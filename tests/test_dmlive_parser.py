import json
from html import escape

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.models import Album, Song
from apps.ingestion.importers.dmlive import DMLiveImporter
from apps.ingestion.parsers.dmlive import parse_source_file
from apps.interviews.models import Interview, SourceSnapshot
from apps.mentions.models import InterviewEntityLink
from apps.transcripts.models import TranscriptParagraph

MEDIAWIKI_NS = "http://www.mediawiki.org/xml/export-0.11/"


def page_xml(page_id, revision_id, title, text, namespace=0):
    return f"""
    <page>
      <title>{escape(title)}</title>
      <ns>{namespace}</ns>
      <id>{page_id}</id>
      <revision>
        <id>{revision_id}</id>
        <timestamp>2026-07-27T12:00:00Z</timestamp>
        <text xml:space="preserve">{escape(text)}</text>
      </revision>
    </page>
    """


def write_xml(path, pages):
    path.write_text(
        f'<mediawiki xmlns="{MEDIAWIKI_NS}">' + "".join(pages) + "</mediawiki>",
        encoding="utf-8",
    )


def interview_text(extra=""):
    return f"""== Notes ==

This was recorded for Radio One.

== Interview transcript ==

Dave: We were writing [[New Life]].

Martin: The album was [[Speak & Spell]].

== Sources ==

[https://example.test/source Original source]

[[Category:Interviews]]
{extra}"""


def test_mediawiki_parser_extracts_sections_speakers_and_categories(tmp_path):
    path = tmp_path / "export.xml"
    write_xml(
        path,
        [
            page_xml(
                10,
                20,
                "1982-03-22 Radio One, London, UK",
                interview_text(),
            )
        ],
    )

    pages = list(parse_source_file(path))

    assert len(pages) == 1
    page = pages[0]
    assert page.page_id == 10
    assert page.revision_id == 20
    assert page.is_interview
    assert page.source_url.endswith("1982-03-22_Radio_One,_London,_UK")
    assert [section.section_type for section in page.sections] == [
        "notes",
        "transcript",
        "sources",
    ]
    assert page.sections[1].paragraphs[0].speaker == "Dave"
    assert page.sections[1].paragraphs[0].text == "We were writing New Life."
    assert "Martin" in page.speakers
    assert "Interviews" in page.categories
    assert "Original source (https://example.test/source)" in page.sections[2].paragraphs[0].text


def test_json_parser_accepts_equivalent_page_shape(tmp_path):
    path = tmp_path / "export.json"
    path.write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_id": 11,
                        "namespace": 0,
                        "title": "2001-01-xx Radio Interview",
                        "revision": {
                            "revision_id": 21,
                            "timestamp": "2026-07-27T12:00:00Z",
                            "text": interview_text(),
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    page = next(parse_source_file(path))

    assert page.page_id == 11
    assert page.revision_id == 21
    assert page.is_interview


@pytest.mark.django_db
def test_import_is_idempotent_and_keeps_private_snapshots(tmp_path):
    path = tmp_path / "export.xml"
    write_xml(
        path,
        [
            page_xml(10, 20, "1982-03-22 Radio One, London, UK", interview_text()),
            page_xml(11, 21, "1983-04-01 Unknown, Madrid, Spain", interview_text().replace("[[Category:Interviews]]", "")),
            page_xml(12, 22, "Category:Interviews", "category page", namespace=14),
        ],
    )
    snapshot_dir = tmp_path / "snapshots"
    importer = DMLiveImporter(snapshot_dir=snapshot_dir)

    first = importer.import_file(path)
    second = importer.import_file(path)

    assert first.pages_seen == 3
    assert first.pages_imported == 2
    assert first.pages_created == 2
    assert first.pages_needs_review == 1
    assert second.pages_unchanged == 2
    assert Interview.objects.count() == 2
    assert SourceSnapshot.objects.count() == 4
    assert len(list(snapshot_dir.glob("*.wikitext"))) == 2
    assert Interview.objects.get(source_page_id=11).classification_status == "needs_review"
    assert Interview.objects.get(source_page_id=10).source_domain == "dmlive.wiki"


@pytest.mark.django_db
def test_changed_source_with_verified_mention_is_preserved_for_review(tmp_path):
    first_path = tmp_path / "first.xml"
    second_path = tmp_path / "second.xml"
    write_xml(
        first_path,
        [page_xml(10, 20, "1982-03-22 Radio One, London, UK", interview_text())],
    )
    write_xml(
        second_path,
        [
            page_xml(
                10,
                23,
                "1982-03-22 Radio One, London, UK",
                interview_text("\nA changed paragraph."),
            )
        ],
    )
    importer = DMLiveImporter(snapshot_dir=tmp_path / "snapshots")
    importer.import_file(first_path)
    interview = Interview.objects.get(source_page_id=10)
    paragraph = TranscriptParagraph.objects.filter(
        transcript__interview=interview, speaker="Dave"
    ).get()
    album = Album.objects.create(title="Speak & Spell", slug="speak-and-spell")
    song = Song.objects.create(title="New Life", slug="new-life", album=album)
    InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        paragraph=paragraph,
        section=paragraph.section,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        review_status=InterviewEntityLink.ReviewStatus.VERIFIED,
    )

    importer.import_file(second_path)

    interview.refresh_from_db()
    paragraph.refresh_from_db()
    link = InterviewEntityLink.objects.get(interview=interview)
    assert interview.transcript_status == Interview.TranscriptStatus.NEEDS_REVIEW
    assert paragraph.text == "We were writing New Life."
    assert link.review_status == InterviewEntityLink.ReviewStatus.NEEDS_REVIEW


@pytest.mark.django_db
def test_mark_missing_marks_absent_pages_without_deleting_them(tmp_path):
    complete_path = tmp_path / "complete.xml"
    partial_path = tmp_path / "partial.xml"
    write_xml(
        complete_path,
        [
            page_xml(10, 20, "1982-03-22 Radio One, London, UK", interview_text()),
            page_xml(11, 21, "1983-04-01 Unknown, Madrid, Spain", interview_text()),
        ],
    )
    write_xml(
        partial_path,
        [page_xml(10, 20, "1982-03-22 Radio One, London, UK", interview_text())],
    )
    importer = DMLiveImporter(snapshot_dir=tmp_path / "snapshots")
    importer.import_file(complete_path)
    summary = importer.import_file(partial_path, mark_missing=True)

    missing = Interview.objects.get(source_page_id=11)
    assert summary.pages_marked_missing == 1
    assert missing.source_present is False
    assert Interview.objects.count() == 2
    assert SourceSnapshot.objects.filter(
        interview=missing, status=SourceSnapshot.Status.MISSING
    ).exists()


def test_command_rejects_non_file_input():
    with pytest.raises(CommandError, match="does not exist"):
        call_command("ingest_dmlive", input="/tmp/definitely-missing-dmlive.xml")


def test_command_dry_run_accepts_local_xml(tmp_path, capsys):
    path = tmp_path / "export.xml"
    write_xml(path, [page_xml(10, 20, "1982-03-22 Radio One", interview_text())])

    call_command("ingest_dmlive", input=str(path), dry_run=True)

    assert '"pages_imported": 1' in capsys.readouterr().out


@pytest.mark.django_db
def test_command_rejects_malformed_xml(tmp_path):
    path = tmp_path / "malformed.xml"
    path.write_text("<mediawiki>", encoding="utf-8")

    with pytest.raises(CommandError):
        call_command("ingest_dmlive", input=str(path))

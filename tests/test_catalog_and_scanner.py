import json
from pathlib import Path

import pytest
from django.core.management import call_command

from apps.catalog.models import Album, Song
from apps.catalog.seed import seed_catalog
from apps.interviews.models import Interview, SourceSnapshot
from apps.mentions import scanner as scanner_module
from apps.mentions.models import InterviewEntityLink
from apps.mentions.scanner import scan_mentions
from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps"
    / "catalog"
    / "data"
    / "depeche_mode_catalog_v1.json"
)


@pytest.mark.django_db
def test_versioned_catalog_seed_is_idempotent():
    first = seed_catalog(CATALOG_PATH)
    second = seed_catalog(CATALOG_PATH)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    expected_song_count = sum(len(album["songs"]) for album in catalog["albums"])
    expected_song_count += len(catalog["standalone_songs"])

    assert first.version == "2.0.0"
    assert first.albums_created == len(catalog["albums"])
    assert first.songs_created == expected_song_count
    assert second.albums_created == 0
    assert second.songs_created == 0
    assert second.albums_updated == len(catalog["albums"])
    assert Album.objects.get(title="Speak & Spell").aliases.get(value="Speak and Spell")
    assert Song.objects.get(title="New Life").album.title == "Speak & Spell"
    assert Song.objects.get(title="I Sometimes Wish I Was Dead").album.title == "Speak & Spell"
    assert Song.objects.get(title="Dreaming of Me").album is None
    assert Song.objects.get(title="Pleasure, Little Treasure").album is None
    assert Song.objects.get(title="Sacred").album.title == "Music for the Masses"
    assert Song.objects.get(title="Easy Tiger").album.title == "Exciter"
    assert Song.objects.get(title="New Life").track_number == 1
    assert Song.objects.get(title="Any Second Now (Voices)").track_number == 10


@pytest.mark.django_db
def test_catalog_seed_supports_compilations_without_detaching_songs(tmp_path):
    manually_marked = Album.objects.create(
        title="Manual Collection",
        slug="manual-collection",
        is_compilation=True,
    )
    path = tmp_path / "compilation-catalog.json"
    path.write_text(
        json.dumps(
            {
                "version": "test-compilation",
                "albums": [
                    {
                        "title": "The Singles 86-98",
                        "release_year": 1998,
                        "is_compilation": True,
                        "songs": ["Enjoy the Silence"],
                    }
                ],
                "standalone_songs": [],
            }
        ),
        encoding="utf-8",
    )

    seed_catalog(path)

    album = Album.objects.get(title="The Singles 86-98")
    assert album.is_compilation is True
    assert Song.objects.get(title="Enjoy the Silence").album == album
    manually_marked.refresh_from_db()
    assert manually_marked.is_compilation is True


@pytest.mark.django_db
def test_catalog_seed_preserves_manual_track_number(tmp_path):
    album = Album.objects.create(title="Speak & Spell", slug="speak-and-spell")
    song = Song.objects.create(
        title="New Life",
        slug="new-life-manual-position",
        album=album,
        track_number=9,
    )
    path = tmp_path / "position-catalog.json"
    path.write_text(
        json.dumps(
            {
                "version": "test-position",
                "albums": [{"title": "Speak & Spell", "songs": ["New Life"]}],
                "standalone_songs": [],
            }
        ),
        encoding="utf-8",
    )

    seed_catalog(path)

    song.refresh_from_db()
    assert song.track_number == 9


@pytest.mark.django_db
def test_catalog_migrates_legacy_titles_and_reports_unmatched_records():
    album = Album.objects.create(title="Music for the Masses", slug="music-for-the-masses")
    Song.objects.create(
        title="Sacrifice",
        slug="sacrifice",
        album=album,
        release_year=1987,
    )
    Song.objects.create(title="A", slug="a", album=album, release_year=1987)

    summary = seed_catalog(CATALOG_PATH)

    assert Song.objects.filter(title="Sacrifice").exists() is False
    assert Song.objects.get(title="Sacred").album == album
    assert "A" in summary.unmatched_existing_songs


def test_catalog_rejects_duplicate_normalized_titles(tmp_path):
    path = tmp_path / "duplicate-catalog.json"
    path.write_text(
        json.dumps(
            {
                "version": "test",
                "albums": [
                    {
                        "title": "Test Album",
                        "release_year": 2026,
                        "songs": ["Same Title"],
                    }
                ],
                "standalone_songs": [{"title": "same-title", "release_year": 2026}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Duplicate normalized song title"):
        seed_catalog(path, dry_run=True)


@pytest.mark.django_db
def test_scanner_prioritizes_internal_links_and_skips_ambiguous_text(tmp_path):
    album = Album.objects.create(title="Violator", slug="violator")
    song = Song.objects.create(title="New Life", slug="new-life", album=album)
    home = Song.objects.create(title="Home", slug="home", album=album)
    interview = Interview.objects.create(
        title="1982-03-22 Radio One",
        slug="1982-03-22-radio-one",
        source_url="https://dmlive.wiki/wiki/1982-03-22_Radio_One",
        source_page_id=200,
    )
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Interview transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        text="We wrote New Life and Home. We also discussed Violator.",
    )
    raw_path = tmp_path / "200-source.wikitext"
    raw_path.write_text("Dave: We wrote [[New Life]] and Home. We also discussed Violator.", encoding="utf-8")
    SourceSnapshot.objects.create(
        interview=interview,
        source_url=interview.source_url,
        source_page_id=200,
        content_hash="a" * 64,
        snapshot_path=str(raw_path),
        status=SourceSnapshot.Status.SUCCESS,
    )

    summary = scan_mentions()

    assert summary.candidates_found == 2
    assert summary.suggestions_created == 2
    assert summary.ambiguous_matches_skipped > 0
    links = list(InterviewEntityLink.objects.order_by("start_offset"))
    assert {link.song_id for link in links if link.song_id} == {song.id}
    assert {link.album_id for link in links if link.album_id} == {album.id}
    assert all(link.review_status == InterviewEntityLink.ReviewStatus.SUGGESTED for link in links)
    assert all(len(link.evidence) <= 280 for link in links)
    assert all(paragraph.text[link.start_offset : link.end_offset] in {"New Life", "Violator"} for link in links)
    assert not InterviewEntityLink.objects.filter(song=home).exists()


@pytest.mark.django_db
def test_explicit_link_allows_ambiguous_song_title(tmp_path):
    album = Album.objects.create(title="Ultra", slug="ultra")
    song = Song.objects.create(title="Home", slug="home", album=album)
    interview = Interview.objects.create(
        title="1997-04-01 Radio Interview",
        slug="1997-04-01-radio-interview",
        source_url="https://dmlive.wiki/wiki/1997-04-01_Radio_Interview",
        source_page_id=201,
    )
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        text="Home was an important song.",
    )
    raw_path = tmp_path / "201-source.wikitext"
    raw_path.write_text("[[Home]] was an important song.", encoding="utf-8")
    SourceSnapshot.objects.create(
        interview=interview,
        source_url=interview.source_url,
        source_page_id=201,
        content_hash="b" * 64,
        snapshot_path=str(raw_path),
        status=SourceSnapshot.Status.SUCCESS,
    )

    summary = scan_mentions()

    assert summary.suggestions_created == 1
    link = InterviewEntityLink.objects.get()
    assert link.song_id == song.id
    assert link.confidence == 1.0
    assert paragraph.text[link.start_offset : link.end_offset] == "Home"


@pytest.mark.django_db
def test_scanner_normalizes_title_variants_and_preserves_source_offsets():
    album = Album.objects.create(title="Construction Time Again", slug="construction-time-again")
    song = Song.objects.create(
        title="The Sun & the Rainfall",
        slug="the-sun-and-the-rainfall",
        album=album,
    )
    interview = Interview.objects.create(
        title="1982-03-22 Radio One",
        slug="1982-03-22-radio-one-normalized",
        source_url="https://dmlive.wiki/wiki/1982-03-22_Radio_One",
        source_page_id=203,
    )
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        text="We discussed The Sun and the Rainfall during the interview.",
    )

    summary = scan_mentions()

    assert summary.suggestions_created == 1
    link = InterviewEntityLink.objects.get(song=song)
    assert paragraph.text[link.start_offset : link.end_offset] == "The Sun and the Rainfall"
    assert float(link.confidence) == 0.92


@pytest.mark.django_db
def test_scanner_sends_song_album_title_collisions_to_review():
    album = Album.objects.create(title="Black Celebration", slug="black-celebration")
    Song.objects.create(title="Black Celebration", slug="black-celebration-song", album=album)
    interview = Interview.objects.create(
        title="1986-02-01 Radio Interview",
        slug="1986-02-01-radio-interview",
        source_url="https://dmlive.wiki/wiki/1986-02-01_Radio_Interview",
        source_page_id=204,
    )
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        text="Black Celebration was discussed.",
    )

    summary = scan_mentions()

    assert summary.candidates_found == 0
    assert summary.ambiguous_matches_skipped == 1
    assert not InterviewEntityLink.objects.exists()


@pytest.mark.django_db
def test_scanner_builds_qa_excerpt_from_question_and_answer_paragraphs():
    album = Album.objects.create(title="Speak & Spell", slug="speak-and-spell")
    Song.objects.create(title="New Life", slug="new-life", album=album)
    Song.objects.create(title="Enjoy the Silence", slug="enjoy-the-silence", album=album)
    interview = Interview.objects.create(
        title="1981-11-09 Radio Interview",
        slug="1981-11-09-radio-interview-qa",
        source_url="https://dmlive.wiki/wiki/1981-11-09_Radio_Interview",
        source_page_id=208,
    )
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Interview transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    question = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        speaker="Question",
        text="Did you write New Life yourselves?",
    )
    answer = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=2,
        speaker="Dave Gahan",
        text="Yes, and we also recorded Enjoy the Silence later.",
    )

    summary = scan_mentions()

    assert summary.qa_excerpts == 2
    links = list(InterviewEntityLink.objects.order_by("start_offset"))
    assert len(links) == 2
    assert all(link.excerpt_type == InterviewEntityLink.ExcerptType.QA for link in links)
    assert all(link.review_status == InterviewEntityLink.ReviewStatus.SUGGESTED for link in links)
    assert all(link.question_paragraph_id == question.id for link in links)
    assert all(link.answer_paragraph_id == answer.id for link in links)


@pytest.mark.django_db
def test_scanner_marks_unpaired_question_excerpt_for_manual_review():
    album = Album.objects.create(title="Speak & Spell", slug="speak-and-spell-unpaired")
    song = Song.objects.create(title="New Life", slug="new-life-unpaired", album=album)
    interview = Interview.objects.create(
        title="1981-11-09 Unpaired Interview",
        slug="1981-11-09-unpaired-interview",
        source_url="https://dmlive.wiki/wiki/1981-11-09_Unpaired_Interview",
        source_page_id=209,
    )
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Interview transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        speaker="Q",
        text="Did you perform New Life live?",
    )

    summary = scan_mentions()
    link = InterviewEntityLink.objects.get(song=song)

    assert summary.needs_review_excerpts == 1
    assert link.excerpt_type == InterviewEntityLink.ExcerptType.NEEDS_REVIEW
    assert link.review_status == InterviewEntityLink.ReviewStatus.NEEDS_REVIEW
    assert link.question_paragraph_id is None
    assert link.answer_paragraph_id is None


@pytest.mark.django_db
def test_repeated_scan_does_not_duplicate_and_preserves_verified_link(tmp_path):
    album = Album.objects.create(title="Violator", slug="violator")
    Song.objects.create(title="Enjoy the Silence", slug="enjoy-the-silence", album=album)
    interview = Interview.objects.create(
        title="1990-03-20 Radio Interview",
        slug="1990-03-20-radio-interview",
        source_url="https://dmlive.wiki/wiki/1990-03-20_Radio_Interview",
        source_page_id=202,
    )
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        text="Enjoy the Silence was written during the sessions.",
    )
    raw_path = tmp_path / "202-source.wikitext"
    raw_path.write_text("Enjoy the Silence was written during the sessions.", encoding="utf-8")
    SourceSnapshot.objects.create(
        interview=interview,
        source_url=interview.source_url,
        source_page_id=202,
        content_hash="c" * 64,
        snapshot_path=str(raw_path),
        status=SourceSnapshot.Status.SUCCESS,
    )

    first = scan_mentions()
    link = InterviewEntityLink.objects.get()
    link.review_status = InterviewEntityLink.ReviewStatus.VERIFIED
    link.save(update_fields=["review_status", "updated_at"])
    second = scan_mentions()

    assert first.suggestions_created == 1
    assert second.suggestions_created == 0
    assert second.suggestions_existing == 1
    assert InterviewEntityLink.objects.count() == 1
    assert InterviewEntityLink.objects.get().review_status == InterviewEntityLink.ReviewStatus.VERIFIED


@pytest.mark.django_db
def test_scan_preserves_repeated_mentions_and_verified_links():
    album = Album.objects.create(title="Violator", slug="violator-repeated")
    song = Song.objects.create(title="New Life", slug="new-life-repeated", album=album)
    interview = Interview.objects.create(
        title="1981-08-23 Television Interview",
        slug="1981-08-23-television-interview-repeated",
        source_url="https://dmlive.wiki/wiki/1981-08-23_Television_Interview",
        source_page_id=205,
    )
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        text="New Life was an early song. We still play New Life today.",
    )

    first = scan_mentions()
    links = list(InterviewEntityLink.objects.filter(song=song).order_by("start_offset"))
    assert first.suggestions_created == 2
    assert len(links) == 2
    assert links[0].end_offset < links[1].start_offset
    assert [paragraph.text[link.start_offset : link.end_offset] for link in links] == [
        "New Life",
        "New Life",
    ]

    links[0].review_status = InterviewEntityLink.ReviewStatus.VERIFIED
    links[0].save(update_fields=["review_status", "updated_at"])
    second = scan_mentions()
    links = list(InterviewEntityLink.objects.filter(song=song).order_by("start_offset"))
    assert second.suggestions_created == 0
    assert second.suggestions_existing == 1
    assert len(links) == 2
    assert links[0].review_status == InterviewEntityLink.ReviewStatus.VERIFIED


@pytest.mark.django_db
def test_scan_report_is_written_as_json(tmp_path):
    report_path = tmp_path / "reports" / "phase5.json"

    call_command("scan_mentions", dry_run=True, report=str(report_path))

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["interviews_scanned"] == 0
    assert report["paragraphs_scanned"] == 0
    assert report["conflicts_detected"] == 0
    assert report["errors"] == []


@pytest.mark.django_db
def test_scan_records_a_failed_interview_and_continues(monkeypatch):
    failing = Interview.objects.create(
        title="Failing interview",
        slug="failing-interview",
        source_url="https://dmlive.wiki/wiki/Failing_interview",
        source_page_id=206,
    )
    healthy = Interview.objects.create(
        title="Healthy interview",
        slug="healthy-interview",
        source_url="https://dmlive.wiki/wiki/Healthy_interview",
        source_page_id=207,
    )
    original = scanner_module.explicit_links_for_interview

    def fail_one(interview, *, snapshot=None):
        if interview.pk == failing.pk:
            raise OSError("snapshot cannot be read")
        return original(interview, snapshot=snapshot)

    monkeypatch.setattr(scanner_module, "explicit_links_for_interview", fail_one)

    summary = scanner_module.scan_mentions()

    assert summary.interviews_scanned == 2
    assert summary.interviews_failed == 1
    assert summary.errors == ["%s:failing-interview: OSError: snapshot cannot be read" % failing.pk]
    assert healthy.slug not in " ".join(summary.errors)

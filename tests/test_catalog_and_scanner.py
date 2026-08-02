from pathlib import Path

import pytest

from apps.catalog.models import Album, Song
from apps.catalog.seed import seed_catalog
from apps.interviews.models import Interview, SourceSnapshot
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

    assert first.version == "1.0.0"
    assert first.albums_created == 15
    assert first.songs_created > 100
    assert second.albums_created == 0
    assert second.songs_created == 0
    assert second.albums_updated == 15
    assert Album.objects.get(title="Speak & Spell").aliases.get(value="Speak and Spell")
    assert Song.objects.get(title="New Life").album.title == "Speak & Spell"


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

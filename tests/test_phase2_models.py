import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.catalog.models import Album, Song
from apps.interviews.models import ImportRun, Interview, SourceSnapshot
from apps.mentions.models import InterviewEntityLink
from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection


def make_interview(*, title="Test interview", page_id=100):
    return Interview.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        source_url=f"https://dmlive.wiki/wiki/{page_id}",
        source_page_id=page_id,
        outlet="Test Channel",
    )


@pytest.mark.django_db
def test_interview_has_canonical_source_defaults_and_stable_identity():
    interview = make_interview()

    assert interview.source_name == "DM Live Wiki"
    assert interview.source_domain == "dmlive.wiki"
    assert interview.source_present is True

    with pytest.raises(IntegrityError):
        make_interview(title="Second interview", page_id=100)


@pytest.mark.django_db
def test_sections_and_paragraph_order_are_scoped_correctly():
    interview = make_interview()
    transcript = Transcript.objects.create(interview=interview)
    first = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Interview transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    second = TranscriptSection.objects.create(
        transcript=transcript,
        order=2,
        heading="Sources",
        section_type=TranscriptSection.SectionType.SOURCES,
    )

    first_paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=first,
        order=1,
        text="First paragraph.",
    )
    second_paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=second,
        order=1,
        text="First source paragraph.",
    )

    assert first_paragraph.order == second_paragraph.order == 1
    assert list(transcript.paragraphs.values_list("id", flat=True)) == [
        first_paragraph.id,
        second_paragraph.id,
    ]

    with pytest.raises(IntegrityError):
        TranscriptParagraph.objects.create(
            transcript=transcript,
            section=first,
            order=1,
            text="Duplicate paragraph order.",
        )


@pytest.mark.django_db
def test_source_snapshot_records_import_run_and_revision():
    interview = make_interview()
    import_run = ImportRun.objects.create(
        input_format=ImportRun.InputFormat.XML,
        input_name="DM+Live-export.xml",
        input_sha256="a" * 64,
    )
    snapshot = SourceSnapshot.objects.create(
        interview=interview,
        import_run=import_run,
        source_url=interview.source_url,
        source_page_id=100,
        source_revision_id=200,
        content_hash="b" * 64,
        status=SourceSnapshot.Status.SUCCESS,
    )

    assert snapshot.import_run_id == import_run.id
    assert snapshot.source_page_id == interview.source_page_id
    assert snapshot.content_hash == "b" * 64


@pytest.mark.django_db
def test_paragraph_mention_requires_matching_section_and_interview():
    interview = make_interview()
    other_interview = make_interview(title="Other interview", page_id=101)
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
        text="Martin mentioned New Life.",
    )
    other_transcript = Transcript.objects.create(interview=other_interview)
    other_section = TranscriptSection.objects.create(
        transcript=other_transcript,
        order=1,
        heading="Interview transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
    )
    album = Album.objects.create(title="Speak & Spell", slug="speak-and-spell")
    song = Song.objects.create(title="New Life", slug="new-life", album=album)

    link = InterviewEntityLink(
        interview=interview,
        song=song,
        paragraph=paragraph,
        section=section,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        start_offset=15,
        end_offset=23,
        paragraph_content_hash="c" * 64,
    )
    link.full_clean()

    link.section = other_section
    with pytest.raises(ValidationError, match="section must belong"):
        link.full_clean()


@pytest.mark.django_db
def test_interview_scope_cannot_reference_paragraph_or_section():
    interview = make_interview()
    transcript = Transcript.objects.create(interview=interview)
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Notes",
        section_type=TranscriptSection.SectionType.NOTES,
    )
    album = Album.objects.create(title="Violator", slug="violator")
    song = Song.objects.create(title="Enjoy the Silence", slug="enjoy-the-silence", album=album)

    link = InterviewEntityLink(
        interview=interview,
        song=song,
        section=section,
        scope=InterviewEntityLink.Scope.INTERVIEW,
    )
    with pytest.raises(ValidationError, match="cannot reference"):
        link.full_clean()


@pytest.mark.django_db
def test_offsets_must_be_provided_as_a_valid_pair():
    interview = make_interview()
    album = Album.objects.create(title="Ultra", slug="ultra")
    song = Song.objects.create(title="Home", slug="home", album=album)
    link = InterviewEntityLink(
        interview=interview,
        song=song,
        start_offset=10,
    )

    with pytest.raises(ValidationError, match="provided together"):
        link.full_clean()

    link.end_offset = 5
    with pytest.raises(ValidationError, match="must not precede"):
        link.full_clean()

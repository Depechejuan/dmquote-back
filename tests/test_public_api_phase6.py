import pytest
from rest_framework.test import APIClient

from apps.catalog.models import Album, Song
from apps.interviews.models import Interview
from apps.mentions.models import InterviewEntityLink
from apps.mentions.scanner import hash_text
from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection


def make_interview(
    *,
    page_id=600,
    title="1984 Radio One interview",
    publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
    classification_status=Interview.ClassificationStatus.INTERVIEW,
    source_present=True,
):
    return Interview.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        date_year=1984,
        date_month=5,
        date_precision=Interview.DatePrecision.MONTH,
        outlet="Radio One",
        medium=Interview.Medium.RADIO,
        location="London",
        source_url=f"https://dmlive.wiki/wiki/{page_id}",
        source_name="DM Live Wiki",
        source_domain="dmlive.wiki",
        source_page_id=page_id,
        source_present=source_present,
        notes="Editorial notes are only public with authorized text.",
        publication_status=publication_status,
        classification_status=classification_status,
        transcript_status=Interview.TranscriptStatus.COMPLETE,
    )


def make_transcript(interview):
    transcript = Transcript.objects.create(
        interview=interview,
        status=Interview.TranscriptStatus.COMPLETE,
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    transcript_section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Interview transcript",
        level=2,
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
        source_anchor="Interview_transcript",
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    private_section = TranscriptSection.objects.create(
        transcript=transcript,
        order=2,
        heading="Private editorial notes",
        level=2,
        section_type=TranscriptSection.SectionType.NOTES,
        source_anchor="Private_editorial_notes",
        publication_status=Interview.PublicationStatus.PRIVATE_ONLY,
    )
    public_paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=transcript_section,
        order=1,
        speaker="Martin Gore",
        text="We discussed New Life in the studio.",
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    private_paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=transcript_section,
        order=2,
        speaker="Martin Gore",
        text="This paragraph is not authorized.",
        publication_status=Interview.PublicationStatus.PRIVATE_ONLY,
    )
    TranscriptParagraph.objects.create(
        transcript=transcript,
        section=private_section,
        order=1,
        text="These notes are not public.",
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    return transcript, transcript_section, public_paragraph, private_paragraph


@pytest.mark.django_db
def test_interview_detail_contains_source_and_citable_authorized_sections():
    interview = make_interview()
    interview.notes = "Authorized editorial note."
    interview.save(update_fields=["notes", "updated_at"])
    _, section, public_paragraph, _ = make_transcript(interview)

    response = APIClient().get(f"/api/v1/interviews/{interview.slug}/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["outlet"] == "Radio One"
    assert payload["medium"] == "radio"
    assert payload["source"] == {
        "name": "DM Live Wiki",
        "domain": "dmlive.wiki",
        "url": interview.source_url,
    }
    assert payload["notes"] == "Authorized editorial note."
    transcript = payload["transcript"]
    assert [item["id"] for item in transcript["sections"]] == [section.id]
    assert transcript["sections"][0]["heading"] == "Interview transcript"
    assert transcript["sections"][0]["source_anchor"] == "Interview_transcript"
    assert transcript["sections"][0]["paragraphs"] == [
        {
            "id": public_paragraph.id,
            "order": 1,
            "speaker": "Martin Gore",
            "text": "We discussed New Life in the studio.",
            "start_seconds": None,
            "end_seconds": None,
        }
    ]
    assert "This paragraph is not authorized." not in response.text
    assert "These notes are not public." not in response.text


@pytest.mark.django_db
def test_public_interview_list_hides_private_missing_and_non_interview_records():
    public = make_interview()
    metadata_only = make_interview(
        page_id=601,
        title="1985 Metadata interview",
        publication_status=Interview.PublicationStatus.METADATA_ONLY,
    )
    make_interview(
        page_id=602,
        title="1986 Private interview",
        publication_status=Interview.PublicationStatus.PRIVATE_ONLY,
    )
    make_interview(
        page_id=603,
        title="1987 Not an interview",
        classification_status=Interview.ClassificationStatus.NOT_INTERVIEW,
    )
    make_interview(
        page_id=604,
        title="1988 Missing source interview",
        source_present=False,
    )

    response = APIClient().get("/api/v1/interviews/")

    assert response.status_code == 200
    results = response.json()["results"]
    assert {item["id"] for item in results} == {public.id, metadata_only.id}


@pytest.mark.django_db
def test_interview_filters_support_year_channel_medium_and_publication_status():
    matching = make_interview()
    other = make_interview(page_id=605, title="1985 Television interview")
    other.date_year = 1985
    other.outlet = "BBC Television"
    other.medium = Interview.Medium.TELEVISION
    other.save(update_fields=["date_year", "outlet", "medium", "updated_at"])

    response = APIClient().get(
        "/api/v1/interviews/?date_year=1984&outlet=Radio+One&medium=radio&publication_status=authorized_text"
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["results"]] == [matching.id]


@pytest.mark.django_db
def test_public_mentions_include_citation_and_hide_suggestions_and_private_text():
    album = Album.objects.create(title="Speak & Spell", slug="speak-and-spell")
    song = Song.objects.create(title="New Life", slug="new-life", album=album)
    interview = make_interview()
    _, section, public_paragraph, private_paragraph = make_transcript(interview)
    public_link = InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        section=section,
        paragraph=public_paragraph,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        method=InterviewEntityLink.Method.RULES,
        confidence=1,
        review_status=InterviewEntityLink.ReviewStatus.VERIFIED,
        start_offset=14,
        end_offset=22,
        evidence=public_paragraph.text,
        paragraph_content_hash=hash_text(public_paragraph.text),
    )
    InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        section=section,
        paragraph=private_paragraph,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        review_status=InterviewEntityLink.ReviewStatus.VERIFIED,
        evidence=private_paragraph.text,
    )
    InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        section=section,
        paragraph=public_paragraph,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        review_status=InterviewEntityLink.ReviewStatus.SUGGESTED,
        evidence="Suggested and hidden",
    )

    for path in (
        f"/api/v1/interviews/{interview.slug}/mentions/",
        f"/api/v1/songs/{song.slug}/mentions/",
        f"/api/v1/albums/{album.slug}/mentions/",
    ):
        response = APIClient().get(path)
        assert response.status_code == 200
        results = response.json()["results"]
        assert [item["id"] for item in results] == [public_link.id]
        mention = results[0]
        assert mention["song"]["title"] == "New Life"
        assert mention["section"] == {
            "id": section.id,
            "order": 1,
            "heading": "Interview transcript",
            "level": 2,
            "section_type": "transcript",
            "source_anchor": "Interview_transcript",
        }
        assert mention["paragraph_id"] == public_paragraph.id
        assert mention["paragraph_order"] == 1
        assert mention["evidence"] == public_paragraph.text
        assert mention["source"]["url"] == interview.source_url
        assert mention["review_status"] == "verified"
        assert "Suggested and hidden" not in response.text
        assert "This paragraph is not authorized." not in response.text


@pytest.mark.django_db
def test_transcript_endpoint_returns_403_for_metadata_only_and_404_for_private():
    metadata_only = make_interview(
        page_id=606,
        title="1989 Pending permission interview",
        publication_status=Interview.PublicationStatus.METADATA_ONLY,
    )
    make_transcript(metadata_only)
    private = make_interview(
        page_id=607,
        title="1990 Private interview",
        publication_status=Interview.PublicationStatus.PRIVATE_ONLY,
    )
    make_transcript(private)

    metadata_response = APIClient().get(
        f"/api/v1/interviews/{metadata_only.slug}/transcript/"
    )
    private_response = APIClient().get(f"/api/v1/interviews/{private.slug}/transcript/")

    assert metadata_response.status_code == 403
    assert private_response.status_code == 404


@pytest.mark.django_db
def test_transcript_endpoint_hides_a_private_transcript_under_an_authorized_interview():
    interview = make_interview(page_id=608, title="1991 Authorized metadata interview")
    transcript, _, _, _ = make_transcript(interview)
    transcript.publication_status = Interview.PublicationStatus.PRIVATE_ONLY
    transcript.save(update_fields=["publication_status", "updated_at"])

    detail_response = APIClient().get(f"/api/v1/interviews/{interview.slug}/")
    transcript_response = APIClient().get(
        f"/api/v1/interviews/{interview.slug}/transcript/"
    )

    assert detail_response.status_code == 200
    assert detail_response.json()["transcript"] is None
    assert transcript_response.status_code == 403


@pytest.mark.django_db
def test_openapi_schema_documents_citation_endpoints():
    response = APIClient().get("/api/schema/?format=json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["openapi"].startswith("3.")
    for path in (
        "/api/v1/interviews/{slug}/mentions/",
        "/api/v1/interviews/{slug}/transcript/",
        "/api/v1/songs/{slug}/mentions/",
        "/api/v1/albums/{slug}/mentions/",
    ):
        assert path in schema["paths"]
        assert "200" in schema["paths"][path]["get"]["responses"]

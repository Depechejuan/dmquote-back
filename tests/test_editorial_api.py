import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import Album, Song
from apps.interviews.models import Interview
from apps.mentions.models import InterviewEntityLink
from apps.mentions.scanner import hash_text
from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection


def make_editorial_interview(page_id=900, title="1981 Editorial interview"):
    interview = Interview.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        date_year=1981,
        date_precision=Interview.DatePrecision.YEAR,
        outlet="BBC",
        source_url=f"https://dmlive.wiki/wiki/{page_id}",
        source_page_id=page_id,
        source_present=True,
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
        speaker="Q",
        text="Q: Which song are you discussing?",
    )
    answer = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=2,
        speaker="A",
        text="A: New Life is the song we are discussing.",
    )
    return interview, transcript, section, question, answer


@pytest.fixture
def staff_api_client(db):
    user = get_user_model().objects.create_superuser(
        username="editorial-staff",
        email="editorial@example.test",
        password="test-password",
    )
    client = APIClient()
    assert client.login(username=user.username, password="test-password")
    return client


@pytest.mark.django_db
def test_editorial_endpoints_require_staff_and_csrf_endpoint_sets_token():
    anonymous = APIClient()
    response = anonymous.get("/api/v1/editorial/queue/")
    assert response.status_code in {401, 403}

    csrf_response = anonymous.get("/api/v1/editorial/csrf/")
    assert csrf_response.status_code == 200
    assert csrf_response.json()["csrf_token"]
    assert "dmquote_csrftoken" in csrf_response.cookies


@pytest.mark.django_db
def test_editorial_queue_can_update_target_excerpt_and_status(staff_api_client):
    album = Album.objects.create(title="Speak & Spell", slug="speak-and-spell-editorial")
    song = Song.objects.create(
        title="New Life",
        slug="new-life-editorial",
        album=album,
        is_b_side=True,
    )
    interview, _, section, question, answer = make_editorial_interview()
    link = InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        section=section,
        paragraph=answer,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        start_offset=3,
        end_offset=11,
        evidence="A: New Life is the song we are discussing.",
        paragraph_content_hash=hash_text(answer.text),
    )

    queue_response = staff_api_client.get("/api/v1/editorial/queue/")
    assert queue_response.status_code == 200
    assert queue_response.json()["results"][0]["id"] == link.id

    interview_response = staff_api_client.get(
        f"/api/v1/editorial/interviews/{interview.slug}/"
    )
    assert interview_response.status_code == 200
    assert interview_response.json()["transcript"]["sections"][0]["paragraphs"][1]["text"] == answer.text

    response = staff_api_client.patch(
        f"/api/v1/editorial/mentions/{link.pk}/",
        {
            "song_id": song.pk,
            "album_id": None,
            "section_id": section.pk,
            "paragraph_id": answer.pk,
            "scope": "paragraph",
            "question_paragraph_id": question.pk,
            "answer_paragraph_id": answer.pk,
            "excerpt_type": "qa",
            "review_status": "verified",
            "evidence": "Q: Which song are you discussing?\nA: New Life is the song we are discussing.",
            "start_offset": 3,
            "end_offset": 11,
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    link.refresh_from_db()
    assert link.review_status == InterviewEntityLink.ReviewStatus.VERIFIED
    assert link.excerpt_type == InterviewEntityLink.ExcerptType.QA
    assert link.question_paragraph_id == question.pk
    assert link.answer_paragraph_id == answer.pk
    assert response.json()["question"]["id"] == question.pk
    assert response.json()["answer"]["id"] == answer.pk

    song_response = staff_api_client.get(f"/api/v1/songs/{song.slug}/")
    assert song_response.json()["is_b_side"] is True


@pytest.mark.django_db
def test_editorial_update_rejects_paragraph_from_another_interview(staff_api_client):
    album = Album.objects.create(title="Ultra", slug="ultra-editorial")
    song = Song.objects.create(title="Home", slug="home-editorial", album=album)
    interview, _, section, _, answer = make_editorial_interview()
    other_interview, _, _, _, other_answer = make_editorial_interview(
        page_id=901,
        title="1982 Other editorial interview",
    )
    link = InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        section=section,
        paragraph=answer,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        evidence=answer.text,
        paragraph_content_hash=hash_text(answer.text),
    )

    response = staff_api_client.patch(
        f"/api/v1/editorial/mentions/{link.pk}/",
        {
            "song_id": song.pk,
            "album_id": None,
            "section_id": section.pk,
            "paragraph_id": other_answer.pk,
            "scope": "paragraph",
        },
        format="json",
    )
    assert response.status_code == 400
    assert "interview" in response.content.decode().lower()
    assert other_interview.pk != interview.pk


@pytest.mark.django_db
def test_editorial_visibility_changes_interview_and_transcript(staff_api_client):
    interview, transcript, section, _, _ = make_editorial_interview()
    response = staff_api_client.patch(
        f"/api/v1/editorial/interviews/{interview.slug}/visibility/",
        {"publication_status": "authorized_text"},
        format="json",
    )
    assert response.status_code == 200
    interview.refresh_from_db()
    transcript.refresh_from_db()
    section.refresh_from_db()
    assert interview.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT
    assert transcript.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT
    assert section.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT

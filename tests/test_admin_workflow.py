import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.catalog.models import Album, Person, Song
from apps.interviews.admin import InterviewAdmin
from apps.interviews.editorial import set_interview_publication_status
from apps.interviews.models import ImportRun, Interview, InterviewParticipant, SourceSnapshot
from apps.mentions.models import InterviewEntityLink
from apps.mentions.scanner import hash_text
from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection


def make_interview(*, page_id=500, title="1984 Radio interview"):
    return Interview.objects.create(
        title=title,
        slug=title.lower().replace(" ", "-"),
        date_year=1984,
        date_precision=Interview.DatePrecision.YEAR,
        outlet="Original outlet",
        source_url=f"https://dmlive.wiki/wiki/{page_id}",
        source_page_id=page_id,
    )


def make_transcript(interview):
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
        speaker="Martin Gore",
        text="We discussed New Life.",
    )
    return transcript, section, paragraph


@pytest.fixture
def admin_client(db):
    user = get_user_model().objects.create_superuser(
        username="phase5-admin",
        email="admin@example.test",
        password="test-password",
    )
    client = Client()
    assert client.login(username=user.username, password="test-password")
    return client


@pytest.mark.django_db
def test_superuser_can_open_all_editorial_admin_queues(admin_client):
    urls = (
        "admin:interviews_interview_changelist",
        "admin:interviews_importrun_changelist",
        "admin:interviews_sourcesnapshot_changelist",
        "admin:transcripts_transcript_changelist",
        "admin:transcripts_transcriptsection_changelist",
        "admin:transcripts_transcriptparagraph_changelist",
        "admin:mentions_interviewentitylink_changelist",
    )

    for url_name in urls:
        response = admin_client.get(reverse(url_name))
        assert response.status_code == 200, url_name


@pytest.mark.django_db
def test_non_staff_user_cannot_open_editorial_admin(admin_client):
    client = Client()
    user = get_user_model().objects.create_user(
        username="phase5-reader",
        password="test-password",
    )
    assert client.login(username=user.username, password="test-password")

    response = client.get(reverse("admin:interviews_interview_changelist"))

    assert response.status_code == 302
    assert "/dmlog/login/" in response["Location"]


@pytest.mark.django_db
def test_interview_admin_action_propagates_authorization_and_privacy(admin_client):
    interview = make_interview()
    transcript, section, paragraph = make_transcript(interview)
    change_url = reverse("admin:interviews_interview_change", args=[interview.pk])

    response = admin_client.post(
        reverse("admin:interviews_interview_changelist"),
        {
            "action": "authorize_interviews",
            "_selected_action": [str(interview.pk)],
        },
        follow=True,
    )

    assert response.status_code == 200
    interview.refresh_from_db()
    transcript.refresh_from_db()
    section.refresh_from_db()
    paragraph.refresh_from_db()
    assert interview.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT
    assert transcript.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT
    assert section.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT
    assert paragraph.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT

    response = admin_client.post(
        reverse("admin:interviews_interview_changelist"),
        {
            "action": "privatize_interviews",
            "_selected_action": [str(interview.pk)],
        },
        follow=True,
    )

    assert response.status_code == 200
    interview.refresh_from_db()
    assert interview.publication_status == Interview.PublicationStatus.PRIVATE_ONLY
    assert Transcript.objects.get(pk=transcript.pk).publication_status == Interview.PublicationStatus.PRIVATE_ONLY
    assert TranscriptSection.objects.get(pk=section.pk).publication_status == Interview.PublicationStatus.PRIVATE_ONLY
    assert TranscriptParagraph.objects.get(pk=paragraph.pk).publication_status == Interview.PublicationStatus.PRIVATE_ONLY
    assert admin_client.get(change_url).status_code == 200


@pytest.mark.django_db
def test_interview_admin_can_correct_metadata_and_participants(admin_client):
    interview = make_interview()
    person = Person.objects.create(name="Dave Gahan", slug="dave-gahan")
    request = RequestFactory().post("/admin/interviews/interview/")
    modeladmin = InterviewAdmin(Interview, admin.site)

    interview.outlet = "Corrected channel"
    interview.location = "Berlin"
    interview.date_year = 1985
    interview.date_precision = Interview.DatePrecision.YEAR
    modeladmin.save_model(request, interview, form=None, change=True)
    InterviewParticipant.objects.create(
        interview=interview,
        person=person,
        role="interviewee",
        sort_order=1,
    )

    interview.refresh_from_db()
    assert interview.outlet == "Corrected channel"
    assert interview.location == "Berlin"
    assert interview.date_year == 1985
    assert list(interview.participant_links.values_list("person__name", flat=True)) == [
        "Dave Gahan"
    ]


@pytest.mark.django_db
def test_editing_interview_metadata_does_not_reset_paragraph_visibility(admin_client):
    interview = make_interview()
    transcript, section, paragraph = make_transcript(interview)
    set_interview_publication_status(
        interview,
        Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    paragraph.publication_status = Interview.PublicationStatus.PRIVATE_ONLY
    paragraph.save(update_fields=["publication_status"])

    request = RequestFactory().post("/admin/interviews/interview/")
    modeladmin = InterviewAdmin(Interview, admin.site)
    interview.outlet = "Editorially corrected channel"
    modeladmin.save_model(request, interview, form=None, change=True)

    transcript.refresh_from_db()
    section.refresh_from_db()
    paragraph.refresh_from_db()
    assert transcript.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT
    assert section.publication_status == Interview.PublicationStatus.AUTHORIZED_TEXT
    assert paragraph.publication_status == Interview.PublicationStatus.PRIVATE_ONLY


@pytest.mark.django_db
def test_interview_admin_review_action_covers_uncategorized_pages(admin_client):
    interview = make_interview()
    interview.classification_status = Interview.ClassificationStatus.INTERVIEW
    interview.transcript_status = Interview.TranscriptStatus.COMPLETE
    interview.save(update_fields=["classification_status", "transcript_status", "updated_at"])

    response = admin_client.post(
        reverse("admin:interviews_interview_changelist"),
        {
            "action": "mark_interviews_for_review",
            "_selected_action": [str(interview.pk)],
        },
        follow=True,
    )

    assert response.status_code == 200
    interview.refresh_from_db()
    assert interview.classification_status == Interview.ClassificationStatus.NEEDS_REVIEW
    assert interview.transcript_status == Interview.TranscriptStatus.NEEDS_REVIEW


@pytest.mark.django_db
def test_mention_admin_verifies_rejects_and_reviews_mentions(admin_client):
    album = Album.objects.create(title="Speak & Spell", slug="speak-and-spell")
    song = Song.objects.create(title="New Life", slug="new-life", album=album)
    interview = make_interview()
    _, section, paragraph = make_transcript(interview)
    link = InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        section=section,
        paragraph=paragraph,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        method=InterviewEntityLink.Method.RULES,
        start_offset=14,
        end_offset=22,
        evidence=paragraph.text,
        paragraph_content_hash=hash_text(paragraph.text),
    )
    changelist = reverse("admin:mentions_interviewentitylink_changelist")

    response = admin_client.post(
        changelist,
        {"action": "verify_mentions", "_selected_action": [str(link.pk)]},
        follow=True,
    )
    assert response.status_code == 200
    link.refresh_from_db()
    assert link.review_status == InterviewEntityLink.ReviewStatus.VERIFIED

    response = admin_client.post(
        changelist,
        {"action": "review_mentions", "_selected_action": [str(link.pk)]},
        follow=True,
    )
    assert response.status_code == 200
    link.refresh_from_db()
    assert link.review_status == InterviewEntityLink.ReviewStatus.NEEDS_REVIEW

    response = admin_client.post(
        changelist,
        {"action": "reject_mentions", "_selected_action": [str(link.pk)]},
        follow=True,
    )
    assert response.status_code == 200
    link.refresh_from_db()
    assert link.review_status == InterviewEntityLink.ReviewStatus.REJECTED


@pytest.mark.django_db
def test_verified_mention_cannot_be_verified_if_relation_is_invalid(admin_client):
    album = Album.objects.create(title="Ultra", slug="ultra")
    song = Song.objects.create(title="Home", slug="home", album=album)
    interview = make_interview()
    other_interview = make_interview(page_id=501, title="1985 TV interview")
    _, section, paragraph = make_transcript(interview)
    _, other_section, _ = make_transcript(other_interview)
    link = InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        section=section,
        paragraph=paragraph,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        review_status=InterviewEntityLink.ReviewStatus.SUGGESTED,
        paragraph_content_hash=hash_text(paragraph.text),
    )
    link.section = other_section
    link.save(update_fields=["section", "updated_at"])

    response = admin_client.post(
        reverse("admin:mentions_interviewentitylink_changelist"),
        {"action": "verify_mentions", "_selected_action": [str(link.pk)]},
        follow=True,
    )

    assert response.status_code == 200
    link.refresh_from_db()
    assert link.review_status == InterviewEntityLink.ReviewStatus.SUGGESTED


@pytest.mark.django_db
def test_admin_flags_mentions_after_paragraph_source_change(admin_client):
    album = Album.objects.create(title="Violator", slug="violator")
    song = Song.objects.create(title="Enjoy the Silence", slug="enjoy-the-silence", album=album)
    interview = make_interview()
    _, section, paragraph = make_transcript(interview)
    link = InterviewEntityLink.objects.create(
        interview=interview,
        song=song,
        section=section,
        paragraph=paragraph,
        scope=InterviewEntityLink.Scope.PARAGRAPH,
        review_status=InterviewEntityLink.ReviewStatus.VERIFIED,
        paragraph_content_hash=hash_text("Old paragraph content."),
    )

    response = admin_client.post(
        reverse("admin:mentions_interviewentitylink_changelist"),
        {
            "action": "flag_changed_paragraph_mentions",
            "_selected_action": [str(link.pk)],
        },
        follow=True,
    )

    assert response.status_code == 200
    link.refresh_from_db()
    assert link.review_status == InterviewEntityLink.ReviewStatus.NEEDS_REVIEW


@pytest.mark.django_db
def test_admin_exposes_import_history_and_read_only_source_records(admin_client):
    interview = make_interview()
    import_run = ImportRun.objects.create(
        input_format=ImportRun.InputFormat.XML,
        input_name="export.xml",
        input_sha256="a" * 64,
        status=ImportRun.Status.SUCCESS,
    )
    snapshot = SourceSnapshot.objects.create(
        interview=interview,
        import_run=import_run,
        source_url=interview.source_url,
        source_page_id=interview.source_page_id,
        content_hash="b" * 64,
        status=SourceSnapshot.Status.SUCCESS,
    )

    assert admin_client.get(
        reverse("admin:interviews_importrun_change", args=[import_run.pk])
    ).status_code == 200
    assert admin_client.get(
        reverse("admin:interviews_sourcesnapshot_change", args=[snapshot.pk])
    ).status_code == 200

    import_admin = admin.site._registry[ImportRun]
    snapshot_admin = admin.site._registry[SourceSnapshot]
    request = RequestFactory().get("/admin/")
    assert import_admin.has_add_permission(request) is False
    assert import_admin.has_delete_permission(request) is False
    assert snapshot_admin.has_add_permission(request) is False
    assert snapshot_admin.has_delete_permission(request) is False


@pytest.mark.django_db
def test_publication_service_keeps_admin_statuses_in_sync():
    interview = make_interview()
    transcript, section, paragraph = make_transcript(interview)

    set_interview_publication_status(
        interview,
        Interview.PublicationStatus.AUTHORIZED_TEXT,
    )

    assert Interview.objects.get(pk=interview.pk).publication_status == "authorized_text"
    assert Transcript.objects.get(pk=transcript.pk).publication_status == "authorized_text"
    assert TranscriptSection.objects.get(pk=section.pk).publication_status == "authorized_text"
    assert TranscriptParagraph.objects.get(pk=paragraph.pk).publication_status == "authorized_text"

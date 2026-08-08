import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from apps.interviews.models import Interview
from apps.transcripts.models import (
    Transcript,
    TranscriptParagraph,
    TranscriptSection,
    TranscriptTranslation,
    TranscriptTranslationRequest,
)
from apps.transcripts.translations import (
    DeepLUsage,
    invalidate_transcript_translations,
    translate_request,
)


def make_public_transcript(*, language="en", page_id=2000):
    interview = Interview.objects.create(
        title=f"Translation interview {page_id}",
        slug=f"translation-interview-{page_id}",
        date_year=1984,
        date_precision=Interview.DatePrecision.YEAR,
        source_url=f"https://dmlive.wiki/wiki/{page_id}",
        source_page_id=page_id,
        source_present=True,
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
        transcript_status=Interview.TranscriptStatus.COMPLETE,
    )
    transcript = Transcript.objects.create(
        interview=interview,
        language=language,
        status=Interview.TranscriptStatus.COMPLETE,
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    section = TranscriptSection.objects.create(
        transcript=transcript,
        order=1,
        heading="Interview transcript",
        section_type=TranscriptSection.SectionType.TRANSCRIPT,
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    paragraph = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=1,
        speaker="Martin",
        text="We discussed New Life.",
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    return interview, transcript, section, paragraph


class FakeDeepLClient:
    def translate(self, texts, *, source_language, target_language):
        return [f"{target_language}: {text}" for text in texts]


@pytest.mark.django_db
def test_public_translation_options_and_idempotent_request():
    interview, transcript, _, _ = make_public_transcript()
    client = APIClient()

    detail = client.get(f"/api/v1/interviews/{interview.slug}/")
    assert detail.status_code == 200
    assert detail.json()["transcript"]["translation_options"] == [
        {"language": "es", "status": "unavailable"}
    ]

    path = f"/api/v1/interviews/{interview.slug}/translations/es/request/"
    created = client.post(path)
    repeated = client.post(path)
    invalid = client.post(
        f"/api/v1/interviews/{interview.slug}/translations/en/request/"
    )

    assert created.status_code == 201
    assert repeated.status_code == 200
    assert invalid.status_code == 400
    assert TranscriptTranslationRequest.objects.filter(transcript=transcript).count() == 1
    assert created.json()["status"] == "queued"
    assert client.get(f"/api/v1/interviews/{interview.slug}/").json()["transcript"][
        "translation_options"
    ] == [{"language": "es", "status": "requested"}]


@pytest.mark.django_db
def test_translation_policy_preserves_other_original_languages():
    interview, _, _, _ = make_public_transcript(language="fr", page_id=2001)

    response = APIClient().get(f"/api/v1/interviews/{interview.slug}/")

    assert response.status_code == 200
    assert response.json()["transcript"]["language"] == "fr"
    assert response.json()["transcript"]["translation_options"] == [
        {"language": "en", "status": "unavailable"},
        {"language": "es", "status": "unavailable"},
    ]


@pytest.mark.django_db
def test_translated_transcript_is_public_only_after_atomic_completion():
    interview, transcript, section, paragraph = make_public_transcript(page_id=2002)
    private = TranscriptParagraph.objects.create(
        transcript=transcript,
        section=section,
        order=2,
        text="Private sentence.",
        publication_status=Interview.PublicationStatus.PRIVATE_ONLY,
    )
    request = TranscriptTranslationRequest.objects.create(
        transcript=transcript,
        target_language="es",
    )

    translated_characters = translate_request(request, FakeDeepLClient())

    assert translated_characters == len(section.heading) + len(paragraph.text)
    request.refresh_from_db()
    assert request.status == TranscriptTranslationRequest.Status.COMPLETED
    translation = TranscriptTranslation.objects.get(transcript=transcript, target_language="es")
    assert translation.sections.count() == 1
    assert translation.paragraphs.count() == 1
    assert translation.sections.get().heading == "es: Interview transcript"
    assert not translation.paragraphs.filter(source_paragraph=private).exists()

    response = APIClient().get(f"/api/v1/interviews/{interview.slug}/transcript/?language=es")
    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "es"
    assert payload["source_language"] == "en"
    assert payload["is_translation"] is True
    assert payload["sections"][0]["paragraphs"][0]["speaker"] == "Martin"
    assert "Private sentence." not in response.text


@pytest.mark.django_db
def test_translation_is_invalidated_when_editor_changes_source_language():
    interview, transcript, _, _ = make_public_transcript(page_id=2003)
    request = TranscriptTranslationRequest.objects.create(
        transcript=transcript,
        target_language="es",
    )
    translate_request(request, FakeDeepLClient())
    user = get_user_model().objects.create_superuser(
        username="translation-editor",
        email="translation-editor@example.test",
        password="test-password",
    )
    client = APIClient()
    assert client.login(username=user.username, password="test-password")

    response = client.patch(
        f"/api/v1/editorial/interviews/{interview.slug}/transcript-language/",
        {"language": "es"},
        format="json",
    )

    assert response.status_code == 200
    transcript.refresh_from_db()
    assert transcript.language == "es"
    assert not TranscriptTranslation.objects.filter(transcript=transcript).exists()
    assert not TranscriptTranslationRequest.objects.filter(pk=request.pk).exists()


@pytest.mark.django_db
def test_private_source_cannot_be_requested_or_exposed():
    interview, transcript, _, _ = make_public_transcript(page_id=2004)
    transcript.publication_status = Interview.PublicationStatus.PRIVATE_ONLY
    transcript.save(update_fields=["publication_status", "updated_at"])

    response = APIClient().post(
        f"/api/v1/interviews/{interview.slug}/translations/es/request/"
    )

    assert response.status_code == 404
    assert not TranscriptTranslationRequest.objects.exists()


@pytest.mark.django_db
@override_settings(DEEPL_MAX_MONTHLY_CHARACTERS=1000)
def test_translation_command_respects_quota_and_keeps_deferred_request(monkeypatch, capsys):
    _, transcript, _, _ = make_public_transcript(page_id=2005)
    request = TranscriptTranslationRequest.objects.create(
        transcript=transcript,
        target_language="es",
    )

    class CommandClient(FakeDeepLClient):
        configured = True

        def usage(self):
            return DeepLUsage(used=995, limit=1000)

    monkeypatch.setattr(
        "apps.transcripts.management.commands.process_translation_requests.DeepLClient",
        CommandClient,
    )

    call_command("process_translation_requests")
    output = json.loads(capsys.readouterr().out)
    request.refresh_from_db()
    assert output["deferred_quota"] == 1
    assert request.status == TranscriptTranslationRequest.Status.QUEUED
    assert not TranscriptTranslation.objects.exists()


@pytest.mark.django_db
def test_invalidation_keeps_pending_request_for_the_same_target():
    _, transcript, _, _ = make_public_transcript(page_id=2006)
    request = TranscriptTranslationRequest.objects.create(
        transcript=transcript,
        target_language="es",
    )
    translate_request(request, FakeDeepLClient())

    invalidate_transcript_translations(transcript)

    assert not TranscriptTranslation.objects.filter(transcript=transcript).exists()
    assert TranscriptTranslationRequest.objects.get(pk=request.pk).status == "queued"

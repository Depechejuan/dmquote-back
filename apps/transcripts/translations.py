from __future__ import annotations

from dataclasses import dataclass

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import (
    Transcript,
    TranscriptSection,
    TranscriptTranslation,
    TranscriptTranslationParagraph,
    TranscriptTranslationRequest,
    TranscriptTranslationSection,
    normalize_language_code,
)


class TranslationError(Exception):
    pass


class TranslationQuotaError(TranslationError):
    pass


def source_language_base(language: str) -> str:
    return normalize_language_code(language).split("-", 1)[0]


def translation_targets(language: str) -> tuple[str, ...]:
    source = source_language_base(language)
    if source == "en":
        return ("es",)
    if source == "es":
        return ("en",)
    return ("en", "es")


def deepl_target_language(language: str) -> str:
    return "EN-GB" if source_language_base(language) == "en" else "ES"


def deepl_source_language(language: str) -> str:
    return normalize_language_code(language).replace("-", "-").upper()


def transcript_is_public(transcript: Transcript) -> bool:
    return (
        transcript.interview.publication_status == "authorized_text"
        and transcript.publication_status == "authorized_text"
    )


def public_sections(transcript: Transcript):
    return transcript.sections.filter(publication_status="authorized_text").prefetch_related(
        "paragraphs"
    ).order_by("order")


def public_paragraphs(section: TranscriptSection):
    return section.paragraphs.filter(publication_status="authorized_text").order_by("order")


def translation_options(transcript: Transcript) -> list[dict[str, str]]:
    available = {
        item.target_language
        for item in transcript.translations.filter(status=TranscriptTranslation.Status.AVAILABLE)
    }
    requested = {
        item.target_language: item.status
        for item in transcript.translation_requests.all()
    }
    options = []
    for language in translation_targets(transcript.language):
        if language in available:
            status = "available"
        elif requested.get(language) in {
            TranscriptTranslationRequest.Status.QUEUED,
            TranscriptTranslationRequest.Status.PROCESSING,
        }:
            status = "requested"
        else:
            status = "unavailable"
        options.append({"language": language, "status": status})
    return options


def invalidate_transcript_translations(transcript: Transcript) -> None:
    """Remove stale output while retaining valid public requests for a future run."""

    TranscriptTranslation.objects.filter(transcript=transcript).delete()
    valid_targets = translation_targets(transcript.language)
    TranscriptTranslationRequest.objects.filter(transcript=transcript).exclude(
        target_language__in=valid_targets
    ).delete()
    TranscriptTranslationRequest.objects.filter(
        transcript=transcript,
        status=TranscriptTranslationRequest.Status.COMPLETED,
    ).update(
        status=TranscriptTranslationRequest.Status.QUEUED,
        completed_at=None,
        error_message="",
    )


@dataclass(frozen=True)
class DeepLUsage:
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class DeepLClient:
    """Minimal server-only adapter for the DeepL API Free text endpoints."""

    def __init__(self, auth_key: str | None = None, base_url: str | None = None):
        self.auth_key = auth_key or settings.DEEPL_AUTH_KEY
        self.base_url = (base_url or settings.DEEPL_API_BASE_URL).rstrip("/")
        self.timeout = settings.DEEPL_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(self.auth_key)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.configured:
            raise TranslationError("DEEPL_AUTH_KEY is not configured.")
        headers = {"Authorization": f"DeepL-Auth-Key {self.auth_key}"}
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {403, 429, 456}:
                raise TranslationQuotaError("DeepL quota is unavailable.") from exc
            raise TranslationError(f"DeepL request failed: {exc.response.status_code}.") from exc
        except httpx.HTTPError as exc:
            raise TranslationError("DeepL could not be reached.") from exc
        return response.json()

    def usage(self) -> DeepLUsage:
        payload = self._request("GET", "/v2/usage")
        return DeepLUsage(
            used=int(payload.get("character_count", 0)),
            limit=int(payload.get("character_limit", settings.DEEPL_MAX_MONTHLY_CHARACTERS)),
        )

    def translate(self, texts: list[str], *, source_language: str, target_language: str) -> list[str]:
        payload = self._request(
            "POST",
            "/v2/translate",
            json={
                "text": texts,
                "source_lang": deepl_source_language(source_language),
                "target_lang": deepl_target_language(target_language),
            },
        )
        translations = payload.get("translations", [])
        if len(translations) != len(texts) or any("text" not in item for item in translations):
            raise TranslationError("DeepL returned an incomplete translation response.")
        return [item["text"] for item in translations]


@dataclass(frozen=True)
class TranslationItem:
    kind: str
    source_id: int
    text: str


def source_items(transcript: Transcript) -> tuple[list[TranscriptSection], list[TranslationItem]]:
    sections = list(public_sections(transcript))
    items: list[TranslationItem] = []
    for section in sections:
        items.append(TranslationItem("section", section.pk, section.heading))
        for paragraph in public_paragraphs(section):
            items.append(TranslationItem("paragraph", paragraph.pk, paragraph.text))
    return sections, items


def source_character_count(transcript: Transcript) -> int:
    _, items = source_items(transcript)
    return sum(len(item.text) for item in items)


def chunk_items(items: list[TranslationItem], max_bytes: int = 100_000) -> list[list[TranslationItem]]:
    chunks: list[list[TranslationItem]] = []
    current: list[TranslationItem] = []
    current_bytes = 0
    for item in items:
        size = len(item.text.encode("utf-8"))
        if size > max_bytes:
            raise TranslationError("A transcript item exceeds the DeepL request limit.")
        if current and current_bytes + size > max_bytes:
            chunks.append(current)
            current = []
            current_bytes = 0
        current.append(item)
        current_bytes += size
    if current:
        chunks.append(current)
    return chunks


def translate_request(request: TranscriptTranslationRequest, client: DeepLClient) -> int:
    transcript = Transcript.objects.select_related("interview").get(pk=request.transcript_id)
    if not transcript_is_public(transcript):
        raise TranslationError("The source transcript is not publicly authorized.")
    if request.target_language not in translation_targets(transcript.language):
        raise TranslationError("The requested target language no longer applies to this transcript.")

    sections, items = source_items(transcript)
    if not items:
        raise TranslationError("The source transcript has no authorized text to translate.")

    translated_by_source_id: dict[tuple[str, int], str] = {}
    for chunk in chunk_items(items):
        translated = client.translate(
            [item.text for item in chunk],
            source_language=transcript.language,
            target_language=request.target_language,
        )
        translated_by_source_id.update(
            {
                (item.kind, item.source_id): translated_text
                for item, translated_text in zip(chunk, translated)
            }
        )

    with transaction.atomic():
        translation, _ = TranscriptTranslation.objects.update_or_create(
            transcript=transcript,
            target_language=request.target_language,
            defaults={"provider": "deepl", "status": TranscriptTranslation.Status.AVAILABLE},
        )
        translation.sections.all().delete()
        translated_sections = [
            TranscriptTranslationSection(
                translation=translation,
                source_section=section,
                order=section.order,
                heading=translated_by_source_id[("section", section.pk)],
                level=section.level,
                section_type=section.section_type,
                source_anchor=section.source_anchor,
            )
            for section in sections
        ]
        TranscriptTranslationSection.objects.bulk_create(translated_sections)
        translated_section_by_source_id = {
            item.source_section_id: item for item in translation.sections.all()
        }
        paragraphs = []
        for section in sections:
            translated_section = translated_section_by_source_id[section.pk]
            for paragraph in public_paragraphs(section):
                paragraphs.append(
                    TranscriptTranslationParagraph(
                        translation=translation,
                        section=translated_section,
                        source_paragraph=paragraph,
                        order=paragraph.order,
                        speaker=paragraph.speaker,
                        text=translated_by_source_id[("paragraph", paragraph.pk)],
                        start_seconds=paragraph.start_seconds,
                        end_seconds=paragraph.end_seconds,
                    )
                )
        TranscriptTranslationParagraph.objects.bulk_create(paragraphs)
        request.status = TranscriptTranslationRequest.Status.COMPLETED
        request.completed_at = timezone.now()
        request.error_message = ""
        request.save(update_fields=["status", "completed_at", "error_message", "updated_at"])
    return sum(len(item.text) for item in items)

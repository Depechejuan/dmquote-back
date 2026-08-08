import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.transcripts.models import TranscriptTranslationRequest
from apps.transcripts.translations import (
    DeepLClient,
    TranslationError,
    TranslationQuotaError,
    source_character_count,
    transcript_is_public,
    translate_request,
)


class Command(BaseCommand):
    help = "Process queued public transcript translation requests through DeepL API Free."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None, help="Maximum requests to process.")
        parser.add_argument(
            "--max-characters",
            type=int,
            default=None,
            help="Optional lower cap for this invocation.",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["limit"] is not None and options["limit"] < 1:
            raise CommandError("--limit must be at least 1.")
        if options["max_characters"] is not None and options["max_characters"] < 1:
            raise CommandError("--max-characters must be at least 1.")

        client = DeepLClient()
        if not client.configured:
            raise CommandError("DEEPL_AUTH_KEY must be configured on the backend server.")
        usage = client.usage()
        remaining = min(usage.remaining, settings.DEEPL_MAX_MONTHLY_CHARACTERS)
        if options["max_characters"] is not None:
            remaining = min(remaining, options["max_characters"])

        recovered_processing = TranscriptTranslationRequest.objects.filter(
            status=TranscriptTranslationRequest.Status.PROCESSING
        ).update(status=TranscriptTranslationRequest.Status.QUEUED)
        queryset = TranscriptTranslationRequest.objects.filter(
            status=TranscriptTranslationRequest.Status.QUEUED
        ).select_related("transcript__interview").order_by("requested_at", "id")
        if options["limit"] is not None:
            queryset = queryset[: options["limit"]]

        summary = {
            "dry_run": options["dry_run"],
            "provider_remaining": usage.remaining,
            "run_character_cap": remaining,
            "processed": 0,
            "translated_characters": 0,
            "failed": 0,
            "skipped_private": 0,
            "deferred_quota": 0,
            "recovered_processing": recovered_processing,
        }
        for translation_request in queryset:
            transcript = translation_request.transcript
            if not transcript_is_public(transcript):
                summary["skipped_private"] += 1
                continue
            characters = source_character_count(transcript)
            if characters > remaining:
                summary["deferred_quota"] += 1
                break
            if options["dry_run"]:
                summary["processed"] += 1
                summary["translated_characters"] += characters
                remaining -= characters
                continue

            translation_request.status = TranscriptTranslationRequest.Status.PROCESSING
            translation_request.save(update_fields=["status", "updated_at"])
            try:
                translated_characters = translate_request(translation_request, client)
            except TranslationQuotaError:
                translation_request.status = TranscriptTranslationRequest.Status.QUEUED
                translation_request.save(update_fields=["status", "updated_at"])
                summary["deferred_quota"] += 1
                break
            except TranslationError as exc:
                translation_request.status = TranscriptTranslationRequest.Status.FAILED
                translation_request.error_message = str(exc)
                translation_request.save(
                    update_fields=["status", "error_message", "updated_at"]
                )
                summary["failed"] += 1
                continue
            summary["processed"] += 1
            summary["translated_characters"] += translated_characters
            remaining -= translated_characters

        self.stdout.write(json.dumps(summary, ensure_ascii=False, sort_keys=True))

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.interviews.models import SourceSnapshot
from apps.transcripts.models import Transcript
from apps.transcripts.translations import invalidate_transcript_translations
from apps.ingestion.parsers.dmlive import detect_transcript_language


class Command(BaseCommand):
    help = "Backfill transcript source languages from the latest DM Live snapshots."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--report")

    def handle(self, *args, **options):
        summary = {
            "dry_run": options["dry_run"],
            "transcripts_scanned": 0,
            "languages_detected": 0,
            "transcripts_updated": 0,
            "snapshots_missing": 0,
            "read_errors": 0,
            "errors": [],
        }
        for transcript in Transcript.objects.select_related("interview").iterator():
            summary["transcripts_scanned"] += 1
            snapshot = (
                SourceSnapshot.objects.filter(interview_id=transcript.interview_id)
                .order_by("-retrieved_at")
                .first()
            )
            if snapshot is None or not snapshot.snapshot_path:
                summary["snapshots_missing"] += 1
                continue
            path = Path(snapshot.snapshot_path)
            if not path.is_absolute():
                from django.conf import settings

                path = settings.BASE_DIR / path
            try:
                language = detect_transcript_language(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError) as exc:
                summary["read_errors"] += 1
                summary["errors"].append(
                    f"{transcript.interview_id}:{type(exc).__name__}: {exc}"
                )
                continue
            if not language:
                continue
            summary["languages_detected"] += 1
            if transcript.language == language:
                continue
            summary["transcripts_updated"] += 1
            if not options["dry_run"]:
                with transaction.atomic():
                    transcript.language = language
                    transcript.save(update_fields=["language", "updated_at"])
                    invalidate_transcript_translations(transcript)

        payload = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        if options.get("report"):
            report_path = Path(options["report"]).expanduser()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(payload + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(payload))

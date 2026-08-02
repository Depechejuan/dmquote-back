import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.interviews.models import ImportRun, Interview, SourceSnapshot
from apps.mentions.models import InterviewEntityLink
from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection


class Command(BaseCommand):
    help = "Generate a local editorial audit report for imported DM Live records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            help="Optional local JSON path. The report is always also printed to stdout.",
        )
        parser.add_argument("--source-domain", default="dmlive.wiki")

    def handle(self, *args, **options):
        report = build_report(options["source_domain"])
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        output = options.get("output")
        if output:
            path = Path(output).expanduser()
            if path.is_dir():
                raise CommandError("--output must point to a file, not a directory.")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(serialized + "\n", encoding="utf-8")
        self.stdout.write(serialized)


def build_report(source_domain: str = "dmlive.wiki") -> dict:
    interviews = Interview.objects.filter(source_domain=source_domain)
    latest_import = ImportRun.objects.filter(source_name="DM Live Wiki").first()
    latest_snapshots = SourceSnapshot.objects.filter(import_run=latest_import)
    latest_snapshot_counts = Counter(
        latest_snapshots.values_list("status", flat=True)
    )
    links = InterviewEntityLink.objects.filter(interview__source_domain=source_domain)

    channels = Counter(
        interview.outlet.strip() or "(incomplete)"
        for interview in interviews.only("outlet")
    )
    transcript_statuses = Counter(
        interviews.values_list("transcript_status", flat=True)
    )
    classification_statuses = Counter(
        interviews.values_list("classification_status", flat=True)
    )
    publication_statuses = Counter(
        interviews.values_list("publication_status", flat=True)
    )
    mention_statuses = Counter(links.values_list("review_status", flat=True))

    import_errors = []
    if latest_import and latest_import.error_message:
        import_errors = [line for line in latest_import.error_message.splitlines() if line]

    interviews_without_source = interviews.filter(
        source_url=""
    ).count() + interviews.filter(source_name="").count()
    mentions_needing_review = mention_statuses.get(
        InterviewEntityLink.ReviewStatus.NEEDS_REVIEW, 0
    )
    transcript_needing_review = transcript_statuses.get(
        Interview.TranscriptStatus.NEEDS_REVIEW, 0
    )

    return {
        "generated_at": timezone.now().isoformat(),
        "source": {
            "name": "DM Live Wiki",
            "domain": source_domain,
            "canonical_url": "https://dmlive.wiki/",
        },
        "latest_import": (
            {
                "id": latest_import.id,
                "input_name": latest_import.input_name,
                "input_format": latest_import.input_format,
                "input_sha256": latest_import.input_sha256,
                "status": latest_import.status,
                "pages_read": latest_import.pages_seen,
                "pages_created": latest_import.pages_created,
                "pages_updated": latest_import.pages_updated,
                "pages_skipped": latest_import.pages_skipped,
                "pages_failed": latest_import.pages_failed,
                "errors": import_errors,
            }
            if latest_import
            else None
        ),
        "import_totals": {
            "pages_read": latest_import.pages_seen if latest_import else 0,
            "pages_imported": latest_snapshot_counts.get("success", 0)
            + latest_snapshot_counts.get("not_modified", 0),
            "pages_classified_as_interviews": classification_statuses.get("interview", 0),
            "pages_pending_classification": classification_statuses.get("needs_review", 0),
            "pages_skipped": latest_import.pages_skipped if latest_import else 0,
            "pages_failed": latest_import.pages_failed if latest_import else 0,
            "pages_marked_missing": interviews.filter(source_present=False).count(),
        },
        "catalog": {
            "interviews": interviews.count(),
            "sections": TranscriptSection.objects.filter(
                transcript__interview__source_domain=source_domain
            ).count(),
            "paragraphs": TranscriptParagraph.objects.filter(
                transcript__interview__source_domain=source_domain
            ).count(),
            "transcripts": Transcript.objects.filter(
                interview__source_domain=source_domain
            ).count(),
        },
        "editorial_audit": {
            "interviews_with_incomplete_channel": channels.get("(incomplete)", 0),
            "interviews_without_source": interviews_without_source,
            "interviews_source_present": interviews.filter(source_present=True).count(),
            "channels": dict(sorted(channels.items())),
            "transcript_statuses": dict(sorted(transcript_statuses.items())),
            "classification_statuses": dict(sorted(classification_statuses.items())),
            "publication_statuses": dict(sorted(publication_statuses.items())),
        },
        "mentions": {
            "songs_detected": links.filter(song__isnull=False).values("song_id").distinct().count(),
            "albums_detected": links.filter(album__isnull=False).values("album_id").distinct().count(),
            "total": links.count(),
            "suggested": mention_statuses.get(InterviewEntityLink.ReviewStatus.SUGGESTED, 0),
            "verified": mention_statuses.get(InterviewEntityLink.ReviewStatus.VERIFIED, 0),
            "rejected": mention_statuses.get(InterviewEntityLink.ReviewStatus.REJECTED, 0),
            "needs_review": mentions_needing_review,
            "conflicts": mentions_needing_review + transcript_needing_review,
            "review_required_before_publication": mention_statuses.get(
                InterviewEntityLink.ReviewStatus.SUGGESTED, 0
            )
            + mentions_needing_review,
        },
        "duplicates_avoided": {
            "not_modified_snapshots_in_latest_import": latest_snapshot_counts.get(
                "not_modified", 0
            ),
            "source_snapshots_total": SourceSnapshot.objects.filter(
                interview__source_domain=source_domain
            ).count(),
        },
        "errors": import_errors,
        "audit_flags": [
            flag
            for flag, condition in (
                (
                    "Manual review required for automatic mentions.",
                    mention_statuses.get(InterviewEntityLink.ReviewStatus.SUGGESTED, 0) > 0,
                ),
                (
                    "Some interviews have incomplete channel metadata.",
                    channels.get("(incomplete)", 0) > 0,
                ),
                (
                    "Some interviews or mentions require review after source changes.",
                    mentions_needing_review + transcript_needing_review > 0,
                ),
            )
            if condition
        ],
    }

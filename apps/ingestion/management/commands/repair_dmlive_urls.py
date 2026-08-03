import json

from django.core.management.base import BaseCommand

from apps.interviews.models import Interview, SourceSnapshot
from apps.interviews.source_urls import build_dmlive_url


class Command(BaseCommand):
    help = "Repair DM Live Wiki interview and snapshot URLs using canonical page titles."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        interviews = list(
            Interview.objects.filter(source_domain="dmlive.wiki").only("id", "title", "source_url")
        )
        changed_interviews = []
        changed_snapshots = []
        canonical_urls = {
            interview.id: build_dmlive_url(interview.title) for interview in interviews
        }

        for interview in interviews:
            canonical_url = canonical_urls[interview.id]
            if interview.source_url != canonical_url:
                interview.source_url = canonical_url
                changed_interviews.append(interview)

        snapshots = list(
            SourceSnapshot.objects.filter(interview_id__in=canonical_urls).only(
                "id", "interview_id", "source_url"
            )
        )
        for snapshot in snapshots:
            canonical_url = canonical_urls[snapshot.interview_id]
            if snapshot.source_url != canonical_url:
                snapshot.source_url = canonical_url
                changed_snapshots.append(snapshot)

        if not dry_run:
            if changed_interviews:
                Interview.objects.bulk_update(changed_interviews, ["source_url"])
            if changed_snapshots:
                SourceSnapshot.objects.bulk_update(changed_snapshots, ["source_url"])

        result = {
            "dry_run": dry_run,
            "interviews_checked": len(interviews),
            "interviews_changed": len(changed_interviews),
            "snapshots_checked": len(snapshots),
            "snapshots_changed": len(changed_snapshots),
        }
        self.stdout.write(json.dumps(result, sort_keys=True))

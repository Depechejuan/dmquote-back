import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.interviews.models import Interview
from apps.mentions.scanner import scan_mentions


class Command(BaseCommand):
    help = "Suggest song and album mentions from imported interview paragraphs."

    def add_arguments(self, parser):
        parser.add_argument("--interview-slug")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--report",
            help="Write the JSON scan report to this local path.",
        )

    def handle(self, *args, **options):
        interview = None
        if options.get("interview_slug"):
            try:
                interview = Interview.objects.get(slug=options["interview_slug"])
            except Interview.DoesNotExist as exc:
                raise CommandError("Interview not found") from exc
        summary = scan_mentions(interview=interview, dry_run=options["dry_run"])
        payload = summary.as_dict()
        if options.get("report"):
            report_path = Path(options["report"]).expanduser()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        self.stdout.write(self.style.SUCCESS(json.dumps(payload, ensure_ascii=False, sort_keys=True)))

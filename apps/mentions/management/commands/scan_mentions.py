import json

from django.core.management.base import BaseCommand, CommandError

from apps.interviews.models import Interview
from apps.mentions.scanner import scan_mentions


class Command(BaseCommand):
    help = "Suggest song and album mentions from imported interview paragraphs."

    def add_arguments(self, parser):
        parser.add_argument("--interview-slug")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        interview = None
        if options.get("interview_slug"):
            try:
                interview = Interview.objects.get(slug=options["interview_slug"])
            except Interview.DoesNotExist as exc:
                raise CommandError("Interview not found") from exc
        summary = scan_mentions(interview=interview, dry_run=options["dry_run"])
        self.stdout.write(self.style.SUCCESS(json.dumps(summary.__dict__, sort_keys=True)))

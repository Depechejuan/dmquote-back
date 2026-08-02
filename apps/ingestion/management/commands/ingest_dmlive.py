import json
from pathlib import Path
from xml.etree.ElementTree import ParseError

from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.importers.dmlive import DMLiveImporter, DMLiveImportError


class Command(BaseCommand):
    help = "Import a local DM Live XML or JSON export without making network requests."

    def add_arguments(self, parser):
        parser.add_argument("--input", help="Path to a local XML or JSON export.")
        parser.add_argument(
            "--format",
            choices=["auto", "xml", "json"],
            default="auto",
            help="Input format. Defaults to the file extension.",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--bulk",
            action="store_true",
            help="Use batched database writes for a large local export.",
        )
        parser.add_argument(
            "--mark-missing",
            action="store_true",
            help="Treat the input as a complete export and mark absent source pages as missing.",
        )

    def handle(self, *args, **options):
        input_name = options.get("input")
        if not input_name:
            raise CommandError("A local --input XML or JSON file is required.")
        if Path(input_name).is_dir():
            raise CommandError("--input must point to a file, not a directory.")

        try:
            summary = DMLiveImporter().import_file(
                input_name,
                input_format=options["format"],
                dry_run=options["dry_run"],
                bulk=options["bulk"],
                mark_missing=options["mark_missing"],
            )
        except (DMLiveImportError, ParseError, ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        message = json.dumps(summary.as_dict(), ensure_ascii=False, sort_keys=True)
        style = self.style.WARNING if options["dry_run"] else self.style.SUCCESS
        self.stdout.write(style(message))

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.seed import seed_catalog

DEFAULT_CATALOG = Path(__file__).resolve().parents[2] / "data" / "depeche_mode_catalog_v1.json"


class Command(BaseCommand):
    help = "Load a versioned song and album catalogue from a local JSON file."

    def add_arguments(self, parser):
        parser.add_argument("--input", default=str(DEFAULT_CATALOG))
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        input_path = Path(options["input"])
        if not input_path.is_file():
            raise CommandError(f"Catalog file does not exist: {input_path}")
        try:
            summary = seed_catalog(input_path, dry_run=options["dry_run"])
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(json.dumps(summary.__dict__, sort_keys=True)))

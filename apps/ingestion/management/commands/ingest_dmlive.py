from django.core.management.base import BaseCommand, CommandError

from apps.ingestion.adapters.dmlive import DMLiveAdapter


class Command(BaseCommand):
    help = "Prepare a DM Live import. Network access is opt-in and remains unavailable in the skeleton."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--allow-network",
            action="store_true",
            help="Explicitly acknowledge that network access has been authorised.",
        )

    def handle(self, *args, **options):
        if not options["allow_network"]:
            raise CommandError(
                "Import is disabled by default. Use --allow-network only after source-owner permission."
            )
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run requested; no network operation performed."))
            return
        try:
            DMLiveAdapter()
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc
        raise CommandError("The source importer is intentionally not implemented in the skeleton.")

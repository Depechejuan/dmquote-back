import json

from django.core.management.base import BaseCommand, CommandError

from apps.interviews.models import Interview
from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection


class Command(BaseCommand):
    help = "Authorize imported DM Live interview text for the public API."

    def add_arguments(self, parser):
        parser.add_argument("--source-domain", default="dmlive.wiki")
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Required confirmation that the source owner authorized publication.",
        )

    def handle(self, *args, **options):
        if not options["confirm"]:
            raise CommandError("Pass --confirm only after source publication permission is confirmed.")

        interviews = Interview.objects.filter(
            source_domain=options["source_domain"],
            source_present=True,
        ).exclude(classification_status=Interview.ClassificationStatus.NOT_INTERVIEW)
        interview_ids = list(interviews.values_list("id", flat=True))
        authorized_interviews = interviews.update(
            publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT
        )
        authorized_transcripts = Transcript.objects.filter(
            interview_id__in=interview_ids
        ).update(publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT)
        authorized_sections = TranscriptSection.objects.filter(
            transcript__interview_id__in=interview_ids
        ).update(publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT)
        authorized_paragraphs = TranscriptParagraph.objects.filter(
            transcript__interview_id__in=interview_ids
        ).update(publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT)

        self.stdout.write(
            self.style.SUCCESS(
                json.dumps(
                    {
                        "source_domain": options["source_domain"],
                        "authorized_interviews": authorized_interviews,
                        "authorized_transcripts": authorized_transcripts,
                        "authorized_sections": authorized_sections,
                        "authorized_paragraphs": authorized_paragraphs,
                        "mentions_changed": 0,
                    },
                    sort_keys=True,
                )
            )
        )

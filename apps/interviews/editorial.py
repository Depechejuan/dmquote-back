from __future__ import annotations

from django.db import transaction

from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection

from .models import Interview


@transaction.atomic
def set_interview_publication_status(interview: Interview, status: str) -> None:
    """Keep the publication status of an interview and its transcript in sync."""

    interview.publication_status = status
    interview.save(update_fields=["publication_status", "updated_at"])

    transcript = Transcript.objects.filter(interview_id=interview.pk).first()
    if transcript is None:
        return

    transcript.publication_status = status
    transcript.save(update_fields=["publication_status", "updated_at"])
    TranscriptSection.objects.filter(transcript_id=transcript.pk).update(
        publication_status=status
    )
    TranscriptParagraph.objects.filter(transcript_id=transcript.pk).update(
        publication_status=status
    )

from django.db import models

from apps.interviews.models import Interview


class Transcript(models.Model):
    interview = models.OneToOneField(
        Interview, on_delete=models.CASCADE, related_name="transcript"
    )
    language = models.CharField(max_length=12, default="en")
    status = models.CharField(
        max_length=20,
        choices=Interview.TranscriptStatus.choices,
        default=Interview.TranscriptStatus.MISSING,
    )
    publication_status = models.CharField(
        max_length=24,
        choices=Interview.PublicationStatus.choices,
        default=Interview.PublicationStatus.PRIVATE_ONLY,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Transcript: {self.interview}"


class TranscriptParagraph(models.Model):
    transcript = models.ForeignKey(
        Transcript, on_delete=models.CASCADE, related_name="paragraphs"
    )
    order = models.PositiveIntegerField()
    speaker = models.CharField(max_length=160, blank=True)
    text = models.TextField()
    start_seconds = models.PositiveIntegerField(null=True, blank=True)
    end_seconds = models.PositiveIntegerField(null=True, blank=True)
    publication_status = models.CharField(
        max_length=24,
        choices=Interview.PublicationStatus.choices,
        default=Interview.PublicationStatus.PRIVATE_ONLY,
    )

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "order"], name="unique_transcript_paragraph_order"
            )
        ]

    def __str__(self) -> str:
        return f"{self.transcript} paragraph {self.order}"

import re

from django.core.exceptions import ValidationError
from django.db import models

from apps.interviews.models import Interview

LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z]{2,4})?$")


def normalize_language_code(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def validate_language_code(value: str) -> None:
    if not LANGUAGE_CODE_RE.fullmatch(normalize_language_code(value)):
        raise ValidationError("Use a two- or three-letter ISO/BCP-47 language code.")


class Transcript(models.Model):
    interview = models.OneToOneField(
        Interview, on_delete=models.CASCADE, related_name="transcript"
    )
    language = models.CharField(
        max_length=12,
        default="en",
        validators=[validate_language_code],
        help_text="Original transcript language as an ISO/BCP-47 code.",
    )
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

    def save(self, *args, **kwargs):
        self.language = normalize_language_code(self.language)
        super().save(*args, **kwargs)


class TranscriptSection(models.Model):
    class SectionType(models.TextChoices):
        NOTES = "notes", "Notes"
        AUDIO = "audio", "Audio"
        TRANSCRIPT = "transcript", "Transcript"
        SOURCES = "sources", "Sources"
        TRACKLIST = "tracklist", "Tracklist"
        VIDEO = "video", "Video"
        OTHER = "other", "Other"

    transcript = models.ForeignKey(
        Transcript, on_delete=models.CASCADE, related_name="sections"
    )
    order = models.PositiveIntegerField()
    heading = models.CharField(max_length=255)
    level = models.PositiveSmallIntegerField(default=2)
    section_type = models.CharField(
        max_length=16, choices=SectionType.choices, default=SectionType.OTHER
    )
    source_anchor = models.SlugField(max_length=180, blank=True)
    publication_status = models.CharField(
        max_length=24,
        choices=Interview.PublicationStatus.choices,
        default=Interview.PublicationStatus.PRIVATE_ONLY,
    )

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "order"], name="unique_transcript_section_order"
            )
        ]

    def __str__(self) -> str:
        return f"{self.transcript} — {self.heading}"


class TranscriptParagraph(models.Model):
    transcript = models.ForeignKey(
        Transcript, on_delete=models.CASCADE, related_name="paragraphs"
    )
    section = models.ForeignKey(
        TranscriptSection, on_delete=models.CASCADE, related_name="paragraphs"
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
        ordering = ["section__order", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "order"], name="unique_section_paragraph_order"
            )
        ]

    def __str__(self) -> str:
        return f"{self.transcript} — {self.section.heading} paragraph {self.order}"


class TranscriptTranslation(models.Model):
    """A published machine translation of one source transcript."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"

    transcript = models.ForeignKey(
        Transcript,
        on_delete=models.CASCADE,
        related_name="translations",
    )
    target_language = models.CharField(max_length=12, validators=[validate_language_code])
    provider = models.CharField(max_length=32, default="deepl")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.AVAILABLE)
    translated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["target_language"]
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "target_language"],
                name="unique_transcript_translation_language",
            )
        ]

    def save(self, *args, **kwargs):
        self.target_language = normalize_language_code(self.target_language)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.transcript} → {self.target_language}"


class TranscriptTranslationSection(models.Model):
    translation = models.ForeignKey(
        TranscriptTranslation,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    source_section = models.ForeignKey(TranscriptSection, on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    heading = models.CharField(max_length=255)
    level = models.PositiveSmallIntegerField(default=2)
    section_type = models.CharField(
        max_length=16,
        choices=TranscriptSection.SectionType.choices,
        default=TranscriptSection.SectionType.OTHER,
    )
    source_anchor = models.SlugField(max_length=180, blank=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["translation", "order"],
                name="unique_translation_section_order",
            ),
            models.UniqueConstraint(
                fields=["translation", "source_section"],
                name="unique_translation_source_section",
            ),
        ]


class TranscriptTranslationParagraph(models.Model):
    translation = models.ForeignKey(
        TranscriptTranslation,
        on_delete=models.CASCADE,
        related_name="paragraphs",
    )
    section = models.ForeignKey(
        TranscriptTranslationSection,
        on_delete=models.CASCADE,
        related_name="paragraphs",
    )
    source_paragraph = models.ForeignKey(TranscriptParagraph, on_delete=models.CASCADE)
    order = models.PositiveIntegerField()
    speaker = models.CharField(max_length=160, blank=True)
    text = models.TextField()
    start_seconds = models.PositiveIntegerField(null=True, blank=True)
    end_seconds = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["section__order", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "order"],
                name="unique_translation_paragraph_order",
            ),
            models.UniqueConstraint(
                fields=["translation", "source_paragraph"],
                name="unique_translation_source_paragraph",
            ),
        ]


class TranscriptTranslationRequest(models.Model):
    """A de-duplicated public request for a target language."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    transcript = models.ForeignKey(
        Transcript,
        on_delete=models.CASCADE,
        related_name="translation_requests",
    )
    target_language = models.CharField(max_length=12, validators=[validate_language_code])
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    requested_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["requested_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["transcript", "target_language"],
                name="unique_translation_request_language",
            )
        ]

    def save(self, *args, **kwargs):
        self.target_language = normalize_language_code(self.target_language)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.transcript} → {self.target_language} ({self.status})"

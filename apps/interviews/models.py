from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse

from apps.catalog.models import Person


class ImportRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        PARTIAL = "partial", "Partial"
        FAILED = "failed", "Failed"

    class InputFormat(models.TextChoices):
        XML = "xml", "XML"
        JSON = "json", "JSON"

    source_name = models.CharField(max_length=120, default="DM Live Wiki")
    input_format = models.CharField(max_length=8, choices=InputFormat.choices)
    input_name = models.CharField(max_length=500)
    input_sha256 = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.RUNNING)
    pages_seen = models.PositiveIntegerField(default=0)
    pages_created = models.PositiveIntegerField(default=0)
    pages_updated = models.PositiveIntegerField(default=0)
    pages_skipped = models.PositiveIntegerField(default=0)
    pages_failed = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"{self.source_name} import {self.started_at:%Y-%m-%d %H:%M:%S}"


class Interview(models.Model):
    class DatePrecision(models.TextChoices):
        DAY = "day", "Day"
        MONTH = "month", "Month"
        YEAR = "year", "Year"
        UNKNOWN = "unknown", "Unknown"

    class TranscriptStatus(models.TextChoices):
        MISSING = "missing", "Missing"
        PARTIAL = "partial", "Partial"
        COMPLETE = "complete", "Complete"
        NEEDS_REVIEW = "needs_review", "Needs review"

    class PublicationStatus(models.TextChoices):
        METADATA_ONLY = "metadata_only", "Metadata only"
        AUTHORIZED_TEXT = "authorized_text", "Authorized text"
        PENDING_PERMISSION = "pending_permission", "Pending permission"
        PRIVATE_ONLY = "private_only", "Private only"

    class Medium(models.TextChoices):
        RADIO = "radio", "Radio"
        TELEVISION = "television", "Television"
        MAGAZINE = "magazine", "Magazine"
        NEWSPAPER = "newspaper", "Newspaper"
        ONLINE = "online", "Online"
        PRESS_CONFERENCE = "press_conference", "Press conference"
        OTHER = "other", "Other"
        UNKNOWN = "unknown", "Unknown"

    class ClassificationStatus(models.TextChoices):
        INTERVIEW = "interview", "Interview"
        NEEDS_REVIEW = "needs_review", "Needs review"
        NOT_INTERVIEW = "not_interview", "Not an interview"

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=280, unique=True)
    date_year = models.PositiveSmallIntegerField(null=True, blank=True)
    date_month = models.PositiveSmallIntegerField(null=True, blank=True)
    date_day = models.PositiveSmallIntegerField(null=True, blank=True)
    date_precision = models.CharField(
        max_length=12, choices=DatePrecision.choices, default=DatePrecision.UNKNOWN
    )
    outlet = models.CharField(max_length=255, blank=True)
    medium = models.CharField(max_length=24, choices=Medium.choices, default=Medium.UNKNOWN)
    classification_status = models.CharField(
        max_length=16,
        choices=ClassificationStatus.choices,
        default=ClassificationStatus.INTERVIEW,
    )
    location = models.CharField(max_length=255, blank=True)
    source_url = models.URLField(max_length=500)
    source_name = models.CharField(max_length=120, default="DM Live Wiki")
    source_domain = models.CharField(max_length=120, default="dmlive.wiki")
    source_page_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    source_revision_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_revision_timestamp = models.DateTimeField(null=True, blank=True)
    source_content_hash = models.CharField(max_length=128, blank=True)
    source_present = models.BooleanField(default=True)
    audio_url = models.URLField(max_length=500, blank=True)
    transcript_status = models.CharField(
        max_length=20, choices=TranscriptStatus.choices, default=TranscriptStatus.MISSING
    )
    publication_status = models.CharField(
        max_length=24,
        choices=PublicationStatus.choices,
        default=PublicationStatus.METADATA_ONLY,
    )
    notes = models.TextField(blank=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_year", "-date_month", "-date_day", "title"]
        indexes = [
            models.Index(
                fields=["date_year", "transcript_status"], name="interview_date_status_idx"
            ),
            models.Index(fields=["publication_status"], name="interview_publication_idx"),
            models.Index(fields=["source_present", "source_domain"], name="interview_source_state_idx"),
            models.Index(fields=["classification_status"], name="interview_classification_idx"),
        ]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("interview-detail", kwargs={"slug": self.slug})

    @property
    def date_display(self) -> str:
        if self.date_year is None:
            return "Unknown date"
        if self.date_precision == self.DatePrecision.DAY and self.date_month and self.date_day:
            return f"{self.date_year:04d}-{self.date_month:02d}-{self.date_day:02d}"
        if self.date_precision == self.DatePrecision.MONTH and self.date_month:
            return f"{self.date_year:04d}-{self.date_month:02d}"
        return str(self.date_year)

    def clean(self) -> None:
        if self.date_month is not None and not 1 <= self.date_month <= 12:
            raise ValidationError({"date_month": "Month must be between 1 and 12."})
        if self.date_day is not None and not 1 <= self.date_day <= 31:
            raise ValidationError({"date_day": "Day must be between 1 and 31."})
        if self.date_precision == self.DatePrecision.DAY and not (
            self.date_year and self.date_month and self.date_day
        ):
            raise ValidationError("Day precision requires year, month and day.")


class InterviewParticipant(models.Model):
    interview = models.ForeignKey(
        Interview, on_delete=models.CASCADE, related_name="participant_links"
    )
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="interview_links")
    role = models.CharField(max_length=120, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "person__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["interview", "person"], name="unique_interview_participant"
            )
        ]

    def __str__(self) -> str:
        return f"{self.interview} — {self.person}"


class SourceSnapshot(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        NOT_MODIFIED = "not_modified", "Not modified"
        ERROR = "error", "Error"
        BLOCKED = "blocked", "Blocked"
        MISSING = "missing", "Missing"

    interview = models.ForeignKey(
        Interview, on_delete=models.CASCADE, related_name="source_snapshots"
    )
    import_run = models.ForeignKey(
        ImportRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_snapshots",
    )
    source_url = models.URLField(max_length=500)
    source_page_id = models.PositiveBigIntegerField(null=True, blank=True)
    source_revision_id = models.PositiveBigIntegerField(null=True, blank=True)
    revision_timestamp = models.DateTimeField(null=True, blank=True)
    retrieved_at = models.DateTimeField(auto_now_add=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    etag = models.CharField(max_length=255, blank=True)
    last_modified = models.CharField(max_length=255, blank=True)
    content_hash = models.CharField(max_length=128, blank=True)
    snapshot_path = models.CharField(max_length=1000, blank=True)
    source_present = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=Status.choices)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-retrieved_at"]

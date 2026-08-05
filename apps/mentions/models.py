from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.models import Album, Song
from apps.interviews.models import Interview
from apps.transcripts.models import TranscriptParagraph, TranscriptSection


class InterviewEntityLink(models.Model):
    class Scope(models.TextChoices):
        INTERVIEW = "interview", "Interview"
        PARAGRAPH = "paragraph", "Paragraph"

    class Method(models.TextChoices):
        MANUAL = "manual", "Manual"
        RULES = "rules", "Rules"
        AI = "ai", "AI"

    class ReviewStatus(models.TextChoices):
        SUGGESTED = "suggested", "Suggested"
        VERIFIED = "verified", "Verified"
        REJECTED = "rejected", "Rejected"
        NEEDS_REVIEW = "needs_review", "Needs review"

    class ExcerptType(models.TextChoices):
        QA = "qa", "Question and answer"
        PARAGRAPH = "paragraph", "Paragraph"
        NEEDS_REVIEW = "needs_review", "Needs review"

    interview = models.ForeignKey(
        Interview, on_delete=models.CASCADE, related_name="entity_links"
    )
    song = models.ForeignKey(
        Song, on_delete=models.CASCADE, null=True, blank=True, related_name="interview_links"
    )
    album = models.ForeignKey(
        Album, on_delete=models.CASCADE, null=True, blank=True, related_name="interview_links"
    )
    paragraph = models.ForeignKey(
        TranscriptParagraph,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="entity_links",
    )
    question_paragraph = models.ForeignKey(
        TranscriptParagraph,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="question_entity_links",
    )
    answer_paragraph = models.ForeignKey(
        TranscriptParagraph,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="answer_entity_links",
    )
    section = models.ForeignKey(
        TranscriptSection,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="entity_links",
    )
    scope = models.CharField(max_length=12, choices=Scope.choices, default=Scope.INTERVIEW)
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.MANUAL)
    confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    review_status = models.CharField(
        max_length=12, choices=ReviewStatus.choices, default=ReviewStatus.SUGGESTED
    )
    start_offset = models.PositiveIntegerField(null=True, blank=True)
    end_offset = models.PositiveIntegerField(null=True, blank=True)
    evidence = models.TextField(blank=True)
    excerpt_type = models.CharField(
        max_length=12,
        choices=ExcerptType.choices,
        default=ExcerptType.PARAGRAPH,
    )
    paragraph_content_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["interview__date_year", "interview__title"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(song__isnull=False) & models.Q(album__isnull=True))
                    | (models.Q(song__isnull=True) & models.Q(album__isnull=False))
                ),
                name="link_targets_exactly_one_entity",
            ),
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(scope="interview", paragraph__isnull=True, section__isnull=True)
                        | models.Q(
                            scope="paragraph",
                            paragraph__isnull=False,
                            section__isnull=False,
                        )
                    )
                ),
                name="link_scope_matches_paragraph",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(start_offset__isnull=True, end_offset__isnull=True)
                    | models.Q(
                        start_offset__isnull=False,
                        end_offset__isnull=False,
                        end_offset__gte=models.F("start_offset"),
                    )
                ),
                name="link_offsets_are_consistent",
            ),
        ]

    def clean(self) -> None:
        if bool(self.song_id) == bool(self.album_id):
            raise ValidationError("A link must target exactly one song or album.")
        if self.scope == self.Scope.PARAGRAPH and not self.paragraph_id:
            raise ValidationError("Paragraph scope requires a paragraph.")
        if self.scope == self.Scope.PARAGRAPH and not self.section_id:
            raise ValidationError("Paragraph scope requires a section.")
        if self.scope == self.Scope.INTERVIEW and (self.paragraph_id or self.section_id):
            raise ValidationError("Interview scope cannot reference a section or paragraph.")
        if self.paragraph_id and self.paragraph.transcript.interview_id != self.interview_id:
            raise ValidationError("The paragraph must belong to the linked interview.")
        if self.section_id and self.section.transcript.interview_id != self.interview_id:
            raise ValidationError("The section must belong to the linked interview.")
        if self.paragraph_id and self.section_id and self.paragraph.section_id != self.section_id:
            raise ValidationError("The paragraph must belong to the linked section.")
        for related_paragraph in (self.question_paragraph, self.answer_paragraph):
            if (
                related_paragraph
                and related_paragraph.transcript.interview_id != self.interview_id
            ):
                raise ValidationError("Question and answer paragraphs must belong to the interview.")
        if self.excerpt_type == self.ExcerptType.QA and not (
            self.question_paragraph_id and self.answer_paragraph_id
        ):
            raise ValidationError("A Q/A excerpt requires both a question and an answer paragraph.")
        if self.excerpt_type != self.ExcerptType.QA and (
            self.question_paragraph_id or self.answer_paragraph_id
        ):
            raise ValidationError("Only Q/A excerpts can reference question and answer paragraphs.")
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValidationError("Start and end offsets must be provided together.")
        if self.start_offset is not None:
            if self.end_offset < self.start_offset:
                raise ValidationError("End offset must not precede start offset.")
            if self.end_offset == self.start_offset:
                raise ValidationError("Offsets must define a non-empty range.")
            if not self.paragraph_id:
                raise ValidationError("Offsets require a paragraph citation.")
            if self.end_offset > len(self.paragraph.text):
                raise ValidationError("Offsets must point inside the selected paragraph.")

    def __str__(self) -> str:
        target = self.song or self.album
        return f"{self.interview} → {target}"

from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from apps.mentions.scanner import hash_text

from .models import InterviewEntityLink


@admin.action(description="Verify selected mentions")
def verify_mentions(modeladmin, request, queryset):
    verified = 0
    invalid = 0
    for link in queryset.select_related("interview", "song", "album", "paragraph", "section"):
        try:
            link.full_clean()
        except ValidationError:
            invalid += 1
            continue
        link.review_status = InterviewEntityLink.ReviewStatus.VERIFIED
        link.save(update_fields=["review_status", "updated_at"])
        verified += 1

    if verified:
        modeladmin.message_user(
            request,
            f"{verified} mention(s) verified.",
            messages.SUCCESS,
        )
    if invalid:
        modeladmin.message_user(
            request,
            f"{invalid} invalid mention(s) were left unchanged and require correction.",
            messages.ERROR,
        )


@admin.action(description="Reject selected mentions")
def reject_mentions(modeladmin, request, queryset):
    changed = queryset.update(review_status=InterviewEntityLink.ReviewStatus.REJECTED)
    modeladmin.message_user(request, f"{changed} mention(s) rejected.", messages.SUCCESS)


@admin.action(description="Send selected mentions to review")
def review_mentions(modeladmin, request, queryset):
    changed = queryset.update(review_status=InterviewEntityLink.ReviewStatus.NEEDS_REVIEW)
    modeladmin.message_user(
        request,
        f"{changed} mention(s) sent to editorial review.",
        messages.SUCCESS,
    )


@admin.action(description="Re-suggest selected mentions")
def suggest_mentions(modeladmin, request, queryset):
    changed = queryset.update(review_status=InterviewEntityLink.ReviewStatus.SUGGESTED)
    modeladmin.message_user(request, f"{changed} mention(s) marked as suggested.", messages.SUCCESS)


@admin.action(description="Flag mentions whose paragraph changed")
def flag_changed_paragraph_mentions(modeladmin, request, queryset):
    changed = 0
    for link in queryset.select_related("paragraph"):
        if (
            link.paragraph_id
            and link.paragraph_content_hash
            and hash_text(link.paragraph.text) != link.paragraph_content_hash
        ):
            if link.review_status != InterviewEntityLink.ReviewStatus.NEEDS_REVIEW:
                link.review_status = InterviewEntityLink.ReviewStatus.NEEDS_REVIEW
                link.save(update_fields=["review_status", "updated_at"])
                changed += 1
    modeladmin.message_user(
        request,
        f"{changed} mention(s) flagged because their paragraph changed.",
        messages.SUCCESS,
    )


@admin.register(InterviewEntityLink)
class InterviewEntityLinkAdmin(admin.ModelAdmin):
    list_display = (
        "interview",
        "target_display",
        "scope",
        "section",
        "paragraph",
        "method",
        "excerpt_type",
        "review_status",
        "confidence",
        "evidence_preview",
    )
    list_filter = ("scope", "method", "review_status", "interview__source_present")
    search_fields = (
        "interview__title",
        "song__title",
        "album__title",
        "section__heading",
        "paragraph__text",
        "evidence",
    )
    raw_id_fields = (
        "interview",
        "song",
        "album",
        "section",
        "paragraph",
        "question_paragraph",
        "answer_paragraph",
    )
    list_select_related = ("interview", "song", "album", "section", "paragraph")
    actions = [
        verify_mentions,
        reject_mentions,
        review_mentions,
        suggest_mentions,
        flag_changed_paragraph_mentions,
    ]

    @admin.display(description="Song or album", ordering="song__title")
    def target_display(self, obj):
        return obj.song or obj.album

    @admin.display(description="Evidence")
    def evidence_preview(self, obj):
        if len(obj.evidence) <= 80:
            return obj.evidence
        return f"{obj.evidence[:77]}…"

    def save_model(self, request, obj, form, change):
        obj.full_clean()
        super().save_model(request, obj, form, change)

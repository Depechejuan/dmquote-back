from django.contrib import admin, messages

from apps.interviews.models import Interview

from .models import Transcript, TranscriptParagraph, TranscriptSection


class TranscriptSectionInline(admin.TabularInline):
    model = TranscriptSection
    extra = 0
    ordering = ("order",)
    fields = ("order", "heading", "level", "section_type", "source_anchor", "publication_status")


class TranscriptParagraphInline(admin.TabularInline):
    model = TranscriptParagraph
    extra = 0
    ordering = ("order",)
    fields = (
        "order",
        "speaker",
        "text",
        "start_seconds",
        "end_seconds",
        "publication_status",
    )


@admin.action(description="Authorize selected transcript text")
def authorize_transcripts(modeladmin, request, queryset):
    count = _set_transcript_status(
        queryset,
        Interview.PublicationStatus.AUTHORIZED_TEXT,
    )
    modeladmin.message_user(
        request,
        f"{count} transcript(s) authorized, including sections and paragraphs.",
        messages.SUCCESS,
    )


@admin.action(description="Make selected transcript text private")
def privatize_transcripts(modeladmin, request, queryset):
    count = _set_transcript_status(
        queryset,
        Interview.PublicationStatus.PRIVATE_ONLY,
    )
    modeladmin.message_user(
        request,
        f"{count} transcript(s) made private, including sections and paragraphs.",
        messages.SUCCESS,
    )


def _set_transcript_status(queryset, status: str) -> int:
    count = 0
    for transcript in queryset:
        transcript.publication_status = status
        transcript.save(update_fields=["publication_status", "updated_at"])
        transcript.sections.update(publication_status=status)
        transcript.paragraphs.update(publication_status=status)
        count += 1
    return count


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ("interview", "language", "status", "publication_status")
    list_filter = ("status", "publication_status", "language")
    search_fields = ("interview__title", "interview__outlet")
    raw_id_fields = ("interview",)
    inlines = [TranscriptSectionInline]
    actions = [authorize_transcripts, privatize_transcripts]

    def save_model(self, request, obj, form, change):
        previous_status = (
            Transcript.objects.filter(pk=obj.pk)
            .values_list("publication_status", flat=True)
            .first()
            if change
            else None
        )
        super().save_model(request, obj, form, change)
        if previous_status is not None and previous_status != obj.publication_status:
            if obj.publication_status not in {
                Interview.PublicationStatus.AUTHORIZED_TEXT,
                Interview.PublicationStatus.PRIVATE_ONLY,
            }:
                return
            obj.sections.update(publication_status=obj.publication_status)
            obj.paragraphs.update(publication_status=obj.publication_status)


@admin.register(TranscriptSection)
class TranscriptSectionAdmin(admin.ModelAdmin):
    list_display = (
        "transcript",
        "order",
        "heading",
        "section_type",
        "publication_status",
    )
    list_filter = ("section_type", "publication_status")
    search_fields = ("heading", "source_anchor", "transcript__interview__title")
    raw_id_fields = ("transcript",)
    ordering = ("transcript", "order")
    inlines = [TranscriptParagraphInline]

    def save_model(self, request, obj, form, change):
        previous_status = (
            TranscriptSection.objects.filter(pk=obj.pk)
            .values_list("publication_status", flat=True)
            .first()
            if change
            else None
        )
        super().save_model(request, obj, form, change)
        if (
            previous_status is not None
            and previous_status != obj.publication_status
            and obj.publication_status
            in {
            Interview.PublicationStatus.AUTHORIZED_TEXT,
            Interview.PublicationStatus.PRIVATE_ONLY,
            }
        ):
            obj.paragraphs.update(publication_status=obj.publication_status)


@admin.action(description="Authorize selected paragraphs")
def authorize_paragraphs(modeladmin, request, queryset):
    changed = queryset.update(
        publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT
    )
    modeladmin.message_user(
        request,
        f"{changed} paragraph(s) authorized.",
        messages.SUCCESS,
    )


@admin.action(description="Make selected paragraphs private")
def privatize_paragraphs(modeladmin, request, queryset):
    changed = queryset.update(publication_status=Interview.PublicationStatus.PRIVATE_ONLY)
    modeladmin.message_user(
        request,
        f"{changed} paragraph(s) made private.",
        messages.SUCCESS,
    )


@admin.register(TranscriptParagraph)
class TranscriptParagraphAdmin(admin.ModelAdmin):
    list_display = (
        "transcript",
        "section",
        "order",
        "speaker",
        "publication_status",
    )
    list_filter = ("publication_status", "section__section_type")
    search_fields = (
        "text",
        "speaker",
        "section__heading",
        "transcript__interview__title",
    )
    raw_id_fields = ("transcript", "section")
    ordering = ("transcript", "section__order", "order")
    actions = [authorize_paragraphs, privatize_paragraphs]

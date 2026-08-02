from django.contrib import admin, messages

from .editorial import set_interview_publication_status
from .models import ImportRun, Interview, InterviewParticipant, SourceSnapshot


class InterviewParticipantInline(admin.TabularInline):
    model = InterviewParticipant
    extra = 0
    ordering = ("sort_order", "person__name")
    autocomplete_fields = ("person",)


class SourceSnapshotInline(admin.TabularInline):
    model = SourceSnapshot
    extra = 0
    can_delete = False
    max_num = 0
    fields = (
        "source_url",
        "source_page_id",
        "source_revision_id",
        "revision_timestamp",
        "retrieved_at",
        "status",
        "content_hash",
        "snapshot_path",
        "source_present",
        "import_run",
    )
    readonly_fields = fields


@admin.action(description="Authorize text for selected interviews")
def authorize_interviews(modeladmin, request, queryset):
    _set_interview_status(
        modeladmin,
        request,
        queryset,
        Interview.PublicationStatus.AUTHORIZED_TEXT,
        "authorized",
    )


@admin.action(description="Make selected interviews private")
def privatize_interviews(modeladmin, request, queryset):
    _set_interview_status(
        modeladmin,
        request,
        queryset,
        Interview.PublicationStatus.PRIVATE_ONLY,
        "made private",
    )


@admin.action(description="Send selected interviews to editorial review")
def mark_interviews_for_review(modeladmin, request, queryset):
    changed = queryset.update(
        classification_status=Interview.ClassificationStatus.NEEDS_REVIEW,
        transcript_status=Interview.TranscriptStatus.NEEDS_REVIEW,
    )
    modeladmin.message_user(
        request,
        f"{changed} interview(s) sent to editorial review.",
        messages.SUCCESS,
    )


def _set_interview_status(modeladmin, request, queryset, status: str, verb: str):
    count = 0
    for interview in queryset:
        set_interview_publication_status(interview, status)
        count += 1
    modeladmin.message_user(
        request,
        f"{count} interview(s) {verb}, including transcript sections and paragraphs.",
        messages.SUCCESS,
    )


@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "date_display",
        "outlet",
        "medium",
        "classification_status",
        "source_present",
        "transcript_status",
        "publication_status",
    )
    list_filter = (
        "classification_status",
        "medium",
        "source_present",
        "transcript_status",
        "publication_status",
        "date_precision",
    )
    search_fields = (
        "title",
        "outlet",
        "location",
        "source_url",
        "source_page_id",
        "source_revision_id",
    )
    readonly_fields = (
        "source_name",
        "source_domain",
        "source_page_id",
        "source_revision_id",
        "source_revision_timestamp",
        "source_content_hash",
        "source_present",
        "source_updated_at",
        "created_at",
        "updated_at",
    )
    prepopulated_fields = {"slug": ("title",)}
    inlines = [InterviewParticipantInline, SourceSnapshotInline]
    actions = [authorize_interviews, privatize_interviews, mark_interviews_for_review]

    def save_model(self, request, obj, form, change):
        previous_status = (
            Interview.objects.filter(pk=obj.pk)
            .values_list("publication_status", flat=True)
            .first()
            if change
            else None
        )
        super().save_model(request, obj, form, change)
        if previous_status is not None and previous_status != obj.publication_status:
            set_interview_publication_status(obj, obj.publication_status)


@admin.register(ImportRun)
class ImportRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "source_name",
        "input_format",
        "input_name",
        "status",
        "pages_seen",
        "pages_created",
        "pages_updated",
        "pages_failed",
    )
    list_filter = ("status", "input_format", "source_name")
    search_fields = ("input_name", "input_sha256", "error_message")
    readonly_fields = [field.name for field in ImportRun._meta.fields]
    date_hierarchy = "started_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SourceSnapshot)
class SourceSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "interview",
        "retrieved_at",
        "status",
        "source_present",
        "source_revision_id",
        "http_status",
    )
    list_filter = ("status", "source_present")
    search_fields = (
        "interview__title",
        "source_url",
        "source_page_id",
        "source_revision_id",
        "content_hash",
    )
    readonly_fields = [field.name for field in SourceSnapshot._meta.fields]
    date_hierarchy = "retrieved_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False

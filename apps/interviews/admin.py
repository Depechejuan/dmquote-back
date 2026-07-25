from django.contrib import admin

from .models import Interview, InterviewParticipant, SourceSnapshot


class InterviewParticipantInline(admin.TabularInline):
    model = InterviewParticipant
    extra = 0


@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "date_display",
        "outlet",
        "transcript_status",
        "publication_status",
    )
    list_filter = ("transcript_status", "publication_status", "date_precision")
    search_fields = ("title", "outlet", "location", "source_url")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [InterviewParticipantInline]


@admin.register(SourceSnapshot)
class SourceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("interview", "retrieved_at", "status", "http_status")
    list_filter = ("status",)
    search_fields = ("interview__title", "source_url", "content_hash")

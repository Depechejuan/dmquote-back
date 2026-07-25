from django.contrib import admin

from .models import Transcript, TranscriptParagraph


class TranscriptParagraphInline(admin.TabularInline):
    model = TranscriptParagraph
    extra = 0
    ordering = ("order",)


@admin.register(Transcript)
class TranscriptAdmin(admin.ModelAdmin):
    list_display = ("interview", "language", "status", "publication_status")
    list_filter = ("status", "publication_status", "language")
    search_fields = ("interview__title",)
    inlines = [TranscriptParagraphInline]


@admin.register(TranscriptParagraph)
class TranscriptParagraphAdmin(admin.ModelAdmin):
    list_display = ("transcript", "order", "speaker", "publication_status")
    list_filter = ("publication_status",)
    search_fields = ("text", "speaker", "transcript__interview__title")

from django.contrib import admin

from .models import InterviewEntityLink


@admin.register(InterviewEntityLink)
class InterviewEntityLinkAdmin(admin.ModelAdmin):
    list_display = (
        "interview",
        "song",
        "album",
        "scope",
        "method",
        "review_status",
        "confidence",
    )
    list_filter = ("scope", "method", "review_status")
    search_fields = ("interview__title", "song__title", "album__title", "evidence")

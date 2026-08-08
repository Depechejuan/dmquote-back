from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.catalog.views import AlbumViewSet, SongViewSet, music_catalog
from apps.editorial.views import (
    editorial_catalog,
    editorial_csrf,
    editorial_interview_detail,
    editorial_interview_review_detail,
    editorial_interview_reviews,
    editorial_interview_visibility,
    editorial_mention_collection,
    editorial_mention_detail,
    editorial_paragraph_visibility,
    editorial_queue,
    editorial_section_visibility,
    editorial_transcript_language,
    editorial_translation_requests,
)
from apps.interviews.views import InterviewViewSet

router = DefaultRouter()
router.register("interviews", InterviewViewSet, basename="interview")
router.register("songs", SongViewSet, basename="song")
router.register("albums", AlbumViewSet, basename="album")

urlpatterns = [
    path("editorial/csrf/", editorial_csrf, name="editorial-csrf"),
    path("editorial/queue/", editorial_queue, name="editorial-queue"),
    path(
        "editorial/interview-reviews/",
        editorial_interview_reviews,
        name="editorial-interview-reviews",
    ),
    path("editorial/catalog/", editorial_catalog, name="editorial-catalog"),
    path(
        "editorial/translation-requests/",
        editorial_translation_requests,
        name="editorial-translation-requests",
    ),
    path(
        "editorial/interviews/<slug:slug>/",
        editorial_interview_detail,
        name="editorial-interview-detail",
    ),
    path(
        "editorial/interviews/<slug:slug>/visibility/",
        editorial_interview_visibility,
        name="editorial-interview-visibility",
    ),
    path(
        "editorial/interviews/<slug:slug>/mention-review/",
        editorial_interview_review_detail,
        name="editorial-interview-review-detail",
    ),
    path(
        "editorial/interviews/<slug:slug>/transcript-language/",
        editorial_transcript_language,
        name="editorial-transcript-language",
    ),
    path("editorial/mentions/", editorial_mention_collection, name="editorial-mention-collection"),
    path("editorial/mentions/<int:pk>/", editorial_mention_detail, name="editorial-mention-detail"),
    path(
        "editorial/sections/<int:pk>/visibility/",
        editorial_section_visibility,
        name="editorial-section-visibility",
    ),
    path(
        "editorial/paragraphs/<int:pk>/visibility/",
        editorial_paragraph_visibility,
        name="editorial-paragraph-visibility",
    ),
    path("music/", music_catalog, name="music-catalog"),
    path(
        "transcription-needed/",
        InterviewViewSet.as_view({"get": "transcription_needed"}),
        name="transcription-needed",
    ),
    *router.urls,
]

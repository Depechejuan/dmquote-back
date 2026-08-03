from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.catalog.views import AlbumViewSet, SongViewSet, music_catalog
from apps.interviews.views import InterviewViewSet

router = DefaultRouter()
router.register("interviews", InterviewViewSet, basename="interview")
router.register("songs", SongViewSet, basename="song")
router.register("albums", AlbumViewSet, basename="album")

urlpatterns = [
    path("music/", music_catalog, name="music-catalog"),
    path(
        "transcription-needed/",
        InterviewViewSet.as_view({"get": "transcription_needed"}),
        name="transcription-needed",
    ),
    *router.urls,
]

from django.db.models import Prefetch, Q
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.mentions.public import public_mentions
from apps.mentions.serializers import InterviewEntityLinkSerializer

from .models import Album, Song
from .serializers import (
    AlbumSerializer,
    MusicCatalogSerializer,
    SongSerializer,
)


@extend_schema(responses=MusicCatalogSerializer)
@api_view(["GET"])
@permission_classes([AllowAny])
def music_catalog(request):
    """Return the public music catalogue grouped into albums and standalone songs."""

    albums = Album.objects.prefetch_related(
        Prefetch("songs", queryset=Song.objects.order_by("title", "id"))
    ).order_by("release_year", "title", "id")
    standalone_songs = Song.objects.filter(album__isnull=True).order_by("title", "id")
    payload = {
        "albums": albums,
        "standalone_songs": standalone_songs,
    }
    return Response(MusicCatalogSerializer(payload).data)


class SongViewSet(ReadOnlyModelViewSet):
    queryset = Song.objects.select_related("album").all()
    serializer_class = SongSerializer
    lookup_field = "slug"
    filterset_fields = ["release_year", "album"]
    search_fields = ["title", "aliases__value", "album__title"]
    ordering_fields = ["title", "release_year"]

    @extend_schema(
        responses={
            200: InterviewEntityLinkSerializer(many=True),
            404: OpenApiResponse(description="Song not found."),
        }
    )
    @action(detail=True, methods=["get"])
    def mentions(self, request, slug=None):
        song = self.get_object()
        links = public_mentions(
            song.interview_links.select_related(
                "interview",
                "song__album",
                "album",
                "paragraph",
                "section",
            )
            .prefetch_related("interview__participant_links__person")
            .all()
        )
        page = self.paginate_queryset(links)
        serializer = InterviewEntityLinkSerializer(
            page or links,
            many=True,
            context={"request": request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class AlbumViewSet(ReadOnlyModelViewSet):
    queryset = Album.objects.all()
    serializer_class = AlbumSerializer
    lookup_field = "slug"
    filterset_fields = ["release_year", "is_compilation"]
    search_fields = ["title", "aliases__value"]
    ordering_fields = ["title", "release_year"]

    @extend_schema(
        responses={
            200: InterviewEntityLinkSerializer(many=True),
            404: OpenApiResponse(description="Album not found."),
        }
    )
    @action(detail=True, methods=["get"])
    def mentions(self, request, slug=None):
        album = self.get_object()
        links = public_mentions(
            album_link_queryset(album)
            .select_related(
                "interview",
                "song__album",
                "album",
                "paragraph",
                "section",
            )
            .prefetch_related("interview__participant_links__person")
            .all()
        )
        page = self.paginate_queryset(links)
        serializer = InterviewEntityLinkSerializer(
            page or links,
            many=True,
            context={"request": request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


def album_link_queryset(album):
    """Include direct album mentions and mentions of songs on that album."""

    from apps.mentions.models import InterviewEntityLink

    return InterviewEntityLink.objects.filter(Q(album=album) | Q(song__album=album))

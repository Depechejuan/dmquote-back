from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.mentions.serializers import InterviewEntityLinkSerializer

from .models import Album, Song
from .serializers import AlbumSerializer, SongSerializer


class SongViewSet(ReadOnlyModelViewSet):
    queryset = Song.objects.select_related("album").all()
    serializer_class = SongSerializer
    lookup_field = "slug"
    search_fields = ["title", "aliases__value", "album__title"]
    ordering_fields = ["title", "release_year"]

    @action(detail=True, methods=["get"])
    def mentions(self, request, slug=None):
        song = self.get_object()
        links = song.interview_links.select_related("interview", "paragraph").all()
        page = self.paginate_queryset(links)
        serializer = InterviewEntityLinkSerializer(page or links, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class AlbumViewSet(ReadOnlyModelViewSet):
    queryset = Album.objects.all()
    serializer_class = AlbumSerializer
    lookup_field = "slug"
    search_fields = ["title", "aliases__value"]
    ordering_fields = ["title", "release_year"]

    @action(detail=True, methods=["get"])
    def mentions(self, request, slug=None):
        album = self.get_object()
        links = album.interview_links.select_related("interview", "paragraph").all()
        page = self.paginate_queryset(links)
        serializer = InterviewEntityLinkSerializer(page or links, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.mentions.serializers import InterviewEntityLinkSerializer
from apps.transcripts.serializers import TranscriptSerializer

from .models import Interview
from .serializers import InterviewDetailSerializer, InterviewListSerializer


class InterviewViewSet(ReadOnlyModelViewSet):
    queryset = Interview.objects.prefetch_related(
        "participant_links__person", "transcript__paragraphs"
    ).all()
    lookup_field = "slug"
    filterset_fields = ["date_year", "transcript_status", "publication_status"]
    search_fields = ["title", "outlet", "location", "participant_links__person__name"]
    ordering_fields = ["date_year", "date_month", "date_day", "title"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return InterviewDetailSerializer
        return InterviewListSerializer

    @action(detail=True, methods=["get"])
    def mentions(self, request, slug=None):
        interview = self.get_object()
        links = interview.entity_links.select_related("song", "album", "paragraph").all()
        page = self.paginate_queryset(links)
        serializer = InterviewEntityLinkSerializer(page or links, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["get"])
    def transcript(self, request, slug=None):
        interview = self.get_object()
        if interview.publication_status != Interview.PublicationStatus.AUTHORIZED_TEXT:
            return Response({"detail": "Transcript text is not publicly available."}, status=403)
        if not hasattr(interview, "transcript"):
            return Response({"detail": "Transcript not available."}, status=404)
        return Response(TranscriptSerializer(interview.transcript).data)

    @action(detail=False, methods=["get"], url_path="transcription-needed")
    def transcription_needed(self, request):
        queryset = self.filter_queryset(
            self.get_queryset().filter(
                transcript_status__in=[
                    Interview.TranscriptStatus.MISSING,
                    Interview.TranscriptStatus.PARTIAL,
                    Interview.TranscriptStatus.NEEDS_REVIEW,
                ]
            )
        )
        page = self.paginate_queryset(queryset)
        serializer = InterviewListSerializer(page or queryset, many=True, context={"request": request})
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

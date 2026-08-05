from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.mentions.public import public_mentions
from apps.mentions.serializers import InterviewEntityLinkSerializer
from apps.transcripts.serializers import TranscriptSerializer

from .models import Interview
from .public import public_interviews
from .serializers import InterviewDetailSerializer, InterviewListSerializer


class InterviewViewSet(ReadOnlyModelViewSet):
    queryset = Interview.objects.prefetch_related(
        "participant_links__person",
        "transcript__sections__paragraphs",
        "transcript__paragraphs",
    ).all()
    lookup_field = "slug"
    filterset_fields = [
        "date_year",
        "outlet",
        "medium",
        "transcript_status",
        "publication_status",
    ]
    search_fields = ["title", "outlet", "location", "participant_links__person__name"]
    ordering_fields = ["date_year", "date_month", "date_day", "title", "outlet"]

    def get_queryset(self):
        return public_interviews(self.queryset)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return InterviewDetailSerializer
        return InterviewListSerializer

    @extend_schema(
        responses={
            200: InterviewEntityLinkSerializer(many=True),
            404: OpenApiResponse(description="Interview not found."),
        }
    )
    @action(detail=True, methods=["get"])
    def mentions(self, request, slug=None):
        interview = self.get_object()
        links = public_mentions(
            interview.entity_links.select_related(
                "interview",
                "song__album",
                "album",
                "paragraph",
                "section",
                "question_paragraph",
                "answer_paragraph",
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

    @extend_schema(
        responses={
            200: TranscriptSerializer,
            403: OpenApiResponse(description="Transcript text is not authorized."),
            404: OpenApiResponse(description="Transcript not available."),
        }
    )
    @action(detail=True, methods=["get"])
    def transcript(self, request, slug=None):
        interview = self.get_object()
        if interview.publication_status != Interview.PublicationStatus.AUTHORIZED_TEXT:
            return Response({"detail": "Transcript text is not publicly available."}, status=403)
        if not hasattr(interview, "transcript"):
            return Response({"detail": "Transcript not available."}, status=404)
        if interview.transcript.publication_status != Interview.PublicationStatus.AUTHORIZED_TEXT:
            return Response({"detail": "Transcript text is not publicly available."}, status=403)
        return Response(
            TranscriptSerializer(
                interview.transcript,
                context={"request": request},
            ).data
        )

    @extend_schema(responses=InterviewListSerializer(many=True))
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
        serializer = InterviewListSerializer(
            page or queryset,
            many=True,
            context={"request": request},
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.mentions.public import public_mentions
from apps.mentions.serializers import InterviewEntityLinkSerializer
from apps.transcripts.models import TranscriptTranslation, TranscriptTranslationRequest
from apps.transcripts.serializers import (
    TranscriptSerializer,
    TranscriptTranslationRequestSerializer,
    TranscriptTranslationSerializer,
)
from apps.transcripts.throttles import TranslationRequestThrottle
from apps.transcripts.translations import (
    transcript_is_public,
    translation_targets,
)

from .models import Interview
from .public import public_interviews
from .serializers import InterviewDetailSerializer, InterviewListSerializer


class InterviewViewSet(ReadOnlyModelViewSet):
    queryset = Interview.objects.prefetch_related(
        "participant_links__person",
        "transcript__sections__paragraphs",
        "transcript__paragraphs",
        "transcript__translations__sections__paragraphs",
        "transcript__translations__paragraphs",
        "transcript__translation_requests",
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
            200: PolymorphicProxySerializer(
                component_name="PublicTranscript",
                serializers=[TranscriptSerializer, TranscriptTranslationSerializer],
                resource_type_field_name=None,
            ),
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
        language = request.query_params.get("language", "").strip().lower().replace("_", "-")
        if not language or language == interview.transcript.language:
            return Response(
                TranscriptSerializer(
                    interview.transcript,
                    context={"request": request},
                ).data
            )
        translation = (
            interview.transcript.translations.filter(
                target_language=language,
                status=TranscriptTranslation.Status.AVAILABLE,
            )
            .prefetch_related("sections__paragraphs", "paragraphs")
            .first()
        )
        if translation is None:
            return Response(
                {"detail": "The requested translation is not available."},
                status=HTTP_404_NOT_FOUND,
            )
        return Response(TranscriptTranslationSerializer(translation, context={"request": request}).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="language",
                type=str,
                location=OpenApiParameter.PATH,
                description="Requested ISO/BCP-47 target language.",
            )
        ],
        responses={
            200: TranscriptTranslationRequestSerializer,
            201: TranscriptTranslationRequestSerializer,
            400: OpenApiResponse(description="Unsupported target language."),
            404: OpenApiResponse(description="Transcript not available."),
        }
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=r"translations/(?P<language>[^/.]+)/request",
        authentication_classes=[],
        permission_classes=[AllowAny],
        throttle_classes=[TranslationRequestThrottle],
    )
    def request_translation(self, request, slug=None, language=None):
        interview = self.get_object()
        transcript = getattr(interview, "transcript", None)
        if transcript is None or not transcript_is_public(transcript):
            return Response(
                {"detail": "Transcript not available."},
                status=HTTP_404_NOT_FOUND,
            )
        target_language = (language or "").strip().lower().replace("_", "-")
        if target_language not in translation_targets(transcript.language):
            return Response(
                {"detail": "This target language is not available for the transcript."},
                status=HTTP_400_BAD_REQUEST,
            )
        if transcript.translations.filter(
            target_language=target_language,
            status=TranscriptTranslation.Status.AVAILABLE,
        ).exists():
            translation_request, _ = TranscriptTranslationRequest.objects.get_or_create(
                transcript=transcript,
                target_language=target_language,
                defaults={"status": TranscriptTranslationRequest.Status.COMPLETED},
            )
            if translation_request.status != TranscriptTranslationRequest.Status.COMPLETED:
                translation_request.status = TranscriptTranslationRequest.Status.COMPLETED
                translation_request.save(update_fields=["status", "updated_at"])
            return Response(
                TranscriptTranslationRequestSerializer(translation_request).data,
            )

        translation_request, created = TranscriptTranslationRequest.objects.get_or_create(
            transcript=transcript,
            target_language=target_language,
            defaults={"status": TranscriptTranslationRequest.Status.QUEUED},
        )
        if translation_request.status in {
            TranscriptTranslationRequest.Status.FAILED,
            TranscriptTranslationRequest.Status.COMPLETED,
        }:
            translation_request.status = TranscriptTranslationRequest.Status.QUEUED
            translation_request.error_message = ""
            translation_request.completed_at = None
            translation_request.save(
                update_fields=["status", "error_message", "completed_at", "updated_at"]
            )
        return Response(
            TranscriptTranslationRequestSerializer(translation_request).data,
            status=HTTP_201_CREATED if created else 200,
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

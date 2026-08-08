from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.catalog.models import Album, Song
from apps.interviews.editorial import set_interview_publication_status
from apps.interviews.models import Interview, InterviewMentionReview
from apps.mentions.models import InterviewEntityLink
from apps.transcripts.models import Transcript, TranscriptSection, TranscriptTranslationRequest
from apps.transcripts.translations import invalidate_transcript_translations

from .serializers import (
    CSRFSerializer,
    EditorialCatalogSerializer,
    EditorialInterviewQueueSerializer,
    EditorialInterviewSerializer,
    EditorialMentionCreateSerializer,
    EditorialMentionSerializer,
    EditorialMentionUpdateSerializer,
    EditorialReviewStateSerializer,
    EditorialReviewUpdateSerializer,
    EditorialTranscriptLanguageSerializer,
    EditorialTranscriptSerializer,
    EditorialTranslationRequestSerializer,
    PublicationVisibilitySerializer,
)

EDITORIAL_AUTHENTICATION = [SessionAuthentication]
EDITORIAL_PERMISSIONS = [IsAdminUser]


def editorial_queryset():
    return (
        InterviewEntityLink.objects.select_related(
            "interview",
            "song__album",
            "album",
            "section",
            "paragraph",
            "question_paragraph",
            "answer_paragraph",
        )
        .prefetch_related("interview__participant_links__person")
        .order_by("-interview__date_year", "interview__title", "id")
    )


def editorial_interview_review_queryset():
    return (
        Interview.objects.filter(source_present=True)
        .exclude(classification_status=Interview.ClassificationStatus.NOT_INTERVIEW)
        .select_related("mention_review")
        .prefetch_related("participant_links__person")
        .annotate(
            candidate_count=Count(
                "entity_links",
                filter=Q(
                    entity_links__review_status__in=[
                        InterviewEntityLink.ReviewStatus.SUGGESTED,
                        InterviewEntityLink.ReviewStatus.NEEDS_REVIEW,
                    ]
                ),
                distinct=True,
            ),
            verified_count=Count(
                "entity_links",
                filter=Q(entity_links__review_status=InterviewEntityLink.ReviewStatus.VERIFIED),
                distinct=True,
            ),
        )
        .order_by("-date_year", "-date_month", "-date_day", "title")
    )


def editorial_review_progress():
    eligible = Interview.objects.filter(source_present=True).exclude(
        classification_status=Interview.ClassificationStatus.NOT_INTERVIEW
    )
    total = eligible.count()
    progress = {status: 0 for status, _ in InterviewMentionReview.Status.choices}
    for row in (
        InterviewMentionReview.objects.filter(interview__in=eligible)
        .values("status")
        .annotate(count=Count("id"))
    ):
        progress[row["status"]] = row["count"]
    progress[InterviewMentionReview.Status.PENDING] = total - sum(
        count
        for status, count in progress.items()
        if status != InterviewMentionReview.Status.PENDING
    )
    return {"total": total, **progress}


def apply_editorial_review_filters(queryset, request):
    date_year = request.query_params.get("date_year", "").strip()
    if date_year:
        try:
            queryset = queryset.filter(date_year=int(date_year))
        except ValueError:
            return None, Response({"detail": "date_year must be a whole number."}, status=400)

    mention_kind = request.query_params.get("mention_kind", "").strip()
    mention_id = request.query_params.get("mention_id", "").strip()
    if bool(mention_kind) != bool(mention_id):
        return None, Response(
            {"detail": "mention_kind and mention_id must be provided together."}, status=400
        )
    if not mention_kind:
        return queryset, None
    try:
        mention_id_value = int(mention_id)
    except ValueError:
        return None, Response({"detail": "mention_id must be a whole number."}, status=400)

    visible_statuses = [
        InterviewEntityLink.ReviewStatus.SUGGESTED,
        InterviewEntityLink.ReviewStatus.NEEDS_REVIEW,
        InterviewEntityLink.ReviewStatus.VERIFIED,
    ]
    if mention_kind == "song":
        return queryset.filter(
            entity_links__song_id=mention_id_value,
            entity_links__review_status__in=visible_statuses,
        ), None
    if mention_kind == "album":
        return queryset.filter(
            entity_links__album_id=mention_id_value,
            entity_links__review_status__in=visible_statuses,
        ), None
    if mention_kind == "songs_from_album":
        return queryset.filter(
            entity_links__song__album_id=mention_id_value,
            entity_links__review_status__in=visible_statuses,
        ), None
    return None, Response({"detail": "Invalid mention_kind."}, status=400)


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="review_status",
            type=str,
            required=False,
            description="Comma-separated statuses. Defaults to suggested and needs_review.",
        ),
        OpenApiParameter(name="search", type=str, required=False),
        OpenApiParameter(name="interview_slug", type=str, required=False),
    ],
    responses={200: EditorialMentionSerializer(many=True), 403: OpenApiResponse(description="Staff access required.")},
)
@api_view(["GET"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_queue(request):
    statuses = request.query_params.get("review_status", "suggested,needs_review")
    valid_statuses = {choice for choice, _ in InterviewEntityLink.ReviewStatus.choices}
    selected_statuses = [status.strip() for status in statuses.split(",") if status.strip()]
    if statuses != "all" and not set(selected_statuses).issubset(valid_statuses):
        return Response({"detail": "Invalid review status."}, status=400)
    queryset = editorial_queryset()
    if statuses != "all":
        queryset = queryset.filter(review_status__in=selected_statuses)
    search = request.query_params.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(interview__title__icontains=search)
            | Q(song__title__icontains=search)
            | Q(album__title__icontains=search)
            | Q(evidence__icontains=search)
        )
    interview_slug = request.query_params.get("interview_slug", "").strip()
    if interview_slug:
        queryset = queryset.filter(interview__slug=interview_slug)
    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(queryset, request)
    serializer = EditorialMentionSerializer(page, many=True, context={"request": request})
    return paginator.get_paginated_response(serializer.data)


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="status",
            type=str,
            required=False,
            description="One review status. Defaults to pending; use all for every interview.",
        ),
        OpenApiParameter(name="search", type=str, required=False),
        OpenApiParameter(name="date_year", type=int, required=False),
        OpenApiParameter(
            name="mention_kind",
            type=str,
            required=False,
            description="song, album, or songs_from_album.",
        ),
        OpenApiParameter(name="mention_id", type=int, required=False),
    ],
    responses={
        200: EditorialInterviewQueueSerializer(many=True),
        403: OpenApiResponse(description="Staff access required."),
    },
)
@api_view(["GET"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_interview_reviews(request):
    status = request.query_params.get("status", InterviewMentionReview.Status.PENDING)
    valid_statuses = {choice for choice, _ in InterviewMentionReview.Status.choices}
    if status != "all" and status not in valid_statuses:
        return Response({"detail": "Invalid review status."}, status=400)

    queryset = editorial_interview_review_queryset()
    if status == InterviewMentionReview.Status.PENDING:
        queryset = queryset.filter(
            Q(mention_review__isnull=True)
            | Q(mention_review__status=InterviewMentionReview.Status.PENDING)
        )
    elif status != "all":
        queryset = queryset.filter(mention_review__status=status)

    queryset, filter_error = apply_editorial_review_filters(queryset, request)
    if filter_error:
        return filter_error

    search = request.query_params.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(title__icontains=search)
            | Q(outlet__icontains=search)
            | Q(location__icontains=search)
            | Q(participant_links__person__name__icontains=search)
        ).distinct()

    paginator = PageNumberPagination()
    paginator.page_size = 20
    paginator.max_page_size = 100
    page = paginator.paginate_queryset(queryset, request)
    serializer = EditorialInterviewQueueSerializer(page, many=True, context={"request": request})
    response = paginator.get_paginated_response(serializer.data)
    response.data["progress"] = editorial_review_progress()
    return response


@extend_schema(responses=CSRFSerializer)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([])
def editorial_csrf(request):
    from django.middleware.csrf import get_token

    return Response({"csrf_token": get_token(request)})


@extend_schema(
    responses={200: EditorialCatalogSerializer, 403: OpenApiResponse(description="Staff access required.")}
)
@api_view(["GET"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_catalog(request):
    albums = Album.objects.prefetch_related(
        Prefetch("songs", queryset=Song.objects.order_by("title", "id"))
    ).order_by("release_year", "title", "id")
    standalone_songs = Song.objects.filter(album__isnull=True).order_by("title", "id")
    return Response(
        EditorialCatalogSerializer(
            {"albums": albums, "standalone_songs": standalone_songs},
            context={"request": request},
        ).data
    )


@extend_schema(
    responses={200: EditorialInterviewSerializer, 404: OpenApiResponse(description="Interview not found.")}
)
@api_view(["GET"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_interview_detail(request, slug):
    section_queryset = TranscriptSection.objects.prefetch_related("paragraphs").order_by("order")
    interview = get_object_or_404(
        Interview.objects.select_related("mention_review").prefetch_related(
            "participant_links__person",
            Prefetch("transcript__sections", queryset=section_queryset),
            "transcript__translation_requests",
        ),
        slug=slug,
    )
    return Response(EditorialInterviewSerializer(interview, context={"request": request}).data)


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="status",
            type=str,
            required=False,
            description="queued, processing, completed, failed, or all. Defaults to queued.",
        ),
    ],
    responses={200: EditorialTranslationRequestSerializer(many=True)},
)
@api_view(["GET"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_translation_requests(request):
    status = request.query_params.get("status", TranscriptTranslationRequest.Status.QUEUED)
    valid_statuses = {choice for choice, _ in TranscriptTranslationRequest.Status.choices}
    if status != "all" and status not in valid_statuses:
        return Response({"detail": "Invalid translation request status."}, status=400)
    queryset = TranscriptTranslationRequest.objects.select_related(
        "transcript__interview"
    ).order_by("requested_at", "id")
    if status != "all":
        queryset = queryset.filter(status=status)
    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(
        EditorialTranslationRequestSerializer(page, many=True, context={"request": request}).data
    )


@extend_schema(
    request=EditorialTranscriptLanguageSerializer,
    responses={200: EditorialTranscriptSerializer, 404: OpenApiResponse(description="Transcript not found.")},
)
@api_view(["PATCH"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_transcript_language(request, slug):
    interview = get_object_or_404(Interview, slug=slug)
    transcript = get_object_or_404(Transcript, interview=interview)
    serializer = EditorialTranscriptLanguageSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    if transcript.language != serializer.validated_data["language"]:
        transcript.language = serializer.validated_data["language"]
        transcript.save(update_fields=["language", "updated_at"])
        invalidate_transcript_translations(transcript)
    return Response(EditorialTranscriptSerializer(transcript, context={"request": request}).data)


@extend_schema(
    request=EditorialMentionCreateSerializer,
    responses={201: EditorialMentionSerializer, 400: OpenApiResponse(description="Invalid editorial mention.")},
)
@api_view(["POST"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_mention_collection(request):
    serializer = EditorialMentionCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    mention = serializer.save()
    mention = editorial_queryset().get(pk=mention.pk)
    return Response(
        EditorialMentionSerializer(mention, context={"request": request}).data,
        status=201,
    )


@extend_schema(
    request=EditorialMentionUpdateSerializer,
    responses={200: EditorialMentionSerializer, 400: OpenApiResponse(description="Invalid editorial update.")},
)
@api_view(["GET", "PATCH"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_mention_detail(request, pk):
    mention = get_object_or_404(editorial_queryset(), pk=pk)
    if request.method == "GET":
        return Response(EditorialMentionSerializer(mention, context={"request": request}).data)
    serializer = EditorialMentionUpdateSerializer(mention, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    mention = serializer.save()
    mention = editorial_queryset().get(pk=mention.pk)
    return Response(EditorialMentionSerializer(mention, context={"request": request}).data)


@extend_schema(
    request=EditorialReviewUpdateSerializer,
    responses={200: EditorialReviewStateSerializer, 400: OpenApiResponse(description="Invalid review transition.")},
)
@api_view(["PATCH"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_interview_review_detail(request, slug):
    interview = get_object_or_404(Interview, slug=slug)
    serializer = EditorialReviewUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    status = serializer.validated_data["status"]
    has_verified_links = interview.entity_links.filter(
        review_status=InterviewEntityLink.ReviewStatus.VERIFIED
    ).exists()
    if status == InterviewMentionReview.Status.REVIEWED_WITH_LINKS and not has_verified_links:
        return Response(
            {"detail": "A verified song or album link is required before closing with links."},
            status=400,
        )
    if status == InterviewMentionReview.Status.REVIEWED_WITHOUT_SONG and has_verified_links:
        return Response(
            {"detail": "An interview with verified links cannot be closed without a song."},
            status=400,
        )

    review, _ = InterviewMentionReview.objects.get_or_create(interview=interview)
    review.status = status
    if status in {
        InterviewMentionReview.Status.REVIEWED_WITH_LINKS,
        InterviewMentionReview.Status.REVIEWED_WITHOUT_SONG,
    }:
        review.reviewer = request.user
        review.reviewed_at = timezone.now()
    review.save()
    return Response(EditorialReviewStateSerializer(review, context={"request": request}).data)


def _visibility_response(serializer, instance):
    serializer.is_valid(raise_exception=True)
    status = serializer.validated_data["publication_status"]
    if isinstance(instance, Interview):
        set_interview_publication_status(instance, status)
    elif isinstance(instance, TranscriptSection):
        instance.publication_status = status
        instance.save(update_fields=["publication_status"])
        instance.paragraphs.update(publication_status=status)
    else:
        instance.publication_status = status
        instance.save(update_fields=["publication_status"])
    return Response({"id": instance.pk, "publication_status": status})


@extend_schema(request=PublicationVisibilitySerializer, responses={200: PublicationVisibilitySerializer})
@api_view(["PATCH"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_interview_visibility(request, slug):
    interview = get_object_or_404(Interview, slug=slug)
    return _visibility_response(PublicationVisibilitySerializer(data=request.data), interview)


@extend_schema(request=PublicationVisibilitySerializer, responses={200: PublicationVisibilitySerializer})
@api_view(["PATCH"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_section_visibility(request, pk):
    section = get_object_or_404(TranscriptSection, pk=pk)
    return _visibility_response(PublicationVisibilitySerializer(data=request.data), section)


@extend_schema(request=PublicationVisibilitySerializer, responses={200: PublicationVisibilitySerializer})
@api_view(["PATCH"])
@authentication_classes(EDITORIAL_AUTHENTICATION)
@permission_classes(EDITORIAL_PERMISSIONS)
def editorial_paragraph_visibility(request, pk):
    from apps.transcripts.models import TranscriptParagraph

    paragraph = get_object_or_404(TranscriptParagraph, pk=pk)
    return _visibility_response(PublicationVisibilitySerializer(data=request.data), paragraph)

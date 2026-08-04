from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.catalog.models import Album, Song
from apps.interviews.editorial import set_interview_publication_status
from apps.interviews.models import Interview
from apps.mentions.models import InterviewEntityLink
from apps.transcripts.models import TranscriptSection

from .serializers import (
    CSRFSerializer,
    EditorialCatalogSerializer,
    EditorialInterviewSerializer,
    EditorialMentionSerializer,
    EditorialMentionUpdateSerializer,
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


@extend_schema(
    parameters=[
        OpenApiParameter(
            name="review_status",
            type=str,
            required=False,
            description="Comma-separated statuses. Defaults to suggested and needs_review.",
        ),
        OpenApiParameter(name="search", type=str, required=False),
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
    paginator = PageNumberPagination()
    paginator.page_size = 20
    page = paginator.paginate_queryset(queryset, request)
    serializer = EditorialMentionSerializer(page, many=True, context={"request": request})
    return paginator.get_paginated_response(serializer.data)


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
        Interview.objects.prefetch_related(
            "participant_links__person",
            Prefetch("transcript__sections", queryset=section_queryset),
        ),
        slug=slug,
    )
    return Response(EditorialInterviewSerializer(interview, context={"request": request}).data)


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

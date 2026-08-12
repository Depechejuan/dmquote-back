from django.db.models import Q, QuerySet

from apps.interviews.models import Interview

from .models import InterviewEntityLink


def public_mentions(
    queryset: QuerySet[InterviewEntityLink] | None = None,
) -> QuerySet[InterviewEntityLink]:
    """Return only verified mentions whose referenced content is authorized."""

    base = queryset if queryset is not None else InterviewEntityLink.objects.all()
    return (
        base.filter(
            review_status__in=[
                InterviewEntityLink.ReviewStatus.VERIFIED,
                InterviewEntityLink.ReviewStatus.NEEDS_REVIEW,
            ],
            interview__source_present=True,
            interview__publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
            interview__classification_status=Interview.ClassificationStatus.INTERVIEW,
        )
        .filter(
            Q(scope=InterviewEntityLink.Scope.INTERVIEW)
            | Q(
                scope=InterviewEntityLink.Scope.PARAGRAPH,
                paragraph__publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
                paragraph__transcript__publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
                section__publication_status=Interview.PublicationStatus.AUTHORIZED_TEXT,
            )
        )
    )

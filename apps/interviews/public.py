from django.db.models import QuerySet

from .models import Interview


def public_interviews(queryset: QuerySet[Interview] | None = None) -> QuerySet[Interview]:
    """Return interviews whose metadata may be shown by the public API."""

    base = queryset if queryset is not None else Interview.objects.all()
    return base.filter(source_present=True).exclude(
        classification_status=Interview.ClassificationStatus.NOT_INTERVIEW
    ).exclude(
        publication_status=Interview.PublicationStatus.PRIVATE_ONLY
    )

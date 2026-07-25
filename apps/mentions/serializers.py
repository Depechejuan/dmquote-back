from rest_framework import serializers

from apps.catalog.serializers import AlbumSummarySerializer, SongSummarySerializer
from apps.interviews.serializers import InterviewListSerializer

from .models import InterviewEntityLink


class InterviewEntityLinkSerializer(serializers.ModelSerializer):
    interview = InterviewListSerializer(read_only=True)
    song = SongSummarySerializer(read_only=True)
    album = AlbumSummarySerializer(read_only=True)
    paragraph_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = InterviewEntityLink
        fields = [
            "id",
            "interview",
            "song",
            "album",
            "paragraph_id",
            "scope",
            "method",
            "confidence",
            "review_status",
            "start_offset",
            "end_offset",
            "evidence",
        ]

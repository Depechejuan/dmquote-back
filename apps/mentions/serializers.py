from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.serializers import AlbumSummarySerializer, SongSummarySerializer
from apps.interviews.serializers import InterviewListSerializer, SourceAttributionSerializer
from apps.transcripts.serializers import TranscriptSectionCitationSerializer

from .models import InterviewEntityLink


class InterviewEntityLinkSerializer(serializers.ModelSerializer):
    interview = InterviewListSerializer(read_only=True)
    song = SongSummarySerializer(read_only=True, allow_null=True)
    album = AlbumSummarySerializer(read_only=True, allow_null=True)
    section = TranscriptSectionCitationSerializer(read_only=True, allow_null=True)
    paragraph_id = serializers.IntegerField(read_only=True, allow_null=True)
    paragraph_order = serializers.SerializerMethodField()
    source = SourceAttributionSerializer(source="interview", read_only=True)

    class Meta:
        model = InterviewEntityLink
        fields = [
            "id",
            "interview",
            "song",
            "album",
            "section",
            "paragraph_id",
            "paragraph_order",
            "scope",
            "method",
            "confidence",
            "review_status",
            "start_offset",
            "end_offset",
            "evidence",
            "source",
        ]

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_paragraph_order(self, obj):
        return obj.paragraph.order if obj.paragraph_id else None

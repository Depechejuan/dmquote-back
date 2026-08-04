from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.serializers import AlbumSummarySerializer, SongSummarySerializer
from apps.interviews.serializers import InterviewListSerializer, SourceAttributionSerializer
from apps.transcripts.serializers import (
    TranscriptParagraphSerializer,
    TranscriptSectionCitationSerializer,
)

from .models import InterviewEntityLink


class InterviewEntityLinkSerializer(serializers.ModelSerializer):
    interview = InterviewListSerializer(read_only=True)
    song = SongSummarySerializer(read_only=True, allow_null=True)
    album = AlbumSummarySerializer(read_only=True, allow_null=True)
    section = TranscriptSectionCitationSerializer(read_only=True, allow_null=True)
    question = serializers.SerializerMethodField()
    answer = serializers.SerializerMethodField()
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
            "question",
            "answer",
            "paragraph_id",
            "paragraph_order",
            "scope",
            "method",
            "confidence",
            "review_status",
            "start_offset",
            "end_offset",
            "evidence",
            "excerpt_type",
            "source",
        ]

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_paragraph_order(self, obj):
        return obj.paragraph.order if obj.paragraph_id else None

    def _public_paragraph(self, paragraph):
        if paragraph is None:
            return None
        if paragraph.publication_status != "authorized_text":
            return None
        return TranscriptParagraphSerializer(paragraph, context=self.context).data

    @extend_schema_field(TranscriptParagraphSerializer(allow_null=True))
    def get_question(self, obj):
        return self._public_paragraph(obj.question_paragraph)

    @extend_schema_field(TranscriptParagraphSerializer(allow_null=True))
    def get_answer(self, obj):
        return self._public_paragraph(obj.answer_paragraph)

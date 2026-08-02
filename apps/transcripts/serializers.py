from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Transcript, TranscriptParagraph, TranscriptSection


class TranscriptParagraphSerializer(serializers.ModelSerializer):
    class Meta:
        model = TranscriptParagraph
        fields = [
            "id",
            "order",
            "speaker",
            "text",
            "start_seconds",
            "end_seconds",
        ]


class TranscriptSectionCitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TranscriptSection
        fields = ["id", "order", "heading", "level", "section_type", "source_anchor"]


class TranscriptSectionSerializer(TranscriptSectionCitationSerializer):
    paragraphs = serializers.SerializerMethodField()

    class Meta(TranscriptSectionCitationSerializer.Meta):
        fields = TranscriptSectionCitationSerializer.Meta.fields + [
            "publication_status",
            "paragraphs",
        ]

    @extend_schema_field(TranscriptParagraphSerializer(many=True))
    def get_paragraphs(self, obj):
        paragraphs = obj.paragraphs.filter(
            publication_status="authorized_text"
        ).order_by("order")
        return TranscriptParagraphSerializer(
            paragraphs,
            many=True,
            context=self.context,
        ).data


class TranscriptSerializer(serializers.ModelSerializer):
    sections = serializers.SerializerMethodField()
    paragraphs = serializers.SerializerMethodField()

    class Meta:
        model = Transcript
        fields = [
            "id",
            "language",
            "status",
            "publication_status",
            "sections",
            "paragraphs",
        ]

    @extend_schema_field(TranscriptSectionSerializer(many=True))
    def get_sections(self, obj):
        if obj.publication_status != "authorized_text":
            return []
        sections = obj.sections.filter(
            publication_status="authorized_text"
        ).order_by("order")
        return TranscriptSectionSerializer(
            sections,
            many=True,
            context=self.context,
        ).data

    @extend_schema_field(TranscriptParagraphSerializer(many=True))
    def get_paragraphs(self, obj):
        if obj.publication_status != "authorized_text":
            return []
        paragraphs = obj.paragraphs.filter(
            publication_status="authorized_text",
            section__publication_status="authorized_text",
        ).order_by("section__order", "order")
        return TranscriptParagraphSerializer(
            paragraphs,
            many=True,
            context=self.context,
        ).data

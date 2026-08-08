from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    Transcript,
    TranscriptParagraph,
    TranscriptSection,
    TranscriptTranslation,
    TranscriptTranslationParagraph,
    TranscriptTranslationRequest,
    TranscriptTranslationSection,
)
from .translations import translation_options


class TranslationOptionSerializer(serializers.Serializer):
    language = serializers.CharField()
    status = serializers.ChoiceField(choices=["available", "requested", "unavailable"])


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
    translation_options = serializers.SerializerMethodField()
    is_translation = serializers.SerializerMethodField()

    class Meta:
        model = Transcript
        fields = [
            "id",
            "language",
            "status",
            "publication_status",
            "sections",
            "paragraphs",
            "translation_options",
            "is_translation",
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

    @extend_schema_field(TranslationOptionSerializer(many=True))
    def get_translation_options(self, obj):
        return translation_options(obj)

    @extend_schema_field(serializers.BooleanField())
    def get_is_translation(self, obj):
        return False


class TranscriptTranslationParagraphSerializer(serializers.ModelSerializer):
    class Meta:
        model = TranscriptTranslationParagraph
        fields = [
            "id",
            "order",
            "speaker",
            "text",
            "start_seconds",
            "end_seconds",
        ]


class TranscriptTranslationSectionSerializer(serializers.ModelSerializer):
    paragraphs = TranscriptTranslationParagraphSerializer(many=True, read_only=True)

    class Meta:
        model = TranscriptTranslationSection
        fields = [
            "id",
            "order",
            "heading",
            "level",
            "section_type",
            "source_anchor",
            "paragraphs",
        ]


class TranscriptTranslationSerializer(serializers.ModelSerializer):
    """Public shape intentionally mirrors a source transcript."""

    language = serializers.CharField(source="target_language")
    source_language = serializers.CharField(source="transcript.language")
    status = serializers.CharField(source="transcript.status")
    publication_status = serializers.CharField(source="transcript.publication_status")
    sections = TranscriptTranslationSectionSerializer(many=True, read_only=True)
    paragraphs = serializers.SerializerMethodField()
    translation_options = serializers.SerializerMethodField()
    is_translation = serializers.SerializerMethodField()

    class Meta:
        model = TranscriptTranslation
        fields = [
            "id",
            "language",
            "source_language",
            "status",
            "publication_status",
            "sections",
            "paragraphs",
            "translation_options",
            "is_translation",
        ]

    @extend_schema_field(TranscriptTranslationParagraphSerializer(many=True))
    def get_paragraphs(self, obj):
        return TranscriptTranslationParagraphSerializer(
            obj.paragraphs.select_related("section").order_by("section__order", "order"),
            many=True,
            context=self.context,
        ).data

    @extend_schema_field(TranslationOptionSerializer(many=True))
    def get_translation_options(self, obj):
        return translation_options(obj.transcript)

    @extend_schema_field(serializers.BooleanField())
    def get_is_translation(self, obj):
        return True


class TranscriptTranslationRequestSerializer(serializers.ModelSerializer):
    language = serializers.CharField(source="target_language")

    class Meta:
        model = TranscriptTranslationRequest
        fields = ["id", "language", "status", "requested_at"]

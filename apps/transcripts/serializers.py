from rest_framework import serializers

from .models import Transcript, TranscriptParagraph


class TranscriptParagraphSerializer(serializers.ModelSerializer):
    class Meta:
        model = TranscriptParagraph
        fields = ["id", "order", "speaker", "text", "start_seconds", "end_seconds"]


class TranscriptSerializer(serializers.ModelSerializer):
    paragraphs = serializers.SerializerMethodField()

    class Meta:
        model = Transcript
        fields = ["id", "language", "status", "publication_status", "paragraphs"]

    def get_paragraphs(self, obj):
        paragraphs = obj.paragraphs.filter(publication_status="authorized_text")
        return TranscriptParagraphSerializer(paragraphs, many=True, context=self.context).data

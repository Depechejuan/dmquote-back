from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.serializers import PersonSerializer

from .models import Interview, InterviewParticipant


class InterviewParticipantSerializer(serializers.ModelSerializer):
    person = PersonSerializer(read_only=True)

    class Meta:
        model = InterviewParticipant
        fields = ["person", "role", "sort_order"]


class InterviewListSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    date = serializers.ReadOnlyField(source="date_display")

    class Meta:
        model = Interview
        fields = [
            "id",
            "title",
            "slug",
            "date",
            "date_year",
            "date_precision",
            "outlet",
            "location",
            "audio_url",
            "source_url",
            "transcript_status",
            "publication_status",
            "participants",
        ]

    @extend_schema_field(InterviewParticipantSerializer(many=True))
    def get_participants(self, obj):
        return InterviewParticipantSerializer(
            obj.participant_links.all(), many=True, context=self.context
        ).data


class InterviewDetailSerializer(InterviewListSerializer):
    class Meta(InterviewListSerializer.Meta):
        fields = InterviewListSerializer.Meta.fields + [
            "date_month",
            "date_day",
            "notes",
            "source_updated_at",
        ]

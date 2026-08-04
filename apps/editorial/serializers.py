from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import Album, Song
from apps.catalog.serializers import (
    AlbumSummarySerializer,
    MusicAlbumSerializer,
    MusicSongSerializer,
    SongSummarySerializer,
)
from apps.interviews.models import Interview
from apps.interviews.serializers import (
    InterviewListSerializer,
    InterviewParticipantSerializer,
    SourceAttributionSerializer,
)
from apps.mentions.models import InterviewEntityLink
from apps.transcripts.models import TranscriptParagraph, TranscriptSection


class EditorialParagraphSerializer(serializers.ModelSerializer):
    class Meta:
        model = TranscriptParagraph
        fields = [
            "id",
            "section_id",
            "order",
            "speaker",
            "text",
            "publication_status",
            "start_seconds",
            "end_seconds",
        ]


class EditorialSectionSerializer(serializers.ModelSerializer):
    paragraphs = EditorialParagraphSerializer(many=True, read_only=True)

    class Meta:
        model = TranscriptSection
        fields = [
            "id",
            "transcript_id",
            "order",
            "heading",
            "level",
            "section_type",
            "source_anchor",
            "publication_status",
            "paragraphs",
        ]


class EditorialSectionCitationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TranscriptSection
        fields = [
            "id",
            "transcript_id",
            "order",
            "heading",
            "level",
            "section_type",
            "source_anchor",
            "publication_status",
        ]


class EditorialTranscriptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    language = serializers.CharField()
    status = serializers.CharField()
    publication_status = serializers.CharField()
    notes = serializers.CharField()
    sections = EditorialSectionSerializer(many=True)


class EditorialInterviewSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    date = serializers.ReadOnlyField(source="date_display")
    source = SourceAttributionSerializer(source="*", read_only=True)
    transcript = serializers.SerializerMethodField()

    class Meta:
        model = Interview
        fields = [
            "id",
            "title",
            "slug",
            "date",
            "date_year",
            "date_month",
            "date_day",
            "date_precision",
            "outlet",
            "medium",
            "location",
            "audio_url",
            "source_url",
            "source",
            "source_present",
            "transcript_status",
            "publication_status",
            "classification_status",
            "participants",
            "notes",
            "transcript",
        ]

    @extend_schema_field(InterviewParticipantSerializer(many=True))
    def get_participants(self, obj):
        return InterviewParticipantSerializer(
            obj.participant_links.all(), many=True, context=self.context
        ).data

    @extend_schema_field(EditorialTranscriptSerializer(allow_null=True))
    def get_transcript(self, obj):
        transcript = getattr(obj, "transcript", None)
        if transcript is None:
            return None
        return EditorialTranscriptSerializer(transcript, context=self.context).data


class EditorialMentionSerializer(serializers.ModelSerializer):
    interview = InterviewListSerializer(read_only=True)
    song = SongSummarySerializer(read_only=True, allow_null=True)
    album = AlbumSummarySerializer(read_only=True, allow_null=True)
    section = EditorialSectionCitationSerializer(read_only=True, allow_null=True)
    paragraph = EditorialParagraphSerializer(read_only=True, allow_null=True)
    question = EditorialParagraphSerializer(
        source="question_paragraph", read_only=True, allow_null=True
    )
    answer = EditorialParagraphSerializer(
        source="answer_paragraph", read_only=True, allow_null=True
    )
    source = SourceAttributionSerializer(source="interview", read_only=True)
    paragraph_order = serializers.SerializerMethodField()

    class Meta:
        model = InterviewEntityLink
        fields = [
            "id",
            "interview",
            "song",
            "album",
            "section",
            "paragraph",
            "paragraph_order",
            "question",
            "answer",
            "scope",
            "method",
            "confidence",
            "review_status",
            "excerpt_type",
            "start_offset",
            "end_offset",
            "evidence",
            "paragraph_content_hash",
            "source",
        ]

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_paragraph_order(self, obj):
        return obj.paragraph.order if obj.paragraph_id else None


class EditorialMentionUpdateSerializer(serializers.Serializer):
    song_id = serializers.IntegerField(required=False, allow_null=True)
    album_id = serializers.IntegerField(required=False, allow_null=True)
    section_id = serializers.IntegerField(required=False, allow_null=True)
    paragraph_id = serializers.IntegerField(required=False, allow_null=True)
    question_paragraph_id = serializers.IntegerField(required=False, allow_null=True)
    answer_paragraph_id = serializers.IntegerField(required=False, allow_null=True)
    scope = serializers.ChoiceField(choices=InterviewEntityLink.Scope.choices, required=False)
    review_status = serializers.ChoiceField(
        choices=InterviewEntityLink.ReviewStatus.choices, required=False
    )
    excerpt_type = serializers.ChoiceField(
        choices=InterviewEntityLink.ExcerptType.choices, required=False
    )
    evidence = serializers.CharField(required=False, allow_blank=True)
    start_offset = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    end_offset = serializers.IntegerField(required=False, allow_null=True, min_value=0)

    def _paragraph(self, value, field_name):
        if value is None:
            return None
        try:
            return TranscriptParagraph.objects.select_related("transcript", "section").get(
                pk=value
            )
        except TranscriptParagraph.DoesNotExist as exc:
            raise serializers.ValidationError({field_name: "Paragraph not found."}) from exc

    def _song(self, value):
        if value is None:
            return None
        try:
            return Song.objects.get(pk=value)
        except Song.DoesNotExist as exc:
            raise serializers.ValidationError({"song_id": "Song not found."}) from exc

    def _album(self, value):
        if value is None:
            return None
        try:
            return Album.objects.get(pk=value)
        except Album.DoesNotExist as exc:
            raise serializers.ValidationError({"album_id": "Album not found."}) from exc

    def validate(self, attrs):
        instance = self.instance
        song_id = attrs.get("song_id", instance.song_id)
        album_id = attrs.get("album_id", instance.album_id)
        if bool(song_id) == bool(album_id):
            raise serializers.ValidationError(
                "A mention must target exactly one song or album."
            )

        song = self._song(song_id) if "song_id" in attrs else instance.song
        album = self._album(album_id) if "album_id" in attrs else instance.album
        attrs["_song"] = song
        attrs["_album"] = album

        scope = attrs.get("scope", instance.scope)
        section_id = attrs.get("section_id", instance.section_id)
        paragraph_id = attrs.get("paragraph_id", instance.paragraph_id)
        section = (
            TranscriptSection.objects.select_related("transcript").filter(pk=section_id).first()
            if section_id
            else None
        )
        if section_id and section is None:
            raise serializers.ValidationError({"section_id": "Section not found."})
        paragraph = self._paragraph(paragraph_id, "paragraph_id") if paragraph_id else None
        if scope == InterviewEntityLink.Scope.PARAGRAPH:
            if paragraph is None or section is None:
                raise serializers.ValidationError(
                    "Paragraph scope requires both a paragraph and a section."
                )
        elif section is not None or paragraph is not None:
            raise serializers.ValidationError(
                "Interview scope cannot reference a section or paragraph."
            )
        if paragraph and paragraph.transcript.interview_id != instance.interview_id:
            raise serializers.ValidationError("The paragraph must belong to the interview.")
        if section and section.transcript.interview_id != instance.interview_id:
            raise serializers.ValidationError("The section must belong to the interview.")
        if paragraph and paragraph.section_id != section.id:
            raise serializers.ValidationError(
                "The paragraph must belong to the selected section."
            )

        question_id = attrs.get("question_paragraph_id", instance.question_paragraph_id)
        answer_id = attrs.get("answer_paragraph_id", instance.answer_paragraph_id)
        question = self._paragraph(question_id, "question_paragraph_id") if question_id else None
        answer = self._paragraph(answer_id, "answer_paragraph_id") if answer_id else None
        for related in (question, answer):
            if related and related.transcript.interview_id != instance.interview_id:
                raise serializers.ValidationError(
                    "Question and answer paragraphs must belong to the interview."
                )
        excerpt_type = attrs.get("excerpt_type", instance.excerpt_type)
        if excerpt_type == InterviewEntityLink.ExcerptType.QA and not (question and answer):
            raise serializers.ValidationError(
                "A Q/A excerpt requires both a question and an answer paragraph."
            )
        if excerpt_type != InterviewEntityLink.ExcerptType.QA and (question or answer):
            raise serializers.ValidationError(
                "Only Q/A excerpts can reference question and answer paragraphs."
            )

        if ("start_offset" in attrs) != ("end_offset" in attrs):
            raise serializers.ValidationError(
                "Start and end offsets must be provided together."
            )
        start = attrs.get("start_offset", instance.start_offset)
        end = attrs.get("end_offset", instance.end_offset)
        if (start is None) != (end is None):
            raise serializers.ValidationError(
                "Start and end offsets must be provided together."
            )
        if paragraph and start is not None and end is not None and end > len(paragraph.text):
            raise serializers.ValidationError(
                "Offsets must point inside the selected paragraph."
            )

        attrs["_section"] = section
        attrs["_paragraph"] = paragraph
        attrs["_question"] = question
        attrs["_answer"] = answer
        return attrs

    def update(self, instance, validated_data):
        if "song_id" in validated_data:
            instance.song = validated_data["_song"]
        if "album_id" in validated_data:
            instance.album = validated_data["_album"]
        if "section_id" in validated_data:
            instance.section = validated_data["_section"]
        if "paragraph_id" in validated_data:
            instance.paragraph = validated_data["_paragraph"]
        if "question_paragraph_id" in validated_data:
            instance.question_paragraph = validated_data["_question"]
        if "answer_paragraph_id" in validated_data:
            instance.answer_paragraph = validated_data["_answer"]
        for field in (
            "scope",
            "review_status",
            "excerpt_type",
            "evidence",
            "start_offset",
            "end_offset",
        ):
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        instance.save()
        return instance


class PublicationVisibilitySerializer(serializers.Serializer):
    publication_status = serializers.ChoiceField(choices=Interview.PublicationStatus.choices)


class CSRFSerializer(serializers.Serializer):
    csrf_token = serializers.CharField()


class EditorialCatalogSerializer(serializers.Serializer):
    albums = MusicAlbumSerializer(many=True)
    standalone_songs = MusicSongSerializer(many=True)

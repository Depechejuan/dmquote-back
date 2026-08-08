import hashlib

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
from apps.interviews.models import Interview, InterviewMentionReview
from apps.interviews.serializers import (
    InterviewListSerializer,
    InterviewParticipantSerializer,
    SourceAttributionSerializer,
)
from apps.mentions.models import InterviewEntityLink
from apps.transcripts.models import (
    TranscriptParagraph,
    TranscriptSection,
    TranscriptTranslationRequest,
    validate_language_code,
)


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


class EditorialTranslationRequestSerializer(serializers.ModelSerializer):
    language = serializers.CharField(source="target_language")
    source_language = serializers.CharField(source="transcript.language")
    interview_slug = serializers.SlugField(source="transcript.interview.slug")
    interview_title = serializers.CharField(source="transcript.interview.title")

    class Meta:
        model = TranscriptTranslationRequest
        fields = [
            "id",
            "language",
            "source_language",
            "status",
            "requested_at",
            "completed_at",
            "interview_slug",
            "interview_title",
        ]


class EditorialTranscriptSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    language = serializers.CharField()
    status = serializers.CharField()
    publication_status = serializers.CharField()
    notes = serializers.CharField()
    sections = EditorialSectionSerializer(many=True)
    translation_requests = serializers.SerializerMethodField()

    @extend_schema_field(EditorialTranslationRequestSerializer(many=True))
    def get_translation_requests(self, obj):
        return EditorialTranslationRequestSerializer(
            obj.translation_requests.all(),
            many=True,
            context=self.context,
        ).data


class EditorialReviewStateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=InterviewMentionReview.Status.choices)
    reviewer = serializers.SerializerMethodField()
    reviewed_at = serializers.DateTimeField(allow_null=True)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_reviewer(self, obj):
        return obj.reviewer.get_username() if obj.reviewer_id else None


class EditorialInterviewSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    date = serializers.ReadOnlyField(source="date_display")
    source = SourceAttributionSerializer(source="*", read_only=True)
    transcript = serializers.SerializerMethodField()
    mention_review = serializers.SerializerMethodField()

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
            "mention_review",
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

    @extend_schema_field(EditorialReviewStateSerializer)
    def get_mention_review(self, obj):
        try:
            review = obj.mention_review
        except InterviewMentionReview.DoesNotExist:
            return {"status": InterviewMentionReview.Status.PENDING, "reviewer": None, "reviewed_at": None}
        return EditorialReviewStateSerializer(review, context=self.context).data


class EditorialInterviewQueueSerializer(InterviewListSerializer):
    """An interview-led queue, including records with no detected mentions."""

    review = serializers.SerializerMethodField()
    candidate_count = serializers.IntegerField(read_only=True)
    verified_count = serializers.IntegerField(read_only=True)

    class Meta(InterviewListSerializer.Meta):
        fields = InterviewListSerializer.Meta.fields + [
            "review",
            "candidate_count",
            "verified_count",
        ]

    @extend_schema_field(EditorialReviewStateSerializer)
    def get_review(self, obj):
        try:
            review = obj.mention_review
        except InterviewMentionReview.DoesNotExist:
            return {"status": InterviewMentionReview.Status.PENDING, "reviewer": None, "reviewed_at": None}
        return EditorialReviewStateSerializer(review, context=self.context).data


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

    def _section(self, value):
        if value is None:
            return None
        section = TranscriptSection.objects.select_related("transcript").filter(pk=value).first()
        if section is None:
            raise serializers.ValidationError({"section_id": "Section not found."})
        return section

    def _interview(self, attrs):
        return self.instance.interview

    def _current_id(self, attrs, field_name):
        if field_name in attrs:
            return attrs[field_name]
        if self.instance is None:
            return None
        return getattr(self.instance, field_name)

    def _current_value(self, attrs, field_name, default=None):
        if field_name in attrs:
            return attrs[field_name]
        if self.instance is None:
            return default
        return getattr(self.instance, field_name)

    def validate(self, attrs):
        interview = self._interview(attrs)
        song_id = self._current_id(attrs, "song_id")
        album_id = self._current_id(attrs, "album_id")
        if bool(song_id) == bool(album_id):
            raise serializers.ValidationError(
                "A mention must target exactly one song or album."
            )

        song = self._song(song_id) if song_id else None
        album = self._album(album_id) if album_id else None
        attrs["_song"] = song
        attrs["_album"] = album

        scope = self._current_value(attrs, "scope", InterviewEntityLink.Scope.PARAGRAPH)
        section_id = self._current_id(attrs, "section_id")
        paragraph_id = self._current_id(attrs, "paragraph_id")
        section = self._section(section_id)
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
        if paragraph and paragraph.transcript.interview_id != interview.pk:
            raise serializers.ValidationError("The paragraph must belong to the interview.")
        if section and section.transcript.interview_id != interview.pk:
            raise serializers.ValidationError("The section must belong to the interview.")
        if paragraph and paragraph.section_id != section.id:
            raise serializers.ValidationError(
                "The paragraph must belong to the selected section."
            )

        question_id = self._current_id(attrs, "question_paragraph_id")
        answer_id = self._current_id(attrs, "answer_paragraph_id")
        question = self._paragraph(question_id, "question_paragraph_id") if question_id else None
        answer = self._paragraph(answer_id, "answer_paragraph_id") if answer_id else None
        for related in (question, answer):
            if related and related.transcript.interview_id != interview.pk:
                raise serializers.ValidationError(
                    "Question and answer paragraphs must belong to the interview."
                )
        excerpt_type = self._current_value(
            attrs, "excerpt_type", InterviewEntityLink.ExcerptType.PARAGRAPH
        )
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
        start = self._current_value(attrs, "start_offset")
        end = self._current_value(attrs, "end_offset")
        if (start is None) != (end is None):
            raise serializers.ValidationError(
                "Start and end offsets must be provided together."
            )
        if start is not None:
            if paragraph is None or not (0 <= start < end <= len(paragraph.text)):
                raise serializers.ValidationError(
                    "Offsets must define a non-empty range inside the selected paragraph."
                )

        attrs["_interview"] = interview
        attrs["_section"] = section
        attrs["_paragraph"] = paragraph
        attrs["_question"] = question
        attrs["_answer"] = answer
        return attrs

    def _save_mention(self, instance):
        if instance.paragraph_id:
            instance.paragraph_content_hash = hashlib.sha256(
                instance.paragraph.text.encode("utf-8")
            ).hexdigest()
        else:
            instance.paragraph_content_hash = ""
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        instance.save()
        return instance

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
        return self._save_mention(instance)


class EditorialMentionCreateSerializer(EditorialMentionUpdateSerializer):
    interview_slug = serializers.SlugField(write_only=True)
    song_id = serializers.IntegerField(required=False, allow_null=True)
    album_id = serializers.IntegerField(required=False, allow_null=True)
    section_id = serializers.IntegerField(required=False, allow_null=True)
    paragraph_id = serializers.IntegerField(required=False, allow_null=True)
    scope = serializers.ChoiceField(
        choices=InterviewEntityLink.Scope.choices, default=InterviewEntityLink.Scope.PARAGRAPH
    )
    review_status = serializers.ChoiceField(
        choices=InterviewEntityLink.ReviewStatus.choices,
        default=InterviewEntityLink.ReviewStatus.SUGGESTED,
    )
    excerpt_type = serializers.ChoiceField(
        choices=InterviewEntityLink.ExcerptType.choices,
        default=InterviewEntityLink.ExcerptType.PARAGRAPH,
    )

    def _interview(self, attrs):
        try:
            return Interview.objects.get(slug=attrs["interview_slug"])
        except Interview.DoesNotExist as exc:
            raise serializers.ValidationError({"interview_slug": "Interview not found."}) from exc

    def create(self, validated_data):
        instance = InterviewEntityLink(
            interview=validated_data["_interview"],
            song=validated_data["_song"],
            album=validated_data["_album"],
            section=validated_data["_section"],
            paragraph=validated_data["_paragraph"],
            question_paragraph=validated_data["_question"],
            answer_paragraph=validated_data["_answer"],
            scope=validated_data.get("scope", InterviewEntityLink.Scope.PARAGRAPH),
            review_status=validated_data.get(
                "review_status", InterviewEntityLink.ReviewStatus.SUGGESTED
            ),
            excerpt_type=validated_data.get(
                "excerpt_type", InterviewEntityLink.ExcerptType.PARAGRAPH
            ),
            evidence=validated_data.get("evidence", ""),
            start_offset=validated_data.get("start_offset"),
            end_offset=validated_data.get("end_offset"),
            method=InterviewEntityLink.Method.MANUAL,
        )
        return self._save_mention(instance)


class EditorialReviewUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=InterviewMentionReview.Status.choices)


class PublicationVisibilitySerializer(serializers.Serializer):
    publication_status = serializers.ChoiceField(choices=Interview.PublicationStatus.choices)


class CSRFSerializer(serializers.Serializer):
    csrf_token = serializers.CharField()


class EditorialTranscriptLanguageSerializer(serializers.Serializer):
    language = serializers.CharField(max_length=12, validators=[validate_language_code])

    def validate_language(self, value):
        return value.strip().lower().replace("_", "-")


class EditorialCatalogSerializer(serializers.Serializer):
    albums = MusicAlbumSerializer(many=True)
    standalone_songs = MusicSongSerializer(many=True)

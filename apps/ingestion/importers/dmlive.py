from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.catalog.models import Person
from apps.ingestion.parsers.dmlive import ParsedPage, parse_source_file
from apps.interviews.models import ImportRun, Interview, InterviewParticipant, SourceSnapshot
from apps.mentions.models import InterviewEntityLink
from apps.transcripts.models import Transcript, TranscriptParagraph, TranscriptSection

DATE_RE = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2}|xx)-(?P<day>\d{2}|xx|\dx)\s+(?P<body>.+)$", re.I)
KNOWN_PARTICIPANTS = {
    "alan": "Alan Wilder",
    "alan wilder": "Alan Wilder",
    "andy": "Andrew Fletcher",
    "andy fletcher": "Andrew Fletcher",
    "andrew": "Andrew Fletcher",
    "andrew fletcher": "Andrew Fletcher",
    "dave": "Dave Gahan",
    "dave gahan": "Dave Gahan",
    "david": "Dave Gahan",
    "david gahan": "Dave Gahan",
    "fletch": "Andrew Fletcher",
    "martin": "Martin Gore",
    "martin gore": "Martin Gore",
    "vince": "Vince Clarke",
    "vince clarke": "Vince Clarke",
}
IGNORED_SPEAKERS = {"host", "interviewer", "interviewer 1", "interviewer 2", "unknown"}


@dataclass
class ImportSummary:
    input_name: str
    input_format: str
    dry_run: bool
    pages_seen: int = 0
    pages_imported: int = 0
    pages_created: int = 0
    pages_updated: int = 0
    pages_unchanged: int = 0
    pages_skipped: int = 0
    pages_needs_review: int = 0
    pages_marked_missing: int = 0
    pages_failed: int = 0
    snapshots_created: int = 0
    sections_created: int = 0
    paragraphs_created: int = 0
    errors: list[str] | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def as_dict(self) -> dict:
        return asdict(self)


class DMLiveImportError(Exception):
    pass


class DMLiveImporter:
    def __init__(self, *, snapshot_dir: str | Path | None = None):
        configured_dir = snapshot_dir or getattr(settings, "DMLIVE_SNAPSHOT_DIR", "snapshots")
        path = Path(configured_dir)
        self.snapshot_dir = path if path.is_absolute() else settings.BASE_DIR / path

    def import_file(
        self,
        input_path: str | Path,
        *,
        input_format: str = "auto",
        dry_run: bool = False,
        bulk: bool = False,
        mark_missing: bool = False,
    ) -> ImportSummary:
        path = Path(input_path).expanduser()
        if not path.is_file():
            raise DMLiveImportError(f"Input file does not exist or is not a file: {path}")

        selected_format = self._select_format(path, input_format)
        if bulk:
            return self._import_file_bulk(
                path,
                selected_format,
                dry_run=dry_run,
                mark_missing=mark_missing,
            )
        summary = ImportSummary(
            input_name=str(path), input_format=selected_format, dry_run=dry_run
        )
        input_hash = sha256_file(path)
        import_run = None
        seen_page_ids: set[int] = set()

        if not dry_run:
            import_run = ImportRun.objects.create(
                input_format=selected_format,
                input_name=str(path),
                input_sha256=input_hash,
            )

        try:
            for page in parse_source_file(path, selected_format):
                summary.pages_seen += 1
                if page.namespace != 0 or not page.title:
                    summary.pages_skipped += 1
                    continue
                if page.page_id is not None:
                    seen_page_ids.add(page.page_id)
                try:
                    if dry_run:
                        self._count_dry_run(page, summary)
                    else:
                        with transaction.atomic():
                            outcome = self._import_page(page, import_run, summary)
                        summary.pages_imported += 1
                        if outcome == "created":
                            summary.pages_created += 1
                        elif outcome == "updated":
                            summary.pages_updated += 1
                        else:
                            summary.pages_unchanged += 1
                        if not page.is_interview:
                            summary.pages_needs_review += 1
                except Exception as exc:
                    summary.pages_failed += 1
                    summary.errors.append(f"{page.title}: {type(exc).__name__}: {exc}")

            if not dry_run and mark_missing:
                summary.pages_marked_missing = self._mark_missing(
                    seen_page_ids, import_run
                )
            if import_run is not None:
                import_run.pages_seen = summary.pages_seen
                import_run.pages_created = summary.pages_created
                import_run.pages_updated = summary.pages_updated
                import_run.pages_skipped = summary.pages_skipped
                import_run.pages_failed = summary.pages_failed
                import_run.status = (
                    ImportRun.Status.FAILED
                    if summary.pages_failed and not summary.pages_imported
                    else ImportRun.Status.PARTIAL
                    if summary.pages_failed
                    else ImportRun.Status.SUCCESS
                )
                from django.utils import timezone

                import_run.completed_at = timezone.now()
                import_run.error_message = "\n".join(summary.errors)
                import_run.save(
                    update_fields=[
                        "pages_seen",
                        "pages_created",
                        "pages_updated",
                        "pages_skipped",
                        "pages_failed",
                        "status",
                        "completed_at",
                        "error_message",
                    ]
                )
        except Exception:
            if import_run is not None:
                import_run.status = ImportRun.Status.FAILED
                import_run.error_message = "Parser failed before import completed."
                from django.utils import timezone

                import_run.completed_at = timezone.now()
                import_run.save(update_fields=["status", "error_message", "completed_at"])
            raise
        return summary

    def _import_file_bulk(
        self,
        path: Path,
        selected_format: str,
        *,
        dry_run: bool,
        mark_missing: bool,
    ) -> ImportSummary:
        summary = ImportSummary(
            input_name=str(path), input_format=selected_format, dry_run=dry_run
        )
        pages = list(parse_source_file(path, selected_format))
        content_pages = []
        seen_page_ids: set[int] = set()
        for page in pages:
            summary.pages_seen += 1
            if page.namespace != 0 or not page.title:
                summary.pages_skipped += 1
                continue
            if page.page_id is not None:
                seen_page_ids.add(page.page_id)
            if dry_run:
                self._count_dry_run(page, summary)
            else:
                content_pages.append(page)

        if dry_run:
            return summary

        import_run = ImportRun.objects.create(
            input_format=selected_format,
            input_name=str(path),
            input_sha256=sha256_file(path),
        )
        try:
            with transaction.atomic():
                self._bulk_import_pages(content_pages, import_run, summary)
                if mark_missing:
                    summary.pages_marked_missing = self._bulk_mark_missing(
                        seen_page_ids, import_run
                    )
                self._finish_import_run(import_run, summary)
        except Exception:
            import_run.status = ImportRun.Status.FAILED
            import_run.error_message = "Bulk import failed before completion."
            import_run.completed_at = timezone.now()
            import_run.save(update_fields=["status", "error_message", "completed_at"])
            raise
        return summary

    def _bulk_import_pages(
        self, pages: list[ParsedPage], import_run: ImportRun, summary: ImportSummary
    ):
        page_ids = [page.page_id for page in pages if page.page_id is not None]
        interviews_by_page = {
            interview.source_page_id: interview
            for interview in Interview.objects.filter(source_page_id__in=page_ids)
        }
        source_urls = [page.source_url for page in pages]
        interviews_by_url = {
            interview.source_url: interview
            for interview in Interview.objects.filter(source_url__in=source_urls)
        }
        used_slugs = set(Interview.objects.values_list("slug", flat=True))
        states = []
        new_interviews = []
        existing_interviews = []

        for page in pages:
            interview = interviews_by_page.get(page.page_id) or interviews_by_url.get(
                page.source_url
            )
            content_hash = sha256_text(page.text)
            created = interview is None
            previous_hash = interview.source_content_hash if interview else ""
            if interview is None:
                title_data = title_metadata(page.title)
                interview = Interview(
                    title=page.title,
                    slug=unique_slug_from_set(used_slugs, page.title, page.page_id),
                    date_year=title_data["date_year"],
                    date_month=title_data["date_month"],
                    date_day=title_data["date_day"],
                    date_precision=title_data["date_precision"],
                    outlet=title_data["outlet"],
                    medium=infer_medium(page),
                    classification_status=(
                        Interview.ClassificationStatus.INTERVIEW
                        if page.is_interview
                        else Interview.ClassificationStatus.NEEDS_REVIEW
                    ),
                    location=title_data["location"],
                    source_url=page.source_url,
                    source_page_id=page.page_id,
                )
                new_interviews.append(interview)
            else:
                existing_interviews.append(interview)
            self._update_interview(interview, page, content_hash)
            states.append(
                {
                    "page": page,
                    "interview": interview,
                    "content_hash": content_hash,
                    "created": created,
                    "changed": created or previous_hash != content_hash,
                }
            )

        Interview.objects.bulk_create(new_interviews)
        Interview.objects.bulk_update(
            existing_interviews,
            [
                "title",
                "slug",
                "date_year",
                "date_month",
                "date_day",
                "date_precision",
                "outlet",
                "medium",
                "classification_status",
                "location",
                "source_url",
                "source_name",
                "source_domain",
                "source_page_id",
                "source_revision_id",
                "source_revision_timestamp",
                "source_content_hash",
                "source_present",
                "source_updated_at",
                "transcript_status",
            ],
        )
        summary.pages_imported = len(states)
        summary.pages_created = sum(state["created"] for state in states)
        summary.pages_updated = sum(
            state["changed"] and not state["created"] for state in states
        )
        summary.pages_unchanged = sum(
            not state["changed"] and not state["created"] for state in states
        )
        summary.pages_needs_review = sum(
            not state["page"].is_interview for state in states
        )

        self._bulk_sync_participants(states)
        self._bulk_create_snapshots(states, import_run, summary)
        self._bulk_sync_transcripts(states, summary)

    def _bulk_sync_participants(self, states):
        names = {
            name
            for state in states
            for name in participant_names(state["page"])
        }
        people = {
            person.name: person for person in Person.objects.filter(name__in=names)
        }
        used_slugs = set(Person.objects.values_list("slug", flat=True))
        new_people = []
        for name in sorted(names):
            if name in people:
                continue
            person = Person(name=name, slug=unique_person_slug_from_set(used_slugs, name), role="speaker")
            new_people.append(person)
            people[name] = person
        Person.objects.bulk_create(new_people)

        interview_ids = [state["interview"].pk for state in states]
        existing = {
            (link.interview_id, link.person_id): link
            for link in InterviewParticipant.objects.filter(interview_id__in=interview_ids)
        }
        new_links = []
        update_links = []
        for state in states:
            for sort_order, name in enumerate(participant_names(state["page"])):
                person = people[name]
                key = (state["interview"].pk, person.pk)
                link = existing.get(key)
                if link is None:
                    new_links.append(
                        InterviewParticipant(
                            interview=state["interview"],
                            person=person,
                            role="speaker",
                            sort_order=sort_order,
                        )
                    )
                else:
                    link.role = "speaker"
                    link.sort_order = sort_order
                    update_links.append(link)
        InterviewParticipant.objects.bulk_create(new_links)
        InterviewParticipant.objects.bulk_update(update_links, ["role", "sort_order"])

    def _bulk_create_snapshots(self, states, import_run: ImportRun, summary: ImportSummary):
        latest_by_interview = {}
        interview_ids = [state["interview"].pk for state in states]
        for snapshot in SourceSnapshot.objects.filter(interview_id__in=interview_ids).order_by(
            "interview_id", "-retrieved_at"
        ):
            latest_by_interview.setdefault(snapshot.interview_id, snapshot)

        snapshot_rows = []
        for state in states:
            latest = latest_by_interview.get(state["interview"].pk)
            unchanged = latest and latest.content_hash == state["content_hash"]
            if unchanged:
                status = SourceSnapshot.Status.NOT_MODIFIED
                snapshot_path = latest.snapshot_path
            else:
                status = SourceSnapshot.Status.SUCCESS
                snapshot_path = self._write_raw_snapshot(
                    state["page"], state["content_hash"]
                )
                summary.snapshots_created += 1
            snapshot_rows.append(
                SourceSnapshot(
                    interview=state["interview"],
                    import_run=import_run,
                    source_url=state["page"].source_url,
                    source_page_id=state["page"].page_id,
                    source_revision_id=state["page"].revision_id,
                    revision_timestamp=state["page"].revision_timestamp,
                    content_hash=state["content_hash"],
                    snapshot_path=snapshot_path,
                    status=status,
                    source_present=True,
                )
            )
        SourceSnapshot.objects.bulk_create(snapshot_rows)

    def _bulk_sync_transcripts(self, states, summary: ImportSummary):
        changed_states = [state for state in states if state["changed"]]
        if not changed_states:
            return
        changed_ids = [state["interview"].pk for state in changed_states]
        verified_ids = set(
            InterviewEntityLink.objects.filter(
                interview_id__in=changed_ids,
                review_status=InterviewEntityLink.ReviewStatus.VERIFIED,
            ).values_list("interview_id", flat=True)
        )
        if verified_ids:
            InterviewEntityLink.objects.filter(
                interview_id__in=verified_ids,
                review_status=InterviewEntityLink.ReviewStatus.VERIFIED,
            ).update(review_status=InterviewEntityLink.ReviewStatus.NEEDS_REVIEW)
            for state in changed_states:
                if state["interview"].pk in verified_ids:
                    state["interview"].transcript_status = Interview.TranscriptStatus.NEEDS_REVIEW

        transcript_by_interview = {
            transcript.interview_id: transcript
            for transcript in Transcript.objects.filter(interview_id__in=changed_ids)
        }
        new_transcripts = []
        for state in changed_states:
            interview_id = state["interview"].pk
            if interview_id in verified_ids or interview_id in transcript_by_interview:
                continue
            transcript = Transcript(interview=state["interview"])
            new_transcripts.append(transcript)
            transcript_by_interview[interview_id] = transcript
        Transcript.objects.bulk_create(new_transcripts)

        rewrite_states = [
            state for state in changed_states if state["interview"].pk not in verified_ids
        ]
        rewrite_transcript_ids = [
            transcript_by_interview[state["interview"].pk].pk for state in rewrite_states
        ]
        TranscriptSection.objects.filter(transcript_id__in=rewrite_transcript_ids).delete()
        section_rows = []
        section_state_pairs = []
        for state in rewrite_states:
            transcript = transcript_by_interview[state["interview"].pk]
            for parsed_section in state["page"].sections:
                section = TranscriptSection(
                    transcript=transcript,
                    order=parsed_section.order,
                    heading=parsed_section.heading,
                    level=parsed_section.level,
                    section_type=parsed_section.section_type,
                    source_anchor=parsed_section.source_anchor,
                )
                section_rows.append(section)
                section_state_pairs.append((parsed_section, section))
        TranscriptSection.objects.bulk_create(section_rows)

        paragraph_rows = []
        for parsed_section, section in section_state_pairs:
            for paragraph in parsed_section.paragraphs:
                paragraph_rows.append(
                    TranscriptParagraph(
                        transcript=section.transcript,
                        section=section,
                        order=paragraph.order,
                        speaker=paragraph.speaker,
                        text=paragraph.text,
                    )
                )
        TranscriptParagraph.objects.bulk_create(paragraph_rows)

        now = timezone.now()
        transcript_updates = []
        for state in rewrite_states:
            has_transcript = any(
                section.section_type == "transcript" for section in state["page"].sections
            )
            paragraph_count = sum(
                len(section.paragraphs) for section in state["page"].sections
            )
            transcript = transcript_by_interview[state["interview"].pk]
            transcript.status = (
                Interview.TranscriptStatus.COMPLETE
                if has_transcript
                else Interview.TranscriptStatus.PARTIAL
                if paragraph_count
                else Interview.TranscriptStatus.MISSING
            )
            transcript.updated_at = now
            transcript_updates.append(transcript)
            state["interview"].transcript_status = transcript.status
            summary.sections_created += len(state["page"].sections)
            summary.paragraphs_created += paragraph_count
        Transcript.objects.bulk_update(transcript_updates, ["status", "updated_at"])
        Interview.objects.bulk_update(
            [state["interview"] for state in changed_states], ["transcript_status"]
        )

    def _bulk_mark_missing(self, seen_page_ids: set[int], import_run: ImportRun) -> int:
        missing = Interview.objects.filter(source_domain="dmlive.wiki", source_present=True)
        if seen_page_ids:
            missing = missing.exclude(source_page_id__in=seen_page_ids)
        interviews = list(missing)
        for interview in interviews:
            interview.source_present = False
        Interview.objects.bulk_update(interviews, ["source_present"])
        SourceSnapshot.objects.bulk_create(
            [
                SourceSnapshot(
                    interview=interview,
                    import_run=import_run,
                    source_url=interview.source_url,
                    source_page_id=interview.source_page_id,
                    source_revision_id=interview.source_revision_id,
                    content_hash=interview.source_content_hash,
                    status=SourceSnapshot.Status.MISSING,
                    source_present=False,
                )
                for interview in interviews
            ]
        )
        return len(interviews)

    @staticmethod
    def _finish_import_run(import_run: ImportRun, summary: ImportSummary):
        import_run.pages_seen = summary.pages_seen
        import_run.pages_created = summary.pages_created
        import_run.pages_updated = summary.pages_updated
        import_run.pages_skipped = summary.pages_skipped
        import_run.pages_failed = summary.pages_failed
        import_run.status = (
            ImportRun.Status.FAILED
            if summary.pages_failed and not summary.pages_imported
            else ImportRun.Status.PARTIAL
            if summary.pages_failed
            else ImportRun.Status.SUCCESS
        )
        import_run.completed_at = timezone.now()
        import_run.error_message = "\n".join(summary.errors or [])
        import_run.save(
            update_fields=[
                "pages_seen",
                "pages_created",
                "pages_updated",
                "pages_skipped",
                "pages_failed",
                "status",
                "completed_at",
                "error_message",
            ]
        )

    def _import_page(
        self, page: ParsedPage, import_run: ImportRun, summary: ImportSummary
    ) -> str:
        content_hash = sha256_text(page.text)
        interview, created = self._get_or_create_interview(page)
        changed = created or interview.source_content_hash != content_hash
        self._update_interview(interview, page, content_hash)
        self._sync_participants(interview, page)

        latest_snapshot = interview.source_snapshots.order_by("-retrieved_at").first()
        if latest_snapshot and latest_snapshot.content_hash == content_hash:
            snapshot_status = SourceSnapshot.Status.NOT_MODIFIED
            snapshot_path = latest_snapshot.snapshot_path
        else:
            snapshot_status = SourceSnapshot.Status.SUCCESS
            snapshot_path = self._write_raw_snapshot(page, content_hash)
            summary.snapshots_created += 1

        SourceSnapshot.objects.create(
            interview=interview,
            import_run=import_run,
            source_url=page.source_url,
            source_page_id=page.page_id,
            source_revision_id=page.revision_id,
            revision_timestamp=page.revision_timestamp,
            content_hash=content_hash,
            snapshot_path=snapshot_path,
            status=snapshot_status,
            source_present=True,
        )

        if created or changed:
            self._sync_transcript(interview, page, summary)
        interview.save(
            update_fields=[
                "title",
                "slug",
                "date_year",
                "date_month",
                "date_day",
                "date_precision",
                "outlet",
                "medium",
                "classification_status",
                "location",
                "source_url",
                "source_name",
                "source_domain",
                "source_page_id",
                "source_revision_id",
                "source_revision_timestamp",
                "source_content_hash",
                "source_present",
                "source_updated_at",
                "transcript_status",
            ]
        )
        return "created" if created else "updated" if changed else "unchanged"

    def _get_or_create_interview(self, page: ParsedPage) -> tuple[Interview, bool]:
        interview = None
        if page.page_id is not None:
            interview = Interview.objects.filter(source_page_id=page.page_id).first()
        if interview is None:
            interview = Interview.objects.filter(source_url=page.source_url).first()
        if interview is not None:
            return interview, False

        title_data = title_metadata(page.title)
        return (
            Interview.objects.create(
                title=page.title,
                slug=unique_slug(page.title, page.page_id),
                date_year=title_data["date_year"],
                date_month=title_data["date_month"],
                date_day=title_data["date_day"],
                date_precision=title_data["date_precision"],
                outlet=title_data["outlet"],
                medium=infer_medium(page),
                classification_status=(
                    Interview.ClassificationStatus.INTERVIEW
                    if page.is_interview
                    else Interview.ClassificationStatus.NEEDS_REVIEW
                ),
                location=title_data["location"],
                source_url=page.source_url,
                source_page_id=page.page_id,
            ),
            True,
        )

    def _update_interview(self, interview: Interview, page: ParsedPage, content_hash: str):
        title_data = title_metadata(page.title)
        interview.title = page.title
        interview.slug = interview.slug or unique_slug(page.title, page.page_id)
        interview.date_year = title_data["date_year"]
        interview.date_month = title_data["date_month"]
        interview.date_day = title_data["date_day"]
        interview.date_precision = title_data["date_precision"]
        interview.outlet = title_data["outlet"]
        interview.medium = infer_medium(page)
        interview.location = title_data["location"]
        interview.source_url = page.source_url
        interview.source_name = "DM Live Wiki"
        interview.source_domain = "dmlive.wiki"
        interview.source_page_id = page.page_id
        interview.source_revision_id = page.revision_id
        interview.source_revision_timestamp = page.revision_timestamp
        interview.source_updated_at = page.revision_timestamp
        interview.source_content_hash = content_hash
        interview.source_present = True
        if interview.classification_status == Interview.ClassificationStatus.INTERVIEW:
            if not page.is_interview:
                interview.classification_status = Interview.ClassificationStatus.NEEDS_REVIEW
        elif page.is_interview and interview.classification_status == Interview.ClassificationStatus.NEEDS_REVIEW:
            interview.classification_status = Interview.ClassificationStatus.INTERVIEW

    def _sync_participants(self, interview: Interview, page: ParsedPage):
        names = participant_names(page)
        for sort_order, name in enumerate(names):
            person, _ = Person.objects.get_or_create(
                name=name,
                defaults={"slug": unique_person_slug(name), "role": "speaker"},
            )
            InterviewParticipant.objects.update_or_create(
                interview=interview,
                person=person,
                defaults={"role": "speaker", "sort_order": sort_order},
            )

    def _sync_transcript(self, interview: Interview, page: ParsedPage, summary: ImportSummary):
        transcript, _ = Transcript.objects.get_or_create(interview=interview)
        has_verified_links = InterviewEntityLink.objects.filter(
            interview=interview,
            review_status=InterviewEntityLink.ReviewStatus.VERIFIED,
        ).exists()
        if has_verified_links and interview.source_content_hash:
            interview.transcript_status = Interview.TranscriptStatus.NEEDS_REVIEW
            InterviewEntityLink.objects.filter(
                interview=interview,
                review_status=InterviewEntityLink.ReviewStatus.VERIFIED,
            ).update(review_status=InterviewEntityLink.ReviewStatus.NEEDS_REVIEW)
            return

        transcript.sections.all().delete()
        section_rows = [
            TranscriptSection(
                transcript=transcript,
                order=parsed_section.order,
                heading=parsed_section.heading,
                level=parsed_section.level,
                section_type=parsed_section.section_type,
                source_anchor=parsed_section.source_anchor,
            )
            for parsed_section in page.sections
        ]
        TranscriptSection.objects.bulk_create(section_rows)

        paragraph_rows = []
        has_transcript = False
        for parsed_section, section in zip(page.sections, section_rows):
            for paragraph in parsed_section.paragraphs:
                paragraph_rows.append(
                    TranscriptParagraph(
                        transcript=transcript,
                        section=section,
                        order=paragraph.order,
                        speaker=paragraph.speaker,
                        text=paragraph.text,
                    )
                )
            has_transcript = has_transcript or parsed_section.section_type == "transcript"
        TranscriptParagraph.objects.bulk_create(paragraph_rows)
        total_sections = len(section_rows)
        total_paragraphs = len(paragraph_rows)
        summary.sections_created += total_sections
        summary.paragraphs_created += total_paragraphs
        transcript.status = (
            Interview.TranscriptStatus.COMPLETE
            if has_transcript
            else Interview.TranscriptStatus.PARTIAL
            if total_paragraphs
            else Interview.TranscriptStatus.MISSING
        )
        transcript.save(update_fields=["status", "updated_at"])
        interview.transcript_status = transcript.status

    def _write_raw_snapshot(self, page: ParsedPage, content_hash: str) -> str:
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        page_key = str(page.page_id or slugify(page.title) or "page")
        snapshot_path = self.snapshot_dir / f"{page_key}-{content_hash}.wikitext"
        if not snapshot_path.exists():
            snapshot_path.write_text(page.text, encoding="utf-8")
        return str(snapshot_path)

    def _mark_missing(self, seen_page_ids: set[int], import_run: ImportRun) -> int:
        missing = Interview.objects.filter(source_domain="dmlive.wiki", source_present=True)
        if seen_page_ids:
            missing = missing.exclude(source_page_id__in=seen_page_ids)
        count = 0
        for interview in missing.iterator():
            interview.source_present = False
            interview.save(update_fields=["source_present", "updated_at"])
            SourceSnapshot.objects.create(
                interview=interview,
                import_run=import_run,
                source_url=interview.source_url,
                source_page_id=interview.source_page_id,
                source_revision_id=interview.source_revision_id,
                content_hash=interview.source_content_hash,
                status=SourceSnapshot.Status.MISSING,
                source_present=False,
            )
            count += 1
        return count

    @staticmethod
    def _select_format(path: Path, input_format: str) -> str:
        selected = input_format.lower()
        if selected == "auto":
            selected = "json" if path.suffix.lower() == ".json" else "xml"
        if selected not in {"xml", "json"}:
            raise DMLiveImportError(f"Unsupported input format: {input_format}")
        return selected

    @staticmethod
    def _count_dry_run(page: ParsedPage, summary: ImportSummary):
        summary.pages_imported += 1
        summary.sections_created += len(page.sections)
        summary.paragraphs_created += sum(len(section.paragraphs) for section in page.sections)
        if not page.is_interview:
            summary.pages_needs_review += 1


def title_metadata(title: str) -> dict:
    match = DATE_RE.match(title.strip())
    body = match.group("body") if match else title.strip()
    year = int(match.group("year")) if match else None
    month = _numeric_date_part(match.group("month")) if match else None
    day = _numeric_date_part(match.group("day")) if match else None
    precision = "day" if year and month and day else "month" if year and month else "year" if year else "unknown"
    parts = [part.strip() for part in body.split(",") if part.strip()]
    return {
        "date_year": year,
        "date_month": month,
        "date_day": day,
        "date_precision": precision,
        "outlet": parts[0] if parts else "",
        "location": ", ".join(parts[1:]),
    }


def _numeric_date_part(value: str | None) -> int | None:
    if not value or not value.isdigit():
        return None
    return int(value)


def infer_medium(page: ParsedPage) -> str:
    searchable = " ".join([page.title, *page.categories]).casefold()
    if "press conference" in searchable or "press conference" in page.title.casefold():
        return Interview.Medium.PRESS_CONFERENCE
    if "radio" in searchable or "fm" in searchable or "bbc" in searchable:
        return Interview.Medium.RADIO
    if any(token in searchable for token in ("television", " tv", "tv ", "tv,")):
        return Interview.Medium.TELEVISION
    if "magazine" in searchable:
        return Interview.Medium.MAGAZINE
    if "newspaper" in searchable or "press" in searchable:
        return Interview.Medium.NEWSPAPER
    if "online" in searchable or "web" in searchable:
        return Interview.Medium.ONLINE
    return Interview.Medium.UNKNOWN


def participant_names(page: ParsedPage) -> list[str]:
    candidates = list(page.speakers)
    for category in page.categories:
        match = re.match(r"Interviews featuring (.+)", category, re.IGNORECASE)
        if match:
            candidates.extend(re.split(r",|\band\b", match.group(1), flags=re.IGNORECASE))
    names = []
    for candidate in candidates:
        normalized = " ".join(candidate.split()).strip(" .")
        if not normalized or normalized.casefold() in IGNORED_SPEAKERS:
            continue
        canonical = KNOWN_PARTICIPANTS.get(normalized.casefold(), normalized)
        if canonical not in names:
            names.append(canonical)
    return names


def unique_slug(title: str, page_id: int | None) -> str:
    base = slugify(title)[:260] or "interview"
    candidate = base
    suffix = page_id or 2
    while Interview.objects.filter(slug=candidate).exclude(source_page_id=page_id).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate[:280]


def unique_slug_from_set(used_slugs: set[str], title: str, page_id: int | None) -> str:
    base = slugify(title)[:260] or "interview"
    candidate = base
    suffix = page_id or 2
    while candidate in used_slugs:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_slugs.add(candidate[:280])
    return candidate[:280]


def unique_person_slug(name: str) -> str:
    base = slugify(name) or "person"
    candidate = base
    suffix = 2
    while Person.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate[:180]


def unique_person_slug_from_set(used_slugs: set[str], name: str) -> str:
    base = slugify(name) or "person"
    candidate = base
    suffix = 2
    while candidate in used_slugs:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_slugs.add(candidate[:180])
    return candidate[:180]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

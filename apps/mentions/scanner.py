from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from django.conf import settings

from apps.catalog.models import Album, Song
from apps.catalog.normalization import normalize_catalog_value
from apps.interviews.models import Interview, SourceSnapshot
from apps.transcripts.models import TranscriptParagraph

from .models import InterviewEntityLink

EVIDENCE_MAX_CHARS = 280
SCANNABLE_SECTION_TYPES = {"transcript", "notes", "other"}
AMBIGUOUS_ALIASES = {
    "alone",
    "angel",
    "clean",
    "come back",
    "corrupt",
    "home",
    "insight",
    "one",
    "peace",
    "perfect",
    "rush",
    "shine",
    "slow",
    "wrong",
}
INTERNAL_LINK_RE = re.compile(r"\[\[([^|\]]+)(?:\|([^\]]+))?\]\]")


@dataclass(frozen=True)
class Target:
    kind: str
    entity: Song | Album
    alias: str
    is_title: bool


@dataclass(frozen=True)
class MentionCandidate:
    target: Target
    paragraph: TranscriptParagraph
    start: int
    end: int
    method: str
    confidence: float


@dataclass
class ScanSummary:
    interviews_scanned: int = 0
    paragraphs_scanned: int = 0
    candidates_found: int = 0
    suggestions_created: int = 0
    suggestions_updated: int = 0
    suggestions_existing: int = 0
    ambiguous_matches_skipped: int = 0
    conflicts_detected: int = 0
    interviews_failed: int = 0
    errors: list[str] | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def as_dict(self) -> dict:
        return asdict(self)


def scan_mentions(
    *, interview: Interview | None = None, dry_run: bool = False
) -> ScanSummary:
    summary = ScanSummary()
    targets = build_targets()
    candidates_to_persist = []
    if interview is not None:
        interviews = [interview]
        paragraphs_by_interview = {interview.pk: scannable_paragraphs(interview)}
        snapshots_by_interview = {
            interview.pk: interview.source_snapshots.order_by("-retrieved_at").first()
        }
    else:
        interviews = list(Interview.objects.filter(source_present=True))
        interview_ids = [current.pk for current in interviews]
        paragraphs_by_interview = defaultdict(list)
        for paragraph in (
            TranscriptParagraph.objects.filter(
                transcript__interview_id__in=interview_ids,
                section__section_type__in=SCANNABLE_SECTION_TYPES,
            )
            .select_related("section", "transcript")
            .order_by("transcript__interview_id", "section__order", "order")
        ):
            paragraphs_by_interview[paragraph.transcript.interview_id].append(paragraph)
        snapshots_by_interview = {}
        for snapshot in SourceSnapshot.objects.filter(
            interview_id__in=interview_ids
        ).order_by("interview_id", "-retrieved_at"):
            snapshots_by_interview.setdefault(snapshot.interview_id, snapshot)

    for current_interview in interviews:
        summary.interviews_scanned += 1
        paragraphs = paragraphs_by_interview.get(current_interview.pk, [])
        summary.paragraphs_scanned += len(paragraphs)
        try:
            explicit_links = explicit_links_for_interview(
                current_interview, snapshot=snapshots_by_interview.get(current_interview.pk)
            )
            candidates, skipped = find_candidates(paragraphs, targets, explicit_links)
        except (OSError, UnicodeError, ValueError) as exc:
            summary.interviews_failed += 1
            summary.errors.append(
                f"{current_interview.pk}:{current_interview.slug}: {type(exc).__name__}: {exc}"
            )
            continue
        summary.ambiguous_matches_skipped += skipped
        summary.conflicts_detected += skipped
        summary.candidates_found += len(candidates)
        if not dry_run:
            candidates_to_persist.extend(candidates)
    if not dry_run:
        created, updated, existing = persist_candidates(candidates_to_persist)
        summary.suggestions_created = created
        summary.suggestions_updated = updated
        summary.suggestions_existing = existing
    return summary


def build_targets() -> list[Target]:
    targets: list[Target] = []
    for album in Album.objects.prefetch_related("aliases").all():
        targets.append(Target("album", album, album.title, True))
        targets.extend(Target("album", album, alias.value, False) for alias in album.aliases.all())
    for song in Song.objects.prefetch_related("aliases").all():
        targets.append(Target("song", song, song.title, True))
        targets.extend(Target("song", song, alias.value, False) for alias in song.aliases.all())
    return targets


def scannable_paragraphs(interview: Interview) -> list[TranscriptParagraph]:
    return list(
        TranscriptParagraph.objects.filter(
            transcript__interview=interview,
            section__section_type__in=SCANNABLE_SECTION_TYPES,
        )
        .select_related("section", "transcript")
        .order_by("section__order", "order")
    )


def explicit_links_for_interview(
    interview: Interview, *, snapshot: SourceSnapshot | None = None
) -> list[tuple[str, str]]:
    if snapshot is None:
        snapshot = interview.source_snapshots.order_by("-retrieved_at").first()
    if not snapshot or not snapshot.snapshot_path:
        return []
    path = Path(snapshot.snapshot_path)
    if not path.is_absolute():
        path = settings.BASE_DIR / path
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    links = []
    for target, label in INTERNAL_LINK_RE.findall(text):
        normalized_target = target.split("#", 1)[0].strip()
        if normalized_target.casefold().startswith(("category:", "file:", "image:")):
            continue
        links.append((normalized_target, (label or normalized_target).strip()))
    return links


def find_candidates(
    paragraphs: list[TranscriptParagraph],
    targets: list[Target],
    explicit_links: list[tuple[str, str]],
) -> tuple[list[MentionCandidate], int]:
    candidates: dict[tuple[str, int, int, int, int], MentionCandidate] = {}
    skipped_ambiguous = 0
    target_index = build_target_index(targets)

    for paragraph in paragraphs:
        normalized_source = normalized_text_with_offsets(paragraph.text)
        for linked_target, linked_label in explicit_links:
            target = unique_target(
                target_index.get(normalize_catalog_value(linked_target), ())
            )
            if target is None:
                target = unique_target(
                    target_index.get(normalize_catalog_value(linked_label), ())
                )
            if target is None:
                continue
            for start, end in find_occurrences(
                paragraph.text, linked_label, normalized_source=normalized_source
            ):
                candidate = MentionCandidate(target, paragraph, start, end, "rules", 1.0)
                _keep_best(candidates, candidate)

        for normalized_alias, matching_targets in target_index.items():
            target = unique_target(matching_targets)
            if target is None:
                if find_occurrences(
                    paragraph.text, normalized_alias, normalized_source=normalized_source
                ):
                    skipped_ambiguous += 1
                continue
            if normalized_alias in AMBIGUOUS_ALIASES:
                if find_occurrences(
                    paragraph.text, normalized_alias, normalized_source=normalized_source
                ):
                    skipped_ambiguous += 1
                continue
            for start, end in find_occurrences(
                paragraph.text, normalized_alias, normalized_source=normalized_source
            ):
                confidence = 0.92 if target.is_title else 0.85
                candidate = MentionCandidate(target, paragraph, start, end, "rules", confidence)
                _keep_best(candidates, candidate)
    return list(candidates.values()), skipped_ambiguous


def build_target_index(targets: Iterable[Target]) -> dict[str, list[Target]]:
    """Index normalized titles and aliases without hiding collisions."""

    indexed: dict[str, dict[tuple[str, int], Target]] = defaultdict(dict)
    for target in targets:
        normalized_alias = normalize_catalog_value(target.alias)
        if not normalized_alias:
            continue
        key = (target.kind, target.entity.pk)
        previous = indexed[normalized_alias].get(key)
        if previous is None or target.is_title:
            indexed[normalized_alias][key] = target
    return {alias: list(entity_targets.values()) for alias, entity_targets in indexed.items()}


def unique_target(targets: Iterable[Target]) -> Target | None:
    targets = list(targets)
    return targets[0] if len(targets) == 1 else None


def persist_candidate(candidate: MentionCandidate) -> str:
    target_filter = {
        "interview": candidate.paragraph.transcript.interview,
        "paragraph": candidate.paragraph,
        "section": candidate.paragraph.section,
        "scope": InterviewEntityLink.Scope.PARAGRAPH,
        "start_offset": candidate.start,
        "end_offset": candidate.end,
    }
    target_filter["song" if candidate.target.kind == "song" else "album"] = candidate.target.entity
    existing = InterviewEntityLink.objects.filter(**target_filter).first()
    if existing is None:
        InterviewEntityLink.objects.create(
            **target_filter,
            method=InterviewEntityLink.Method.RULES,
            confidence=candidate.confidence,
            review_status=InterviewEntityLink.ReviewStatus.SUGGESTED,
            evidence=build_evidence(candidate.paragraph.text, candidate.start, candidate.end),
            paragraph_content_hash=hash_text(candidate.paragraph.text),
        )
        return "created"
    if existing.review_status != InterviewEntityLink.ReviewStatus.SUGGESTED:
        return "existing"
    existing.method = candidate.method
    existing.confidence = candidate.confidence
    existing.evidence = build_evidence(candidate.paragraph.text, candidate.start, candidate.end)
    existing.paragraph_content_hash = hash_text(candidate.paragraph.text)
    existing.save(update_fields=["method", "confidence", "evidence", "paragraph_content_hash", "updated_at"])
    return "updated"


def persist_candidates(candidates: list[MentionCandidate]) -> tuple[int, int, int]:
    if not candidates:
        return 0, 0, 0

    interview_ids = {candidate.paragraph.transcript.interview_id for candidate in candidates}
    existing_links = InterviewEntityLink.objects.filter(interview_id__in=interview_ids)
    existing_by_key = {
        link_key(link): link
        for link in existing_links
    }
    new_links = []
    updated_links = []
    created = updated = existing = 0
    for candidate in candidates:
        key = candidate_key(candidate)
        link = existing_by_key.get(key)
        if link is None:
            link = InterviewEntityLink(
                interview=candidate.paragraph.transcript.interview,
                paragraph=candidate.paragraph,
                section=candidate.paragraph.section,
                scope=InterviewEntityLink.Scope.PARAGRAPH,
                method=InterviewEntityLink.Method.RULES,
                confidence=candidate.confidence,
                review_status=InterviewEntityLink.ReviewStatus.SUGGESTED,
                start_offset=candidate.start,
                end_offset=candidate.end,
                evidence=build_evidence(candidate.paragraph.text, candidate.start, candidate.end),
                paragraph_content_hash=hash_text(candidate.paragraph.text),
            )
            if candidate.target.kind == "song":
                link.song = candidate.target.entity
            else:
                link.album = candidate.target.entity
            new_links.append(link)
            existing_by_key[key] = link
            created += 1
        elif link.review_status != InterviewEntityLink.ReviewStatus.SUGGESTED:
            existing += 1
        else:
            link.method = candidate.method
            link.confidence = candidate.confidence
            link.evidence = build_evidence(candidate.paragraph.text, candidate.start, candidate.end)
            link.paragraph_content_hash = hash_text(candidate.paragraph.text)
            updated_links.append(link)
            updated += 1
    InterviewEntityLink.objects.bulk_create(new_links)
    InterviewEntityLink.objects.bulk_update(
        updated_links,
        ["method", "confidence", "evidence", "paragraph_content_hash", "updated_at"],
    )
    return created, updated, existing


def candidate_key(candidate: MentionCandidate) -> tuple:
    return (
        candidate.paragraph.transcript.interview_id,
        candidate.target.kind,
        candidate.target.entity.pk,
        candidate.paragraph.pk,
        candidate.paragraph.section_id,
        InterviewEntityLink.Scope.PARAGRAPH,
        candidate.start,
        candidate.end,
    )


def link_key(link: InterviewEntityLink) -> tuple:
    return (
        link.interview_id,
        "song" if link.song_id else "album",
        link.song_id or link.album_id,
        link.paragraph_id,
        link.section_id,
        link.scope,
        link.start_offset,
        link.end_offset,
    )


def build_evidence(text: str, start: int, end: int, max_chars: int = EVIDENCE_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    half_window = max_chars // 2
    left = max(0, start - half_window)
    right = min(len(text), end + half_window)
    evidence = text[left:right]
    if left > 0:
        evidence = "…" + evidence
    if right < len(text):
        evidence += "…"
    return evidence[:max_chars]


def find_occurrences(
    text: str,
    alias: str,
    *,
    normalized_source: tuple[str, list[int]] | None = None,
) -> list[tuple[int, int]]:
    if not alias.strip():
        return []
    pattern = re.escape(normalize_catalog_value(alias)).replace(r"\ ", r"\s+")
    normalized_text, offsets = normalized_source or normalized_text_with_offsets(text)
    if not pattern or not normalized_text:
        return []
    return [
        (offsets[match.start()], offsets[match.end() - 1] + 1)
        for match in re.finditer(rf"(?<!\w){pattern}(?!\w)", normalized_text)
    ]


def normalized_text_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalize text for matching while retaining source offsets for citations."""

    normalized_chars: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(text):
        normalized = normalize_catalog_value(character)
        if character == "&":
            normalized = "and"
        elif not normalized:
            normalized = " "
        for normalized_character in normalized:
            normalized_chars.append(normalized_character)
            offsets.append(index)

    collapsed_chars: list[str] = []
    collapsed_offsets: list[int] = []
    previous_was_space = False
    for character, offset in zip(normalized_chars, offsets):
        if character == " ":
            if previous_was_space:
                continue
            previous_was_space = True
        else:
            previous_was_space = False
        collapsed_chars.append(character)
        collapsed_offsets.append(offset)
    while collapsed_chars and collapsed_chars[0] == " ":
        collapsed_chars.pop(0)
        collapsed_offsets.pop(0)
    while collapsed_chars and collapsed_chars[-1] == " ":
        collapsed_chars.pop()
        collapsed_offsets.pop()
    return "".join(collapsed_chars), collapsed_offsets


def _keep_best(
    candidates: dict[tuple[str, int, int, int, int], MentionCandidate],
    candidate: MentionCandidate,
):
    key = (
        candidate.target.kind,
        candidate.target.entity.pk,
        candidate.paragraph.pk,
        candidate.start,
        candidate.end,
    )
    previous = candidates.get(key)
    if previous is None or candidate.confidence > previous.confidence:
        candidates[key] = candidate


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

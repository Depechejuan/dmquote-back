from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from apps.catalog.models import Album, Song
from apps.catalog.normalization import normalize_catalog_value
from apps.interviews.models import Interview
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


def scan_mentions(
    *, interview: Interview | None = None, dry_run: bool = False
) -> ScanSummary:
    summary = ScanSummary()
    targets = build_targets()
    interviews = (
        Interview.objects.filter(pk=interview.pk)
        if interview is not None
        else Interview.objects.filter(source_present=True)
    )
    for current_interview in interviews.iterator():
        summary.interviews_scanned += 1
        paragraphs = scannable_paragraphs(current_interview)
        summary.paragraphs_scanned += len(paragraphs)
        explicit_links = explicit_links_for_interview(current_interview)
        candidates, skipped = find_candidates(paragraphs, targets, explicit_links)
        summary.ambiguous_matches_skipped += skipped
        summary.candidates_found += len(candidates)
        if not dry_run:
            for candidate in candidates:
                result = persist_candidate(candidate)
                if result == "created":
                    summary.suggestions_created += 1
                elif result == "updated":
                    summary.suggestions_updated += 1
                else:
                    summary.suggestions_existing += 1
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


def explicit_links_for_interview(interview: Interview) -> list[tuple[str, str]]:
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
    normalized_targets = {
        normalize_catalog_value(target.alias): target for target in targets if target.alias
    }

    for paragraph in paragraphs:
        for linked_target, linked_label in explicit_links:
            normalized_target = normalize_catalog_value(linked_target)
            target = normalized_targets.get(normalized_target)
            if target is None:
                target = normalized_targets.get(normalize_catalog_value(linked_label))
            if target is None:
                continue
            for start, end in find_occurrences(paragraph.text, linked_label):
                candidate = MentionCandidate(target, paragraph, start, end, "rules", 1.0)
                _keep_best(candidates, candidate)

        for target in targets:
            normalized_alias = normalize_catalog_value(target.alias)
            if normalized_alias in AMBIGUOUS_ALIASES:
                skipped_ambiguous += 1
                continue
            for start, end in find_occurrences(paragraph.text, target.alias):
                confidence = 0.92 if target.is_title else 0.85
                candidate = MentionCandidate(target, paragraph, start, end, "rules", confidence)
                _keep_best(candidates, candidate)
    return list(candidates.values()), skipped_ambiguous


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


def find_occurrences(text: str, alias: str) -> list[tuple[int, int]]:
    if not alias.strip():
        return []
    pattern = re.escape(alias.strip()).replace(r"\ ", r"\s+")
    return [
        match.span()
        for match in re.finditer(rf"(?<!\w){pattern}(?!\w)", text, flags=re.IGNORECASE)
    ]


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

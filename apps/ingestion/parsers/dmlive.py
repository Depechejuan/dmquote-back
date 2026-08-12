from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree

from apps.interviews.source_urls import build_dmlive_url

_HEADING_RE = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$")
_SPEAKER_RE = re.compile(r"^([^:\n]{1,160}):\s+(.*)$")
_CATEGORY_RE = re.compile(r"\[\[\s*Category\s*:\s*([^|\]]+)", re.IGNORECASE)
_INTERNAL_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_EXTERNAL_LINK_RE = re.compile(r"\[([^\s\]]+)(?:\s+([^\]]+))?\]")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_TAG_RE = re.compile(r"<[^>]+>")
_TRANSLATION_NOTICE_RE = re.compile(
    r"\{\{\s*Translation\s+notice\s*\|\s*([^}|]+)", re.IGNORECASE
)
_TRANSCRIPT_HEADING_LANGUAGE_RE = re.compile(
    r"^transcript\s*\(([^)]+)\)\s*$", re.IGNORECASE
)

_LANGUAGE_NAMES = {
    "english": "en",
    "español": "es",
    "french": "fr",
    "français": "fr",
    "german": "de",
    "deutsch": "de",
    "italian": "it",
    "portuguese": "pt",
    "spanish": "es",
}


@dataclass(frozen=True)
class ParsedParagraph:
    order: int
    speaker: str
    text: str


@dataclass(frozen=True)
class ParsedSection:
    order: int
    heading: str
    level: int
    section_type: str
    source_anchor: str
    paragraphs: tuple[ParsedParagraph, ...]


@dataclass(frozen=True)
class ParsedPage:
    page_id: int | None
    namespace: int
    revision_id: int | None
    revision_timestamp: datetime | None
    title: str
    text: str
    categories: tuple[str, ...]
    sections: tuple[ParsedSection, ...]
    transcript_language: str | None = None

    @property
    def speakers(self) -> tuple[str, ...]:
        names = []
        for section in self.sections:
            for paragraph in section.paragraphs:
                if paragraph.speaker and paragraph.speaker not in names:
                    names.append(paragraph.speaker)
        return tuple(names)

    @property
    def is_interview(self) -> bool:
        return any(category.casefold() == "interviews" for category in self.categories)

    @property
    def source_url(self) -> str:
        return build_dmlive_url(self.title)


def parse_source_file(path: str | Path, input_format: str = "auto") -> Iterator[ParsedPage]:
    source_path = Path(path)
    selected_format = input_format.lower()
    if selected_format == "auto":
        selected_format = "json" if source_path.suffix.lower() == ".json" else "xml"
    if selected_format == "xml":
        yield from _parse_xml(source_path)
        return
    if selected_format == "json":
        yield from _parse_json(source_path)
        return
    raise ValueError(f"Unsupported input format: {input_format}")


def _parse_xml(path: Path) -> Iterator[ParsedPage]:
    for _, page_element in ElementTree.iterparse(path, events=("end",)):
        if _local_name(page_element.tag) != "page":
            continue
        yield _parse_xml_page(page_element)
        page_element.clear()


def _parse_xml_page(page_element: ElementTree.Element) -> ParsedPage:
    title = _child_text(page_element, "title") or ""
    namespace = int(_child_text(page_element, "ns") or 0)
    page_id = _as_int(_child_text(page_element, "id"))
    revision = _first_child(page_element, "revision")
    revision_id = _as_int(_child_text(revision, "id")) if revision is not None else None
    revision_timestamp = (
        _parse_timestamp(_child_text(revision, "timestamp")) if revision is not None else None
    )
    text = _child_text(revision, "text") if revision is not None else ""
    return _build_page(
        page_id=page_id,
        namespace=namespace,
        revision_id=revision_id,
        revision_timestamp=revision_timestamp,
        title=title,
        text=text or "",
    )


def _parse_json(path: Path) -> Iterator[ParsedPage]:
    with path.open("r", encoding="utf-8") as input_file:
        payload = json.load(input_file)
    pages = payload.get("pages", payload) if isinstance(payload, dict) else payload
    if not isinstance(pages, list):
        raise ValueError("JSON input must be a list or an object containing a 'pages' list")

    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("Each JSON page must be an object")
        revision = page.get("revision") or {}
        if isinstance(revision, list):
            revision = revision[0] if revision else {}
        text = page.get("text", revision.get("text", ""))
        yield _build_page(
            page_id=_as_int(page.get("page_id", page.get("pageid", page.get("id")))),
            namespace=int(page.get("namespace", page.get("ns", 0)) or 0),
            revision_id=_as_int(
                page.get("revision_id", page.get("revid", revision.get("revision_id", revision.get("id"))))
            ),
            revision_timestamp=_parse_timestamp(
                page.get("revision_timestamp", page.get("timestamp", revision.get("timestamp")))
            ),
            title=str(page.get("title", "")),
            text=str(text or ""),
        )


def _build_page(
    *,
    page_id: int | None,
    namespace: int,
    revision_id: int | None,
    revision_timestamp: datetime | None,
    title: str,
    text: str,
) -> ParsedPage:
    categories = tuple(dict.fromkeys(category.strip() for category in _CATEGORY_RE.findall(text)))
    sections = tuple(parse_wikitext_sections(text))
    return ParsedPage(
        page_id=page_id,
        namespace=namespace,
        revision_id=revision_id,
        revision_timestamp=revision_timestamp,
        title=title.strip(),
        text=text,
        categories=categories,
        sections=sections,
        transcript_language=detect_transcript_language(text, sections),
    )


def detect_transcript_language(
    text: str, sections: tuple[ParsedSection, ...] | list[ParsedSection] | None = None
) -> str | None:
    """Read an explicitly declared transcript language from DM Live wikitext."""

    notice = _TRANSLATION_NOTICE_RE.search(text)
    if notice:
        language = normalize_language_name(notice.group(1))
        if language:
            return language

    for section in sections or ():
        heading_match = _TRANSCRIPT_HEADING_LANGUAGE_RE.fullmatch(section.heading.strip())
        if heading_match:
            language = normalize_language_name(heading_match.group(1))
            if language:
                return language
    return None


def normalize_language_name(value: str) -> str | None:
    normalized = re.sub(r"\s+", " ", value.strip().casefold())
    if normalized in _LANGUAGE_NAMES:
        return _LANGUAGE_NAMES[normalized]
    if re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2,4})?", normalized):
        return normalized
    return None


def parse_wikitext_sections(text: str) -> list[ParsedSection]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    raw_sections: list[tuple[str, int, list[str]]] = []
    current_heading = "Overview"
    current_level = 2
    current_lines: list[str] = []

    for line in lines:
        match = _HEADING_RE.match(line.strip())
        if match:
            if _has_content(current_lines):
                raw_sections.append((current_heading, current_level, current_lines))
            current_heading = match.group(2).strip() or "Untitled section"
            current_level = len(match.group(1))
            current_lines = []
        else:
            current_lines.append(line)
    if _has_content(current_lines):
        raw_sections.append((current_heading, current_level, current_lines))

    sections = []
    for order, (heading, level, section_lines) in enumerate(raw_sections, start=1):
        section_type = classify_section_type(heading)
        paragraphs = parse_wikitext_paragraphs("\n".join(section_lines), section_type)
        if not paragraphs:
            continue
        sections.append(
            ParsedSection(
                order=order,
                heading=heading,
                level=level,
                section_type=section_type,
                source_anchor=slugify_heading(heading),
                paragraphs=tuple(paragraphs),
            )
        )
    return sections


def parse_wikitext_paragraphs(text: str, section_type: str) -> list[ParsedParagraph]:
    cleaned = clean_wikitext(text)
    blocks = [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]
    paragraphs: list[ParsedParagraph] = []

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if section_type == "transcript":
            paragraphs.extend(_split_transcript_lines(lines))
            continue
        speaker, paragraph_text = _split_speaker(lines)
        if paragraph_text:
            paragraphs.append(
                ParsedParagraph(order=len(paragraphs) + 1, speaker=speaker, text=paragraph_text)
            )
    return [
        ParsedParagraph(order=order, speaker=paragraph.speaker, text=paragraph.text)
        for order, paragraph in enumerate(paragraphs, start=1)
    ]


def clean_wikitext(text: str) -> str:
    cleaned = _COMMENT_RE.sub("", text)
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _TEMPLATE_RE.sub("", cleaned)
    cleaned = _CATEGORY_RE.sub("", cleaned)
    cleaned = _INTERNAL_LINK_RE.sub(
        lambda match: (match.group(2) or match.group(1)).split("#", 1)[-1], cleaned
    )
    cleaned = _EXTERNAL_LINK_RE.sub(
        lambda match: (
            f"{match.group(2).strip()} ({match.group(1)})"
            if match.group(2)
            else match.group(1)
        ),
        cleaned,
    )
    cleaned = re.sub(r"'{2,5}", "", cleaned)
    cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = _TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"^\s*[*#;:]+\s?", "", cleaned, flags=re.MULTILINE)
    cleaned = html.unescape(cleaned)
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip()


def classify_section_type(heading: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", heading.casefold()).strip()
    if "source" in normalized or "reference" in normalized:
        return "sources"
    if "transcript" in normalized or "interview" in normalized:
        return "transcript"
    if "track" in normalized or "set list" in normalized or "setlist" in normalized:
        return "tracklist"
    if "audio" in normalized or "download" in normalized:
        return "audio"
    if "video" in normalized:
        return "video"
    if "note" in normalized:
        return "notes"
    return "other"


def slugify_heading(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.casefold()).strip("-")
    return value[:180]


def _split_transcript_lines(lines: list[str]) -> list[ParsedParagraph]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if _SPEAKER_RE.match(line) and current:
            chunks.append(current)
            current = []
        current.append(line)
    if current:
        chunks.append(current)

    paragraphs = []
    for chunk in chunks:
        speaker, paragraph_text = _split_speaker(chunk)
        if paragraph_text:
            paragraphs.append(
                ParsedParagraph(order=len(paragraphs) + 1, speaker=speaker, text=paragraph_text)
            )
    return paragraphs


def _split_speaker(lines: list[str]) -> tuple[str, str]:
    if not lines:
        return "", ""
    match = _SPEAKER_RE.match(lines[0])
    if not match:
        return "", "\n".join(lines).strip()
    speaker = match.group(1).strip()
    text = "\n".join([match.group(2).strip(), *lines[1:]]).strip()
    return speaker, text


def _has_content(lines: list[str]) -> bool:
    return bool(clean_wikitext("\n".join(lines)))


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _first_child(element: ElementTree.Element | None, name: str):
    if element is None:
        return None
    return next((child for child in element if _local_name(child.tag) == name), None)


def _child_text(element: ElementTree.Element | None, name: str) -> str | None:
    child = _first_child(element, name)
    return child.text if child is not None else None


def _as_int(value) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _parse_timestamp(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

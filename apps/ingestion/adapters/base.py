from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SourceInterviewReference:
    title: str
    source_url: str
    year: int | None = None


class SourceAdapter(Protocol):
    def discover_interviews(self, *, year: int | None = None) -> list[SourceInterviewReference]: ...

    def fetch_interview(self, source_url: str) -> str: ...

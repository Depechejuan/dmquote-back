from django.conf import settings


class DMLiveAdapter:
    """Placeholder adapter. Network access is disabled until explicit permission."""

    def __init__(self) -> None:
        if not settings.DMLIVE_IMPORT_ENABLED:
            raise RuntimeError(
                "DM Live import is disabled. Set DMLIVE_IMPORT_ENABLED=true only after permission."
            )

    def discover_interviews(self, *, year: int | None = None):
        raise NotImplementedError("DM Live discovery will be implemented after permission.")

    def fetch_interview(self, source_url: str) -> str:
        raise NotImplementedError("DM Live fetching will be implemented after permission.")

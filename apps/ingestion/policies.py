import time


class RequestPolicy:
    """Conservative policy for an explicitly authorised source import."""

    def __init__(self, delay_seconds: float = 15.0) -> None:
        self.delay_seconds = max(delay_seconds, 0.0)
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.delay_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def mark_request(self) -> None:
        self._last_request_at = time.monotonic()

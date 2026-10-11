import hashlib
import math
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic

from app.common.config import settings
from app.common.errors import AppError


@dataclass
class Window:
    seconds: int
    timestamps: deque[float] = field(default_factory=deque)
    in_flight: int = 0


class RateLimiter:
    """Thread-safe rolling windows for one Core process; shared storage is needed for multi-worker."""

    def __init__(self, clock: Callable[[], float] = monotonic):
        self.clock = clock
        self.windows: dict[str, Window] = {}
        self.lock = Lock()

    def _windows(self, names: list[str], limit: int, seconds: int) -> list[Window]:
        now = self.clock()
        for key, window in list(self.windows.items()):
            while window.timestamps and window.timestamps[0] <= now - window.seconds:
                window.timestamps.popleft()
            if not window.timestamps and not window.in_flight:
                del self.windows[key]
        missing = set(names) - self.windows.keys()
        if len(self.windows) + len(missing) > settings.auth_rate_limit_max_keys:
            raise AppError(503, "Rate limiter unavailable")
        windows = [self.windows.setdefault(name, Window(seconds)) for name in names]
        for window in windows:
            if len(window.timestamps) + window.in_flight >= limit:
                retry = (
                    max(1, math.ceil(window.timestamps[0] + seconds - now))
                    if (window.timestamps)
                    else 1
                )
                error = AppError(429)
                error.headers = {"Retry-After": str(retry)}
                raise error
        return windows

    def consume(self, operation: str, identity: str, limit: int, seconds: int) -> None:
        name = self._key(operation, identity)
        with self.lock:
            for window in self._windows([name], limit, seconds):
                window.timestamps.append(self.clock())

    @contextmanager
    def login_attempt(self, ip: str, email: str) -> Iterator[None]:
        names = [self._key("login_ip", ip), self._key("login_email", email)]
        with self.lock:
            windows = self._windows(
                names, settings.auth_login_max_failures, settings.auth_login_window_seconds
            )
            for window in windows:
                window.in_flight += 1
        failed = False
        try:
            yield
        except AppError as exc:
            failed = exc.status_code == 401
            raise
        finally:
            with self.lock:
                for window in windows:
                    window.in_flight -= 1
                    if failed:
                        window.timestamps.append(self.clock())

    @staticmethod
    def _key(operation: str, value: str) -> str:
        return operation + ":" + hashlib.sha256(value.encode()).hexdigest()


limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return limiter

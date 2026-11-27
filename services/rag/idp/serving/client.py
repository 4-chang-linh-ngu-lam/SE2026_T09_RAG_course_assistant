"""Origin allowlist, service-key auth headers, and thread-safe circuit breaker for remote serving."""

from __future__ import annotations

import http.client
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

SERVING_CLIENT_VERSION = "idp-serving-client-1"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class LocalRegionError(ValueError):
    """Error raised when remote model serving requests fail validation or limits."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CircuitOpenError(RuntimeError):
    """Raised immediately when a serving circuit breaker is open."""


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise LocalRegionError("ORIGIN", "local region reader does not follow redirects")


@dataclass(frozen=True)
class ServingConfig:
    """Configuration separating model serving from the default IDP worker process."""

    mode: Literal["remote", "auto", "in_process"] = "auto"
    allowed_hosts: tuple[str, ...] = ()
    service_key: str | None = None
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.mode not in {"remote", "auto", "in_process"}:
            raise ValueError("serving mode must be one of 'remote', 'auto', 'in_process'")
        if type(self.circuit_failure_threshold) is not int or self.circuit_failure_threshold < 1:
            raise ValueError("circuit_failure_threshold must be a positive integer")
        if self.circuit_cooldown_seconds <= 0:
            raise ValueError("circuit_cooldown_seconds must be positive")


class ModelOriginPolicy:
    """Validate remote serving endpoints (strict loopback by default, or explicit allowlist)."""

    def __init__(
        self,
        allowed_hosts: Iterable[str] = (),
        *,
        allow_https_for_allowed_hosts: bool = False,
    ) -> None:
        self.allowed_hosts = frozenset(
            h.strip().lower() for h in allowed_hosts if isinstance(h, str) and h.strip()
        )
        self.allow_https_for_allowed_hosts = bool(allow_https_for_allowed_hosts)

    def validate(self, base_url: str) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not host
        ):
            raise LocalRegionError(
                "ORIGIN", "local region URL must be a loopback HTTP server origin"
            )
        if host in LOOPBACK_HOSTS:
            if parsed.scheme != "http":
                raise LocalRegionError(
                    "ORIGIN", "local region URL must be a loopback HTTP server origin"
                )
            return
        if host in self.allowed_hosts:
            allowed_schemes = {"http", "https"} if self.allow_https_for_allowed_hosts else {"http"}
            if parsed.scheme not in allowed_schemes:
                raise LocalRegionError("ORIGIN", f"unsupported scheme for allowed model host {host!r}")
            return
        if not self.allowed_hosts:
            raise LocalRegionError(
                "ORIGIN", "local region URL must be a loopback HTTP server origin"
            )
        raise LocalRegionError(
            "ORIGIN", f"model serving host {host!r} is outside loopback and allowed_hosts"
        )


def require_serving_origin(base_url: str, *, allowed_hosts: Iterable[str] = ()) -> None:
    ModelOriginPolicy(allowed_hosts).validate(base_url)


def build_serving_headers(
    service_key: str | None = None,
    *,
    content_type: str | None = "application/json",
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    if service_key:
        headers["X-Model-Service-Key"] = service_key
    return headers


class ServingCircuitBreaker:
    """Thread-safe consecutive-failure circuit breaker for remote OCR/layout endpoints."""

    def __init__(self, *, failure_threshold: int = 3, cooldown_seconds: float = 30.0) -> None:
        if type(failure_threshold) is not int or failure_threshold < 1:
            raise ValueError("failure_threshold must be a positive integer")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = float(cooldown_seconds)
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._total_failures = 0
        self._total_short_circuits = 0
        self._opened_at: float | None = None
        self._last_error: str | None = None

    def allow_request(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.cooldown_seconds:
                # Allow a single half-open probe and slide cooldown while testing.
                self._opened_at = time.monotonic()
                return True
            self._total_short_circuits += 1
            return False

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._last_error = None

    def record_failure(self, reason: str = "serving_error") -> None:
        with self._lock:
            self._total_failures += 1
            self._consecutive_failures += 1
            self._last_error = str(reason)[:200]
            if self._consecutive_failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    def state(self) -> dict:
        with self._lock:
            if self._opened_at is None:
                status = "closed"
            elif time.monotonic() - self._opened_at >= self.cooldown_seconds:
                status = "half_open"
            else:
                status = "open"
            return {
                "status": status,
                "consecutive_failures": self._consecutive_failures,
                "total_failures": self._total_failures,
                "total_short_circuits": self._total_short_circuits,
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
                "last_error": self._last_error,
            }


_THREAD_LOCAL_CONNS = threading.local()


def _get_pooled_conn(
    scheme: str, host: str, port: int, timeout: float
) -> tuple[http.client.HTTPConnection, bool]:
    pool: dict[tuple[str, str, int], http.client.HTTPConnection] = getattr(
        _THREAD_LOCAL_CONNS, "conns", None
    )
    if pool is None:
        pool = {}
        _THREAD_LOCAL_CONNS.conns = pool
    key = (scheme, host, port)
    conn = pool.get(key)
    if conn is not None:
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        return conn, True
    cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    conn = cls(host, port, timeout=timeout)
    pool[key] = conn
    return conn, False


def _drop_pooled_conn(scheme: str, host: str, port: int) -> None:
    pool: dict[tuple[str, str, int], http.client.HTTPConnection] | None = getattr(
        _THREAD_LOCAL_CONNS, "conns", None
    )
    if pool is None:
        return
    conn = pool.pop((scheme, host, port), None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def post_json_keepalive(
    url: str,
    data: bytes,
    headers: dict[str, str],
    *,
    timeout: float,
    max_bytes: int,
) -> bytes:
    """Send an HTTP POST over a thread-local Keep-Alive connection (no redirects)."""
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname or ""
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    req_headers = {
        **headers,
        "Connection": "keep-alive",
        "Content-Length": str(len(data)),
    }

    for attempt in range(2):
        conn, reused = _get_pooled_conn(scheme, host, port, timeout)
        try:
            conn.request("POST", path, body=data, headers=req_headers)
            resp = conn.getresponse()
            raw = resp.read(max_bytes + 1)
            status = resp.status
            reason = resp.reason
            resp_headers = resp.headers
            if (resp_headers.get("Connection") or "").lower() == "close":
                _drop_pooled_conn(scheme, host, port)
        except (
            http.client.RemoteDisconnected,
            http.client.BadStatusLine,
            http.client.CannotSendRequest,
            http.client.ResponseNotReady,
            BrokenPipeError,
            ConnectionResetError,
            ConnectionAbortedError,
        ):
            _drop_pooled_conn(scheme, host, port)
            if reused and attempt == 0:
                continue
            raise
        except Exception:
            _drop_pooled_conn(scheme, host, port)
            raise

        if 300 <= status < 400:
            _drop_pooled_conn(scheme, host, port)
            raise LocalRegionError("ORIGIN", "local region reader does not follow redirects")
        if status >= 400:
            raise urllib.error.HTTPError(url, status, reason, resp_headers, None)
        return raw

    raise RuntimeError("unreachable keep-alive retry state")

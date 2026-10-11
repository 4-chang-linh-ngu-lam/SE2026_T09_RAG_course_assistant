from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Header, Request

from app.common.config import settings
from app.common.errors import AppError

REFRESH_COOKIE = "refresh_token"
COOKIE_PATH = "/api/v1/auth"


def _origin(value: str, *, referer: bool = False) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or (not referer and (parsed.path or parsed.query or parsed.fragment))
        ):
            return None
        return (
            parsed.scheme,
            parsed.hostname.lower(),
            parsed.port or (443 if parsed.scheme == "https" else 80),
        )
    except ValueError:
        return None


def verify_cookie_origin(
    request: Request,
    origin: Annotated[str | None, Header()] = None,
    referer: Annotated[str | None, Header()] = None,
) -> None:
    origin = request.headers.get("origin") if origin is None else origin
    candidate = (
        _origin(origin)
        if origin is not None
        else _origin(referer or request.headers.get("referer", ""), referer=True)
    )
    allowed = {_origin(value) for value in settings.cors_origins}
    if candidate is None or candidate not in allowed:
        raise AppError(403, "Invalid request origin")


def client_identity(request: Request) -> str:
    # Forwarded headers are attacker-controlled unless a trusted proxy verifies them.
    return request.client.host if request.client else "unknown"

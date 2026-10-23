import base64
import hashlib
import hmac
import ipaddress
import json
import re
import time
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
    # Ordinary forwarded headers remain attacker-controlled. Only the dedicated
    # browser-facing Node listener can attest the socket peer for this request.
    values = request.headers.getlist("x-lumi-client-context")
    if not values:
        return request.client.host if request.client else "unknown"
    secret = settings.core_proxy_secret
    if secret is None:
        raise AppError(503, "Proxy identity verification unavailable")
    try:
        if len(values) != 1 or len(values[0]) > 1024:
            raise ValueError
        payload, signature = values[0].split(".")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", payload) or not re.fullmatch(
            r"[a-f0-9]{64}", signature
        ):
            raise ValueError
        expected = hmac.new(
            secret.get_secret_value().encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        claim = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if (
            type(claim.get("v")) is not int
            or claim["v"] != 1
            or type(claim.get("at")) is not int
            or abs(int(time.time()) - claim["at"]) > 30
            or claim.get("method") != request.method
            or claim.get("path") != request.url.path
            or not isinstance(claim.get("ip"), str)
            or "%" in claim["ip"]
        ):
            raise ValueError
        address = ipaddress.ip_address(claim["ip"])
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return str(address)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise AppError(403, "Invalid proxy identity") from None

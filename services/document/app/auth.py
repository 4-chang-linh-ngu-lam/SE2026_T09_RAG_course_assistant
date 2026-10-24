import hmac
import json
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.request import Request as HTTPRequest
from uuid import UUID

from fastapi import Request

from app.config import settings
from app.errors import DocumentError, denied


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CoreGateway:
    def request(self, path: str, *, bearer: str | None = None, body=None, event=False):
        headers = {"Accept": "application/json"}
        if bearer:
            headers["Authorization"] = bearer
        key = settings.document_events_service_secret if event else settings.internal_service_secret
        if path.startswith("/internal/"):
            if key is None:
                raise DocumentError(503, "CORE_UNAVAILABLE", "Chưa cấu hình kết nối quyền Core.")
            headers["X-Service-Key"] = key.get_secret_value()
        data = None if body is None else json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = HTTPRequest(settings.core_api_url + path, data=data, headers=headers)
        try:
            with build_opener(NoRedirect()).open(
                request, timeout=settings.core_timeout_seconds
            ) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise ValueError("Core response exceeded bound")
                return json.loads(raw)
        except HTTPError as error:
            if error.code == 401 and not path.startswith("/internal/"):
                raise DocumentError(401, "UNAUTHENTICATED", "Phiên đăng nhập không còn hiệu lực.")
            if error.code == 403 and not path.startswith("/internal/"):
                denied()
            raise DocumentError(503, "CORE_UNAVAILABLE", "Chưa kiểm tra được quyền từ Core.")
        except (URLError, TimeoutError, OSError, ValueError):
            raise DocumentError(503, "CORE_UNAVAILABLE", "Chưa kết nối được Core.")


@dataclass(frozen=True)
class Actor:
    id: UUID
    school_id: UUID
    roles: tuple[str, ...]
    display_name: str


@dataclass
class AccessContext:
    actor: Actor
    bearer: str
    gateway: CoreGateway
    # Request-local only. Never authorizes a different HTTP request.
    checked: dict = field(default_factory=dict)

    def class_name(self, class_id: UUID) -> str:
        payload = self.gateway.request(f"/api/v1/classes/{class_id}", bearer=self.bearer)
        if (
            not isinstance(payload, dict)
            or payload.get("id") != str(class_id)
            or payload.get("school_id") != str(self.actor.school_id)
            or not isinstance(payload.get("name"), str)
            or not 1 <= len(payload["name"]) <= 200
        ):
            raise DocumentError(503, "INVALID_CORE_RESPONSE", "Invalid authorized class context")
        return payload["name"]

    def class_access(self, class_id: UUID, action="read_document_source", *, fresh=False):
        key = (class_id, action)
        if fresh or key not in self.checked:
            payload = self.gateway.request(
                f"/internal/v1/classes/{class_id}/access?"
                + urlencode({"user_id": str(self.actor.id), "action": action}),
                bearer=self.bearer,
            )
            if (
                not isinstance(payload, dict)
                or payload.get("class_id") != str(class_id)
                or payload.get("user_id") != str(self.actor.id)
                or payload.get("action") != action
                or not isinstance(payload.get("allowed"), bool)
            ):
                raise DocumentError(503, "INVALID_CORE_RESPONSE", "Phản hồi quyền chưa hợp lệ.")
            if payload["allowed"] and (
                payload.get("school_id") != str(self.actor.school_id)
                or payload.get("class_status") not in {"ACTIVE", "ARCHIVED"}
            ):
                denied()
            self.checked[key] = payload
        return self.checked[key]


def get_access(request: Request) -> AccessContext:
    verified = getattr(request.state, "document_access", None)
    if verified is not None and request.method == "GET":
        return verified
    bearer = request.headers.get("Authorization", "")
    if not bearer.startswith("Bearer ") or len(bearer) > 4096:
        raise DocumentError(401, "UNAUTHENTICATED", "Vui lòng đăng nhập.")
    gateway = request.app.state.core
    payload = gateway.request("/api/v1/users/me", bearer=bearer)
    try:
        if payload["status"] != "ACTIVE" or not isinstance(payload["roles"], list):
            denied()
        roles = tuple(payload["roles"])
        if not roles or any(role not in {"ADMIN", "LECTURER", "STUDENT"} for role in roles):
            denied()
        actor = Actor(
            UUID(payload["id"]),
            UUID(payload["school_id"]),
            roles,
            str(payload.get("display_name") or payload["id"])[:200],
        )
    except (ValueError, TypeError, KeyError):
        raise DocumentError(503, "INVALID_CORE_RESPONSE", "Chưa xác minh được tài khoản.")
    return AccessContext(actor, bearer, gateway)


def require_service(request: Request, event_reader=False):
    key = (
        settings.document_event_reader_secret
        if event_reader
        else settings.document_internal_service_secret
    )
    actual = request.headers.get("X-Service-Key", "")
    if (
        key is None
        or not actual
        or len(actual) > 512
        or not hmac.compare_digest(actual.encode(), key.get_secret_value().encode())
    ):
        denied()

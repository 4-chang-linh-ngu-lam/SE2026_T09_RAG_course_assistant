from __future__ import annotations

import json
import time
from types import SimpleNamespace
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from app.common.config import settings
from app.common.errors import register_error_handlers
from app.common.security import create_access_token
from app.common.service_jwt import issue_service_jwt
from app.modules.classroom import public
from app.modules.classroom import router as classroom_router
from app.modules.classroom.authorization import CALLER_ALLOWED_ACTIONS, service_may_authorize
from app.modules.classroom.models import ClassStatus, TeachingRole
from app.modules.classroom.router import internal_router
from app.modules.classroom.schemas import (
    AuthorizationAction,
    ClassAccessAction,
    ClassAccessDTO,
)
from app.modules.identity.schemas import UserSummaryDTO

ISSUER = "https://issuer.example.invalid/document"
SERVICE_ID = "document"
AUDIENCE = "core"
KEY_ID = "document-key-1"
INTERNAL_SECRET = "test-internal-service-secret-" + "x" * 32
REQUIRED_SCOPE = "core:check_access"
ISSUED_SCOPES = [REQUIRED_SCOPE, "core:read"]


def _key_pair(tmp_path):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / "service-private.pem"
    public_path = tmp_path / "service-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_key, private_path, public_path


def _claims(**changes):
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "sub": SERVICE_ID,
        "aud": AUDIENCE,
        "scope": [REQUIRED_SCOPE],
        "token_type": "service",
        "iat": now,
        "exp": now + 300,
    }
    payload.update(changes)
    return payload


def _sign(payload, private_key, kid=KEY_ID):
    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": kid, "typ": "JWT"},
    )


@pytest.fixture
def auth_setup(tmp_path, monkeypatch):
    private_key, private_path, public_path = _key_pair(tmp_path)
    trust = {
        KEY_ID: {
            "issuer": ISSUER,
            "subject": SERVICE_ID,
            "public_key_file": str(public_path),
            "audiences": [AUDIENCE],
            "scopes": ISSUED_SCOPES,
        }
    }
    monkeypatch.setattr(settings, "service_jwt_identity", SERVICE_ID)
    monkeypatch.setattr(settings, "service_jwt_issuer", ISSUER)
    monkeypatch.setattr(settings, "service_jwt_key_id", KEY_ID)
    monkeypatch.setattr(settings, "service_jwt_private_key_file", str(private_path))
    monkeypatch.setattr(settings, "service_jwt_trusted_keys_json", json.dumps(trust))
    monkeypatch.setattr(settings, "service_jwt_expected_audience", AUDIENCE)
    monkeypatch.setattr(settings, "service_jwt_issued_audiences", [AUDIENCE])
    monkeypatch.setattr(settings, "service_jwt_issued_scopes", ISSUED_SCOPES)
    monkeypatch.setattr(settings, "service_jwt_ttl_seconds", 300)
    monkeypatch.setattr(settings, "service_jwt_clock_skew_seconds", 30)
    monkeypatch.setattr(settings, "internal_service_secret", SecretStr(INTERNAL_SECRET))
    return private_key


def _app():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(internal_router)
    return app


def _authorization_body(action=AuthorizationAction.DOCUMENT_READ, **changes):
    body = {
        "user_id": str(uuid4()),
        "resource_type": "class",
        "resource_id": str(uuid4()),
        "action": action.value if isinstance(action, AuthorizationAction) else action,
    }
    body.update(changes)
    return body


def _context(*, roles=(), student=False, teacher=False, active=True, history=False):
    class Repository:
        def has_membership_history(self, class_id, user_id):
            return history

    class_id = uuid4()
    return SimpleNamespace(
        user_id=uuid4(),
        class_id=class_id,
        klass=SimpleNamespace(
            id=class_id,
            school_id=uuid4(),
            status=ClassStatus.ACTIVE if active else ClassStatus.ARCHIVED,
        ),
        roles=frozenset(roles),
        repository=Repository(),
        current_student=student,
        current_teacher=teacher,
        assignment=SimpleNamespace(role=TeachingRole.PRIMARY) if teacher else None,
        active_class=active,
    )


def _patch_live_class_state(monkeypatch, **changes):
    state = {
        "user_status": "ACTIVE",
        "user_school_id": uuid4(),
        "class_school_id": None,
        "class_status": ClassStatus.ACTIVE,
        "roles": ["STUDENT"],
        "member": True,
        "teacher_role": None,
        "history": True,
    }
    state["class_school_id"] = state["user_school_id"]
    state.update(changes)
    user_id, class_id = uuid4(), uuid4()

    class Repository:
        def __init__(self, session):
            self.session = session

        def get_class(self, requested_id, *, for_share=False):
            assert requested_id == class_id
            return SimpleNamespace(school_id=state["class_school_id"], status=state["class_status"])

        def active_membership(self, requested_id, requested_user_id):
            assert requested_id == class_id
            assert requested_user_id == user_id
            return object() if state["member"] else None

        def active_teacher(self, requested_id, requested_user_id):
            assert requested_id == class_id
            assert requested_user_id == user_id
            if state["teacher_role"] is None:
                return None
            return SimpleNamespace(role=state["teacher_role"])

        def has_membership_history(self, requested_id, requested_user_id):
            return state["history"]

    monkeypatch.setattr(public, "ClassroomRepository", Repository)
    monkeypatch.setattr(
        public,
        "get_user_summary",
        lambda requested_user_id, **kwargs: UserSummaryDTO(
            id=requested_user_id,
            email=None,
            username="authorization.test",
            school_id=state["user_school_id"],
            status=state["user_status"],
        ),
    )
    monkeypatch.setattr(public, "get_user_roles", lambda *args, **kwargs: state["roles"])
    return state, user_id, class_id


@pytest.mark.parametrize(
    ("action", "context", "allowed"),
    [
        (AuthorizationAction.DOCUMENT_READ, _context(roles={"STUDENT"}, student=True), True),
        (AuthorizationAction.DOCUMENT_READ, _context(roles={"LECTURER"}, teacher=True), True),
        (AuthorizationAction.DOCUMENT_READ, _context(roles={"STUDENT"}), False),
        (AuthorizationAction.DOCUMENT_SHARE, _context(roles={"LECTURER"}, teacher=True), True),
        (AuthorizationAction.DOCUMENT_SHARE, _context(roles={"STUDENT"}, student=True), False),
        (
            AuthorizationAction.DOCUMENT_SHARE,
            _context(roles={"LECTURER"}, teacher=True, active=False),
            False,
        ),
        (AuthorizationAction.DOCUMENT_MANAGE, _context(roles={"LECTURER"}, teacher=True), True),
        (AuthorizationAction.DOCUMENT_MANAGE, _context(roles={"ADMIN"}), False),
        (AuthorizationAction.AI_QUERY, _context(roles={"STUDENT"}, student=True), True),
        (AuthorizationAction.AI_QUERY, _context(roles={"LECTURER"}, teacher=True), False),
        (
            AuthorizationAction.AI_QUERY,
            _context(roles={"STUDENT"}, student=True, active=False),
            False,
        ),
        (AuthorizationAction.PRACTICE_ACCESS, _context(roles={"STUDENT"}, student=True), True),
        (AuthorizationAction.PRACTICE_ACCESS, _context(roles={"LECTURER"}, teacher=True), False),
        (
            AuthorizationAction.PRACTICE_ACCESS,
            _context(roles={"STUDENT", "LECTURER"}, student=True, teacher=True),
            True,
        ),
        (
            AuthorizationAction.PRACTICE_ACCESS,
            _context(roles={"STUDENT", "LECTURER"}, student=False, teacher=True),
            False,
        ),
        (AuthorizationAction.PRACTICE_ACCESS, _context(roles={"ADMIN"}), False),
        (AuthorizationAction.ASSIGNMENT_CREATE, _context(roles={"LECTURER"}, teacher=True), True),
        (AuthorizationAction.ASSIGNMENT_CREATE, _context(roles={"STUDENT"}, student=True), False),
        (AuthorizationAction.ASSIGNMENT_SUBMIT, _context(roles={"STUDENT"}, student=True), True),
        (AuthorizationAction.ASSIGNMENT_SUBMIT, _context(roles={"LECTURER"}, teacher=True), False),
        (AuthorizationAction.ASSESSMENT_MANAGE, _context(roles={"LECTURER"}, teacher=True), True),
        (AuthorizationAction.ASSESSMENT_MANAGE, _context(roles={"STUDENT"}, student=True), False),
        (AuthorizationAction.GRADE_MANAGE, _context(roles={"LECTURER"}, teacher=True), True),
        (AuthorizationAction.GRADE_MANAGE, _context(roles={"STUDENT"}, student=True), False),
        (
            AuthorizationAction.ANALYTICS_VIEW,
            _context(roles={"STUDENT"}, history=True),
            True,
        ),
        (AuthorizationAction.ANALYTICS_VIEW, _context(roles={"STUDENT"}, history=False), False),
        (AuthorizationAction.ANALYTICS_VIEW, _context(roles={"LECTURER"}, teacher=True), True),
        (AuthorizationAction.ANALYTICS_VIEW, _context(roles={"ADMIN"}), True),
        (AuthorizationAction.ANALYTICS_VIEW, _context(roles={"ADMIN"}, active=False), True),
        (AuthorizationAction.ANALYTICS_VIEW, _context(roles={"STUDENT"}), False),
    ],
)
def test_class_side_policy_is_action_and_role_specific(monkeypatch, action, context, allowed):
    monkeypatch.setattr(public, "_class_authorization_context", lambda *args, **kwargs: context)
    assert (
        public.check_class_authorization_action(
            context.klass.id, context.user_id, action, session=object()
        )
        is allowed
    )


def test_unknown_or_cross_school_class_context_denies(monkeypatch):
    monkeypatch.setattr(public, "_class_authorization_context", lambda *args, **kwargs: None)
    assert not public.check_class_authorization_action(
        uuid4(), uuid4(), AuthorizationAction.DOCUMENT_READ, session=object()
    )


def test_legacy_participate_current_class_still_allows_lecturer(monkeypatch):
    context = _context(roles={"LECTURER"}, teacher=True, active=True)
    monkeypatch.setattr(public, "_class_authorization_context", lambda *args, **kwargs: context)
    assert public.check_class_action(
        context.klass.id,
        context.user_id,
        ClassAccessAction.PARTICIPATE_CURRENT_CLASS,
        session=object(),
    ).allowed


def test_authorization_uses_live_user_status_school_and_membership(monkeypatch):
    state, user_id, class_id = _patch_live_class_state(monkeypatch)
    assert public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.ASSIGNMENT_SUBMIT, session=object()
    )
    assert public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.PRACTICE_ACCESS, session=object()
    )
    state["member"] = False
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.ASSIGNMENT_SUBMIT, session=object()
    )
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.PRACTICE_ACCESS, session=object()
    )
    state["member"] = True
    state["user_status"] = "LOCKED"
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.ASSIGNMENT_SUBMIT, session=object()
    )
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.PRACTICE_ACCESS, session=object()
    )
    state["user_status"] = "ACTIVE"
    state["class_school_id"] = uuid4()
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.ASSIGNMENT_SUBMIT, session=object()
    )
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.PRACTICE_ACCESS, session=object()
    )


def test_multi_role_practice_requires_current_student_membership(monkeypatch):
    state, user_id, class_id = _patch_live_class_state(
        monkeypatch,
        roles=["STUDENT", "LECTURER"],
        member=True,
        teacher_role=TeachingRole.ASSISTING,
    )
    assert public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.PRACTICE_ACCESS, session=object()
    )
    state["member"] = False
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.PRACTICE_ACCESS, session=object()
    )


@pytest.mark.parametrize("teacher_role", [TeachingRole.PRIMARY, TeachingRole.ASSISTING])
def test_primary_and_assisting_use_current_assignment_for_teacher_gates(monkeypatch, teacher_role):
    state, user_id, class_id = _patch_live_class_state(
        monkeypatch,
        roles=["LECTURER"],
        member=False,
        teacher_role=teacher_role,
    )
    assert public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.DOCUMENT_SHARE, session=object()
    )
    assert public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.GRADE_MANAGE, session=object()
    )
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.PRACTICE_ACCESS, session=object()
    )
    state["teacher_role"] = None
    assert not public.check_class_authorization_action(
        class_id, user_id, AuthorizationAction.DOCUMENT_SHARE, session=object()
    )


@pytest.mark.parametrize(
    "action",
    [
        AuthorizationAction.DOCUMENT_SHARE,
        AuthorizationAction.DOCUMENT_MANAGE,
        AuthorizationAction.AI_QUERY,
        AuthorizationAction.PRACTICE_ACCESS,
        AuthorizationAction.ASSIGNMENT_CREATE,
        AuthorizationAction.ASSIGNMENT_SUBMIT,
        AuthorizationAction.ASSESSMENT_MANAGE,
        AuthorizationAction.GRADE_MANAGE,
    ],
)
def test_archived_class_denies_actions_that_create_or_participate(monkeypatch, action):
    context = _context(roles={"LECTURER", "STUDENT"}, student=True, teacher=True, active=False)
    monkeypatch.setattr(public, "_class_authorization_context", lambda *args, **kwargs: context)
    assert not public.check_class_authorization_action(
        context.klass.id, context.user_id, action, session=object()
    )


@pytest.mark.parametrize(
    ("service_id", "action", "allowed"),
    [
        ("document", AuthorizationAction.DOCUMENT_READ, True),
        ("document", AuthorizationAction.DOCUMENT_SHARE, True),
        ("document", AuthorizationAction.DOCUMENT_MANAGE, True),
        ("document", AuthorizationAction.AI_QUERY, False),
        ("ai", AuthorizationAction.AI_QUERY, True),
        ("ai", AuthorizationAction.DOCUMENT_READ, False),
        ("learning", AuthorizationAction.ASSIGNMENT_SUBMIT, True),
        ("learning", AuthorizationAction.GRADE_MANAGE, True),
        ("learning", AuthorizationAction.DOCUMENT_MANAGE, False),
        ("notification", AuthorizationAction.AI_QUERY, False),
        ("unknown", AuthorizationAction.DOCUMENT_READ, False),
    ],
)
def test_caller_action_matrix_is_least_privilege(service_id, action, allowed):
    assert service_may_authorize(service_id, action) is allowed
    assert set().union(*CALLER_ALLOWED_ACTIONS.values()) == set(AuthorizationAction)


def test_core04_endpoint_returns_only_allowed_for_valid_service(auth_setup, monkeypatch):
    token = issue_service_jwt(audience=AUDIENCE, scopes={REQUIRED_SCOPE})
    calls = []
    monkeypatch.setattr(
        classroom_router,
        "check_class_authorization_action",
        lambda class_id, user_id, action: calls.append((class_id, user_id, action)) or True,
    )
    body = _authorization_body()
    response = TestClient(_app()).post(
        "/internal/v1/authorization/check",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"allowed": True}
    assert calls == [
        (UUID(body["resource_id"]), UUID(body["user_id"]), AuthorizationAction.DOCUMENT_READ)
    ]


def test_core04_openapi_exposes_strict_class_authorization_contract():
    spec = _app().openapi()
    path = "/internal/v1/authorization/check"
    assert "post" in spec["paths"][path]
    operation = spec["paths"][path]["post"]
    assert operation["requestBody"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/AuthorizationCheckRequest"
    )
    assert set(operation["responses"]) >= {"200", "401", "403", "422", "500", "503"}
    active_actions = set(spec["components"]["schemas"]["AuthorizationAction"]["enum"])
    assert active_actions == {action.value for action in AuthorizationAction}
    assert "ASSESSMENT_APPROVE" not in active_actions
    assert "GRADE_CORRECTION_APPROVE" not in active_actions
    assert spec["components"]["schemas"]["AuthorizationResourceType"]["enum"] == ["class"]
    assert "get" not in spec["paths"][path]


def test_business_denial_returns_allowed_false(auth_setup, monkeypatch):
    token = issue_service_jwt(audience=AUDIENCE, scopes={REQUIRED_SCOPE})
    monkeypatch.setattr(classroom_router, "check_class_authorization_action", lambda *args: False)
    response = TestClient(_app()).post(
        "/internal/v1/authorization/check",
        json=_authorization_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"allowed": False}


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer malformed"}])
def test_core04_endpoint_rejects_missing_or_invalid_service_jwt(auth_setup, headers):
    response = TestClient(_app()).post(
        "/internal/v1/authorization/check",
        json=_authorization_body(),
        headers=headers,
    )
    assert response.status_code == 401


def test_core04_endpoint_rejects_user_jwt(auth_setup, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", SecretStr("local-test-user-key-" + "x" * 32))
    token = create_access_token(uuid4(), ["LECTURER"], 1)
    response = TestClient(_app()).post(
        "/internal/v1/authorization/check",
        json=_authorization_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_core04_endpoint_rejects_legacy_service_key(auth_setup):
    response = TestClient(_app()).post(
        "/internal/v1/authorization/check",
        json=_authorization_body(),
        headers={"X-Service-Key": INTERNAL_SECRET},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("payload_changes", "expected_status"),
    [
        ({"aud": "learning"}, 401),
        ({"sub": "ai"}, 401),
        ({"scope": ["core:read"]}, 403),
    ],
)
def test_core04_endpoint_enforces_service_claims(auth_setup, payload_changes, expected_status):
    token = _sign(_claims(**payload_changes), auth_setup)
    response = TestClient(_app()).post(
        "/internal/v1/authorization/check",
        json=_authorization_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == expected_status


def test_core04_endpoint_denies_caller_action_mismatch(auth_setup, monkeypatch):
    token = issue_service_jwt(audience=AUDIENCE, scopes={REQUIRED_SCOPE})
    policy_called = False

    def unexpected_policy_call(*args):
        nonlocal policy_called
        policy_called = True
        return True

    monkeypatch.setattr(
        classroom_router, "check_class_authorization_action", unexpected_policy_call
    )
    response = TestClient(_app()).post(
        "/internal/v1/authorization/check",
        json=_authorization_body(AuthorizationAction.AI_QUERY),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert not policy_called


@pytest.mark.parametrize(
    "changes",
    [
        {"resource_type": "document"},
        {"action": "UNKNOWN_ACTION"},
        {"action": "ASSESSMENT_APPROVE"},
        {"action": "GRADE_CORRECTION_APPROVE"},
        {"unrecognized": "field"},
    ],
)
def test_core04_endpoint_rejects_unknown_or_extra_request_fields(auth_setup, changes):
    token = issue_service_jwt(audience=AUDIENCE, scopes={REQUIRED_SCOPE})
    body = _authorization_body(**changes)
    response = TestClient(_app()).post(
        "/internal/v1/authorization/check",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_core04_database_failure_returns_non_success(auth_setup, monkeypatch):
    token = issue_service_jwt(audience=AUDIENCE, scopes={REQUIRED_SCOPE})

    def database_down(*args):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(classroom_router, "check_class_authorization_action", database_down)
    response = TestClient(_app(), raise_server_exceptions=False).post(
        "/internal/v1/authorization/check",
        json=_authorization_body(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_legacy_get_still_uses_x_service_key(auth_setup, monkeypatch):
    class_id, user_id = uuid4(), uuid4()
    class_access = ClassAccessDTO(
        allowed=True,
        class_id=class_id,
        school_id=uuid4(),
        class_status=ClassStatus.ACTIVE,
        teaching_role=TeachingRole.PRIMARY,
    )
    monkeypatch.setattr(
        classroom_router, "check_class_action", lambda *args, **kwargs: class_access
    )
    response = TestClient(_app()).get(
        f"/internal/v1/classes/{class_id}/access",
        params={"user_id": str(user_id), "action": ClassAccessAction.READ_DOCUMENT_SOURCE.value},
        headers={"X-Service-Key": INTERNAL_SECRET},
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert response.json()["class_id"] == str(class_id)
    assert response.json()["user_id"] == str(user_id)
    assert response.json()["action"] == ClassAccessAction.READ_DOCUMENT_SOURCE.value

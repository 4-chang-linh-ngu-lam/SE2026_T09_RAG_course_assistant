from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.identity.models import DataRequestStatus, DataRequestType, Role, UserStatus
from app.modules.identity.schemas import (
    ActivateStudentRequest,
    AdminCreateStudentRequest,
    DataRequestResponse,
    LoginRequest,
    PersonalDataExport,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserProfile,
)


def test_email_normalization_and_secret_inputs():
    request = RegisterRequest(email="STUDENT@Example.COM", password="test password long enough")
    assert request.email == "student@example.com"
    assert "test password" not in repr(request)
    assert request.model_dump(mode="json")["password"] == "**********"
    assert LoginRequest(email="STUDENT@example.com", password="bad").email == "student@example.com"


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_password_length(password):
    with pytest.raises(ValidationError):
        RegisterRequest(email="student@example.com", password=password)
    with pytest.raises(ValidationError):
        ResetPasswordRequest(token="test-token", new_password=password)


def test_requests_reject_privilege_escalation_and_invalid_email():
    for overrides in ({"email": "invalid"}, {"roles": ["ADMIN"]}, {"status": "ACTIVE"}):
        values = {"email": "student@example.com", "password": "test password long enough"}
        values.update(overrides)
        with pytest.raises(ValidationError):
            RegisterRequest(**values)


def test_responses_never_serialize_storage_hashes():
    response = RegisterResponse(
        user_id=uuid4(), email="student@example.com", status=UserStatus.PENDING_VERIFICATION
    )
    assert set(response.model_dump()) == {"user_id", "email", "status"}
    assert set(TokenResponse(access_token="test-access").model_dump()) == {
        "access_token",
        "token_type",
        "expires_in",
    }


def test_personal_data_export_schema_contains_only_core_identity_records():
    user_id = uuid4()
    now = datetime.now(UTC)
    export = PersonalDataExport(
        exported_at=now,
        profile=UserProfile(
            id=user_id,
            email=None,
            username="student.synthetic",
            school_id=uuid4(),
            display_name="Synthetic student",
            roles=[Role.STUDENT],
            status=UserStatus.ACTIVE,
        ),
        data_requests=[
            DataRequestResponse(
                id=uuid4(),
                user_id=user_id,
                request_type=DataRequestType.EXPORT,
                reason="Synthetic request",
                status=DataRequestStatus.PENDING,
                resolution_note=None,
                created_at=now,
                updated_at=now,
            )
        ],
    )

    payload = export.model_dump(mode="json")
    assert set(payload) == {"schema_version", "exported_at", "profile", "data_requests"}
    assert payload["schema_version"] == 1
    assert payload["data_requests"][0]["user_id"] == str(user_id)
    assert "password_hash" not in payload["profile"]
    assert all("token" not in key.lower() for key in payload)


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"email": "staff@example.com", "username": "student"},
        {"username": ""},
        {"username": "student\x00"},
        {"username": "a b"},
        {"username": "student@example.com"},
    ],
)
def test_login_requires_one_valid_identifier(values):
    with pytest.raises(ValidationError):
        LoginRequest(password="test-only", **values)


def test_student_inputs_normalize_username_and_do_not_accept_email_or_roles():
    request = AdminCreateStudentRequest(username="  Student.Example  ")
    assert request.username == "student.example"
    assert LoginRequest(username=" STUDENT.EXAMPLE ", password="test").login_key == (
        "username:student.example"
    )
    for extra in (
        {"roles": ["ADMIN"]},
        {"email": "student@example.com"},
        {"school_id": str(uuid4())},
    ):
        with pytest.raises(ValidationError):
            AdminCreateStudentRequest(username="student", **extra)
    body = ActivateStudentRequest(
        username="student", activation_code="test-only-code", new_password="test-only long password"
    )
    assert "test-only-code" not in repr(body)

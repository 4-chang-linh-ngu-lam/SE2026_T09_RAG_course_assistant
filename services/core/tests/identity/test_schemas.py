from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.identity.models import UserStatus
from app.modules.identity.schemas import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenResponse,
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

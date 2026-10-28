from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.common.config import settings
from app.common.errors import AppError
from app.modules.identity.credential_tokens import derive_email_token
from app.modules.identity.models import TokenPurpose


def test_email_token_can_be_regenerated_for_retry_without_persisting_raw_value(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", SecretStr("test-only-key-" + "x" * 32))
    token_id, user_id = uuid4(), uuid4()
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    first = derive_email_token(token_id, user_id, TokenPurpose.ADMIN_INVITATION, expires_at)
    retry = derive_email_token(token_id, user_id, TokenPurpose.ADMIN_INVITATION, expires_at)

    assert first == retry
    assert len(first) == 43
    assert derive_email_token(uuid4(), user_id, TokenPurpose.ADMIN_INVITATION, expires_at) != first
    assert derive_email_token(token_id, user_id, TokenPurpose.PASSWORD_RESET, expires_at) != first
    assert (
        derive_email_token(
            token_id, user_id, TokenPurpose.ADMIN_INVITATION, expires_at + timedelta(seconds=1)
        )
        != first
    )


def test_email_token_generation_fails_closed_without_signing_key(monkeypatch):
    monkeypatch.setattr(settings, "secret_key", None)
    with pytest.raises(AppError) as raised:
        derive_email_token(
            uuid4(),
            uuid4(),
            TokenPurpose.PASSWORD_RESET,
            datetime.now(UTC) + timedelta(minutes=5),
        )
    assert raised.value.status_code == 503

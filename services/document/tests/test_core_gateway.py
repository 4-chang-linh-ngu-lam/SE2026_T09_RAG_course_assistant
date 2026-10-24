from urllib.error import HTTPError

import pytest
from pydantic import SecretStr

from app import auth
from app.config import settings
from app.errors import DocumentError


@pytest.mark.parametrize("http_status", [401, 403])
def test_internal_service_auth_failure_is_not_a_user_session_expiration(monkeypatch, http_status):
    class Unavailable:
        def open(self, request, **kwargs):
            raise HTTPError(request.full_url, http_status, "rejected", {}, None)

    monkeypatch.setattr(auth, "build_opener", lambda *args: Unavailable())
    monkeypatch.setattr(settings, "internal_service_secret", SecretStr("synthetic-" + "x" * 32))
    with pytest.raises(DocumentError) as result:
        auth.CoreGateway().request("/internal/v1/classes/test/access", bearer="Bearer synthetic")
    assert result.value.status == 503
    with pytest.raises(DocumentError) as result:
        auth.CoreGateway().request("/api/v1/users/me", bearer="Bearer synthetic")
    assert result.value.status == http_status

"""Deterministic, non-stored material for retrying one-time email delivery.

The database stores only the token hash. A token can be regenerated for the
same token row while the configured signing secret remains unchanged.
"""

import base64
import hashlib
import hmac
from datetime import datetime
from uuid import UUID

from app.common.config import settings
from app.common.errors import AppError
from app.modules.identity.models import TokenPurpose

_DOMAIN = b"lumi.identity.email-token.v1\0"


def derive_email_token(
    token_id: UUID, user_id: UUID, purpose: TokenPurpose, expires_at: datetime
) -> str:
    secret = settings.secret_key
    if secret is None:
        raise AppError(503, "Authentication unavailable")
    fields = (
        str(token_id),
        str(user_id),
        purpose.value,
        expires_at.isoformat(),
    )
    message = _DOMAIN + "\0".join(fields).encode("utf-8")
    digest = hmac.new(secret.get_secret_value().encode("utf-8"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

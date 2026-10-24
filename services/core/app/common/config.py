from typing import Literal
from urllib.parse import urlsplit

from pydantic import EmailStr, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://rag_course:change-me-local-only@localhost:5432/rag_course"
    )
    cors_origins: list[str] = ["http://localhost:3000"]
    web_origin: str | None = None

    @field_validator("web_origin")
    @classmethod
    def validate_web_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parts = urlsplit(value)
        if (
            any(character.isspace() for character in value)
            or any(character in value for character in ("\\", "?", "#"))
            or parts.scheme not in ("http", "https")
            or not parts.hostname
            or "%" in parts.netloc
            or parts.username is not None
            or parts.password is not None
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            raise ValueError("WEB_ORIGIN must be an HTTP(S) origin without credentials or path")
        # Accessing port validates its syntax and range as well.
        if parts.port is not None and parts.port < 1:
            raise ValueError("WEB_ORIGIN has an invalid port")
        return value.rstrip("/")

    database_connect_timeout_seconds: int = Field(default=3, gt=0)
    database_pool_timeout_seconds: int = Field(default=3, gt=0)
    database_pool_size: int = Field(default=5, gt=0)
    database_max_overflow: int = Field(default=10, ge=0)
    # Health/migrations can start without keys; authentication fails closed until configured.
    secret_key: SecretStr | None = Field(default=None, min_length=32)
    algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, gt=0)
    refresh_token_expire_days: int = Field(default=7, gt=0)
    email_verification_expire_hours: int = Field(default=24, gt=0)
    password_reset_expire_minutes: int = Field(default=60, gt=0)
    admin_invitation_expire_hours: int = Field(default=24, gt=0)
    student_activation_expire_hours: int = Field(default=24, gt=0)
    internal_service_secret: SecretStr | None = Field(default=None, min_length=32)
    document_events_service_secret: SecretStr | None = Field(default=None, min_length=32)
    # Distinct server-only Web attestation key; never grants a user/service role.
    core_proxy_secret: SecretStr | None = Field(default=None, min_length=32)
    cookie_secure: bool = True
    cookie_httponly: Literal[True] = True
    cookie_samesite: Literal["lax"] = "lax"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: EmailStr | None = None
    smtp_security: Literal["starttls", "tls"] = "starttls"
    smtp_timeout_seconds: float = Field(default=10, gt=0)
    auth_login_max_failures: int = Field(default=5, gt=0)
    auth_login_window_seconds: int = Field(default=60, gt=0)
    auth_register_limit: int = Field(default=3, gt=0)
    auth_forgot_limit: int = Field(default=3, gt=0)
    auth_request_window_seconds: int = Field(default=3600, gt=0)
    auth_reset_limit: int = Field(default=5, gt=0)
    auth_rate_limit_max_keys: int = Field(default=10000, gt=0)
    auth_idempotency_max_keys: int = Field(default=1000, gt=0)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

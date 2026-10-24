from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://document:configure-me@localhost:5432/rag_course"
    core_api_url: str = "http://core:8000"
    internal_service_secret: SecretStr | None = Field(default=None, min_length=32)
    document_events_service_secret: SecretStr | None = Field(default=None, min_length=32)
    document_internal_service_secret: SecretStr | None = Field(default=None, min_length=32)
    document_event_reader_secret: SecretStr | None = Field(default=None, min_length=32)
    storage_root: Path = Path("/data/documents")
    max_file_size_bytes: int = Field(default=50 * 1024 * 1024, ge=1, le=50 * 1024 * 1024)
    processing_timeout_seconds: int = Field(default=90, ge=1, le=90)
    job_lease_seconds: int = Field(default=120, ge=100, le=600)
    core_timeout_seconds: float = Field(default=5, gt=0, le=15)

    @field_validator("core_api_url")
    @classmethod
    def valid_origin(cls, value: str) -> str:
        p = urlsplit(value)
        if (
            p.scheme not in {"http", "https"}
            or not p.hostname
            or p.username is not None
            or p.password is not None
            or p.path not in {"", "/"}
            or p.query
            or p.fragment
            or any(c.isspace() for c in value)
            or "\\" in value
        ):
            raise ValueError("CORE_API_URL must be an HTTP(S) origin")
        return value.rstrip("/")

    @model_validator(mode="after")
    def distinct_credentials(self):
        secrets = [
            s.get_secret_value()
            for s in (
                self.internal_service_secret,
                self.document_events_service_secret,
                self.document_internal_service_secret,
                self.document_event_reader_secret,
            )
            if s is not None
        ]
        if len(secrets) != len(set(secrets)):
            raise ValueError("Service credentials must be distinct")
        return self


settings = Settings()

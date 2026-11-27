from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    database_url: SecretStr | None = None
    database_admin_url: SecretStr | None = None
    database_name: str = "lumi_document"
    database_user: str = "lumi_document"
    database_password: SecretStr | None = None
    allow_local_database_provisioning: bool = False
    test_database_disposable: bool = False
    database_connect_timeout_seconds: int = Field(default=3, gt=0)
    database_pool_timeout_seconds: int = Field(default=3, gt=0)
    database_pool_size: int = Field(default=5, gt=0)
    database_max_overflow: int = Field(default=5, ge=0)
    storage_root: Path = Path("/var/lib/lumi-document/files")

    model_config = SettingsConfigDict(
        env_prefix="DOCUMENT_",
        env_file=".env",
        extra="ignore",
    )

    @field_validator("database_url", "database_admin_url")
    @classmethod
    def require_postgresql_psycopg(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        parsed = make_url(value.get_secret_value())
        if parsed.drivername != "postgresql+psycopg":
            raise ValueError("Document database URLs must use postgresql+psycopg")
        return value


settings = Settings()

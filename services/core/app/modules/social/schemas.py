from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuthorSummary(BaseModel):
    """Public Social author projection; login identifiers are intentionally omitted."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    display_name: str | None = None

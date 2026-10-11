from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.db import Base


class AuditMetadata(BaseModel):
    """Allow only structured non-content fields; arbitrary text is not safe to audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    changed_fields: list[Literal["status", "roles", "owner_user_id", "join_enabled"]] = []
    previous_status: Literal["ACTIVE", "LOCKED", "ARCHIVED", "PENDING_VERIFICATION"] | None = None
    new_status: Literal["ACTIVE", "LOCKED", "ARCHIVED", "PENDING_VERIFICATION"] | None = None
    reason_code: Literal["ADMIN_INTERVENTION", "USER_REQUEST", "POLICY_VIOLATION"] | None = None


class AuditEvent(Base):
    __tablename__ = "audit_events"

    actor_id: Mapped[UUID | None]
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[UUID]
    correlation_id: Mapped[UUID]
    metadata_json: Mapped[dict] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


def record_audit(
    session: Session,
    *,
    actor_id: UUID | None,
    action: str,
    target_type: str,
    target_id: UUID,
    correlation_id: UUID,
    metadata_json: AuditMetadata,
) -> AuditEvent:
    # Action/type are identifiers, never user-supplied descriptions or content.
    for identifier in (action, target_type):
        if not identifier or len(identifier) > 100 or not identifier.replace("_", "").isalpha():
            raise ValueError("Audit action and target type must be identifiers")
    if not isinstance(metadata_json, AuditMetadata):
        raise TypeError("Audit metadata must use the safe schema")
    # Revalidate mutable fields before persistence, even on an already-created DTO.
    safe_metadata = AuditMetadata.model_validate(metadata_json.model_dump())
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        correlation_id=correlation_id,
        metadata_json=safe_metadata.model_dump(exclude_none=True),
    )
    session.add(event)
    return event

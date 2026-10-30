from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.db import Base


class AuditMetadata(BaseModel):
    """Allow only structured non-content fields; arbitrary text is not safe to audit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    changed_fields: list[
        Literal[
            "status",
            "roles",
            "owner_user_id",
            "join_enabled",
            "username",
            "credentials",
            "data_request_status",
            "school_id",
        ]
    ] = []
    previous_status: Literal["ACTIVE", "LOCKED", "ARCHIVED", "PENDING_VERIFICATION"] | None = None
    new_status: Literal["ACTIVE", "LOCKED", "ARCHIVED", "PENDING_VERIFICATION"] | None = None
    reason_code: Literal["ADMIN_INTERVENTION", "USER_REQUEST", "POLICY_VIOLATION"] | None = None
    identity_verified: bool | None = None
    manual_fulfillment_confirmed: bool | None = None


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("idx_audit_school_occurred", "school_id", "occurred_at", "id"),
        Index("idx_audit_actor_occurred", "actor_id", "occurred_at"),
        Index("idx_audit_action_occurred", "action", "occurred_at"),
    )

    actor_id: Mapped[UUID | None]
    school_id: Mapped[UUID | None]
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
    school_id: UUID | None = None,
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
        school_id=school_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        correlation_id=correlation_id,
        metadata_json=safe_metadata.model_dump(exclude_none=True),
    )
    session.add(event)
    return event

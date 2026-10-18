from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.common.audit import AuditEvent
from app.common.errors import AppError
from app.modules.administration.models import StudentImportBatch


class AdministrationRepository:
    def __init__(self, session: Session):
        self.session = session

    def batch(self, preview_id: UUID, actor_id: UUID, school_id: UUID) -> StudentImportBatch:
        row = self.session.scalar(
            select(StudentImportBatch)
            .where(
                StudentImportBatch.id == preview_id,
                StudentImportBatch.actor_id == actor_id,
                StudentImportBatch.school_id == school_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise AppError(404)
        return row

    def audit_events(
        self,
        school_id: UUID,
        *,
        limit: int,
        cursor: UUID | None,
        actor_id: UUID | None,
        action: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> list[AuditEvent]:
        conditions = [AuditEvent.school_id == school_id]
        if actor_id is not None:
            conditions.append(AuditEvent.actor_id == actor_id)
        if action is not None:
            conditions.append(AuditEvent.action == action)
        if since is not None:
            conditions.append(AuditEvent.occurred_at >= since)
        if until is not None:
            conditions.append(AuditEvent.occurred_at <= until)
        query = select(AuditEvent).where(*conditions)
        if cursor is not None:
            anchor = self.session.scalar(
                select(AuditEvent).where(AuditEvent.id == cursor, *conditions)
            )
            if anchor is None:
                raise AppError(400, "Invalid cursor")
            query = query.where(
                or_(
                    AuditEvent.occurred_at < anchor.occurred_at,
                    and_(AuditEvent.occurred_at == anchor.occurred_at, AuditEvent.id < anchor.id),
                )
            )
        return list(
            self.session.scalars(
                query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
            )
        )

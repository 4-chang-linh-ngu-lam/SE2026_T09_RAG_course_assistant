import hashlib
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.modules.notification.models import Notification


class NotificationRepository:
    def __init__(self, session: Session):
        self.session = session

    def lock_recipient(self, recipient_id: UUID) -> None:
        # All inbox writes take this transaction lock. Hash collisions only serialize
        # unrelated recipients; no user identifiers or secrets enter SQL literals.
        key = int.from_bytes(hashlib.sha256(recipient_id.bytes).digest()[:8], signed=True)
        self.session.execute(select(func.pg_advisory_xact_lock(key)))

    def create(self, *, recipient_id: UUID, event_type: str, payload: dict, dedup_key: str) -> None:
        self.lock_recipient(recipient_id)
        self.session.execute(
            insert(Notification)
            .values(
                recipient_id=recipient_id,
                type=event_type,
                payload_json=payload,
                dedup_key=dedup_key,
            )
            .on_conflict_do_nothing(index_elements=[Notification.dedup_key])
        )

    def list_for_user(
        self, user_id: UUID, *, limit: int, cursor: UUID | None
    ) -> list[Notification]:
        query = select(Notification).where(Notification.recipient_id == user_id)
        if cursor is not None:
            sequence = self.session.scalar(
                select(Notification.sequence).where(
                    Notification.id == cursor, Notification.recipient_id == user_id
                )
            )
            if sequence is None:
                raise AppError(400, "Invalid cursor")
            query = query.where(Notification.sequence < sequence)
        return list(
            self.session.scalars(query.order_by(Notification.sequence.desc()).limit(limit + 1))
        )

    def unread_count(self, user_id: UUID) -> int:
        return self.session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.recipient_id == user_id, Notification.read_at.is_(None))
        )

    def mark_read(self, notification_id: UUID, user_id: UUID) -> None:
        found = self.session.scalar(
            update(Notification)
            .where(Notification.id == notification_id, Notification.recipient_id == user_id)
            .values(read_at=func.coalesce(Notification.read_at, func.clock_timestamp()))
            .returning(Notification.id)
        )
        if found is None:
            raise AppError(404)

    def mark_all_read(self, user_id: UUID) -> None:
        watermark = self.session.scalar(
            select(func.max(Notification.sequence)).where(Notification.recipient_id == user_id)
        )
        if watermark is not None:
            self.session.execute(
                update(Notification)
                .where(
                    Notification.recipient_id == user_id,
                    Notification.sequence <= watermark,
                    Notification.read_at.is_(None),
                )
                .values(read_at=func.clock_timestamp())
            )

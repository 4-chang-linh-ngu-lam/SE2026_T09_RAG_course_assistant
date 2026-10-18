from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.modules.social.calendar.models import CalendarEvent, CalendarOrigin


class CalendarRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, event: CalendarEvent) -> CalendarEvent:
        self.session.add(event)
        self.session.flush()
        return event

    def get(self, event_id: UUID, *, for_update: bool = False) -> CalendarEvent | None:
        query = select(CalendarEvent).where(CalendarEvent.id == event_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_learning(self, external_ref: str, *, for_update: bool = False) -> CalendarEvent | None:
        query = select(CalendarEvent).where(
            CalendarEvent.origin == CalendarOrigin.LEARNING,
            CalendarEvent.external_ref == external_ref,
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def insert_learning_if_absent(self, values: dict) -> UUID | None:
        """Insert nguyên tử; trả None nếu external_ref đã có (worker khác vừa tạo)."""
        statement = (
            insert(CalendarEvent)
            .values(origin=CalendarOrigin.LEARNING, **values)
            .on_conflict_do_nothing(
                index_elements=["origin", "external_ref"],
                index_where=text("external_ref IS NOT NULL"),
            )
            .returning(CalendarEvent.id)
        )
        return self.session.scalar(statement)

    def list(
        self,
        class_id: UUID,
        *,
        from_time: datetime | None,
        to_time: datetime | None,
        limit: int,
        cursor: UUID | None,
    ) -> list[CalendarEvent]:
        query = select(CalendarEvent).where(CalendarEvent.class_id == class_id)
        if from_time is not None:
            query = query.where(CalendarEvent.ends_at > from_time)
        if to_time is not None:
            query = query.where(CalendarEvent.starts_at < to_time)
        if cursor is not None:
            cursor_event = self.session.scalar(
                select(CalendarEvent).where(
                    CalendarEvent.id == cursor,
                    CalendarEvent.class_id == class_id,
                )
            )
            if cursor_event is None:
                raise AppError(400, "Invalid cursor")
            query = query.where(
                or_(
                    CalendarEvent.starts_at > cursor_event.starts_at,
                    and_(
                        CalendarEvent.starts_at == cursor_event.starts_at,
                        CalendarEvent.id > cursor_event.id,
                    ),
                )
            )
        return list(
            self.session.scalars(
                query.order_by(CalendarEvent.starts_at.asc(), CalendarEvent.id.asc()).limit(
                    limit + 1
                )
            )
        )

    def delete(self, event: CalendarEvent) -> None:
        self.session.delete(event)
        self.session.flush()

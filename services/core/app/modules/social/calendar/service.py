from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser
from app.common.db import transaction
from app.common.errors import AppError
from app.common.outbox import record_outbox_event
from app.common.pagination import Pagination, encode_cursor
from app.modules.classroom.public import ClassAccessAction
from app.modules.social.access import require_read_access, require_write_access
from app.modules.social.calendar.models import CalendarEvent, CalendarOrigin
from app.modules.social.calendar.repository import CalendarRepository
from app.modules.social.calendar.schemas import (
    CalendarEventCreateRequest,
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventUpdateRequest,
)

LEARNING_READ_ONLY = "Deadline từ Learning chỉ được đồng bộ tự động"


def _validate_interval(starts_at: datetime, ends_at: datetime) -> None:
    if (
        starts_at.tzinfo is None
        or starts_at.utcoffset() is None
        or ends_at.tzinfo is None
        or ends_at.utcoffset() is None
        or starts_at >= ends_at
    ):
        raise AppError(422, "Invalid event interval")


class CalendarService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = CalendarRepository(session)

    @staticmethod
    def _response(event: CalendarEvent) -> CalendarEventResponse:
        return CalendarEventResponse.model_validate(event)

    def list_events(
        self,
        class_id: UUID,
        pagination: Pagination,
        current_user: CurrentUser,
        *,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
    ) -> CalendarEventListResponse:
        require_read_access(self.session, class_id, current_user)
        if from_time is not None and (from_time.tzinfo is None or from_time.utcoffset() is None):
            raise AppError(422, "Datetime must include a timezone")
        if to_time is not None and (to_time.tzinfo is None or to_time.utcoffset() is None):
            raise AppError(422, "Datetime must include a timezone")
        if from_time is not None and to_time is not None and from_time >= to_time:
            raise AppError(422, "from must be before to")
        rows = self.repository.list(
            class_id,
            from_time=from_time,
            to_time=to_time,
            limit=pagination.limit,
            cursor=pagination.cursor,
        )
        items = rows[: pagination.limit]
        return CalendarEventListResponse(
            items=[self._response(event) for event in items],
            next_cursor=(
                encode_cursor(items[-1].id) if len(rows) > pagination.limit and items else None
            ),
        )

    def create_event(
        self,
        class_id: UUID,
        request: CalendarEventCreateRequest,
        current_user: CurrentUser,
    ) -> CalendarEventResponse:
        with transaction(self.session):
            require_write_access(
                self.session,
                class_id,
                current_user,
                ClassAccessAction.MANAGE_CLASS_CALENDAR,
            )
            event = self.repository.create(
                CalendarEvent(
                    class_id=class_id,
                    title=request.title,
                    description=request.description,
                    starts_at=request.starts_at,
                    ends_at=request.ends_at,
                    origin=CalendarOrigin.CORE,
                    external_ref=None,
                    version=1,
                )
            )
            return self._response(event)

    def update_event(
        self,
        class_id: UUID,
        event_id: UUID,
        request: CalendarEventUpdateRequest,
        current_user: CurrentUser,
    ) -> CalendarEventResponse:
        with transaction(self.session):
            require_write_access(
                self.session,
                class_id,
                current_user,
                ClassAccessAction.MANAGE_CLASS_CALENDAR,
            )
            event = self.repository.get(event_id, for_update=True)
            if event is None or event.class_id != class_id:
                raise AppError(404)
            if event.origin == CalendarOrigin.LEARNING:
                raise AppError(400, LEARNING_READ_ONLY)
            changes = request.model_dump(exclude_unset=True)
            starts_at = changes.get("starts_at", event.starts_at)
            ends_at = changes.get("ends_at", event.ends_at)
            _validate_interval(starts_at, ends_at)
            for field, value in changes.items():
                setattr(event, field, value)
            self.session.flush()
            return self._response(event)

    def delete_event(
        self,
        class_id: UUID,
        event_id: UUID,
        current_user: CurrentUser,
    ) -> None:
        with transaction(self.session):
            require_write_access(
                self.session,
                class_id,
                current_user,
                ClassAccessAction.MANAGE_CLASS_CALENDAR,
            )
            event = self.repository.get(event_id, for_update=True)
            if event is None or event.class_id != class_id:
                raise AppError(404)
            if event.origin == CalendarOrigin.LEARNING:
                raise AppError(400, LEARNING_READ_ONLY)
            self.repository.delete(event)


def upsert_learning_deadline(
    session: Session,
    *,
    class_id: UUID,
    external_ref: str,
    title: str,
    starts_at: datetime,
    ends_at: datetime,
    version: int,
) -> CalendarEvent:
    """Maintain the read-only deadline projection; awaiting the TASK-019 contract."""
    if not external_ref or not title.strip() or len(title) > 200 or version < 1:
        raise AppError(422, "Invalid Learning deadline")
    _validate_interval(starts_at, ends_at)
    repository = CalendarRepository(session)
    values = {
        "class_id": class_id,
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "version": version,
    }
    with transaction(session):
        # INSERT ... ON CONFLICT: SELECT FOR UPDATE không khóa được dòng chưa tồn tại.
        inserted_id = repository.insert_learning_if_absent(
            {**values, "external_ref": external_ref, "description": None}
        )
        event = repository.get_learning(external_ref, for_update=True)
        if event is None:
            raise AppError(503)
        if inserted_id is None:
            if version <= event.version:
                return event
            for field, value in values.items():
                setattr(event, field, value)
            session.flush()
        record_outbox_event(
            session,
            event_type="CALENDAR_DEADLINE_CHANGED",
            aggregate_id=event.id,
            payload_json={
                "class_id": str(class_id),
                "event_id": str(event.id),
                "external_ref": external_ref,
                "version": version,
            },
        )
        return event

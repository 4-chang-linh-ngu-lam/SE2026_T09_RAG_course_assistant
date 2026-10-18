from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.db import get_db
from app.common.errors import ErrorEnvelope
from app.common.pagination import Pagination, get_pagination
from app.modules.social.calendar.schemas import (
    CalendarEventCreateRequest,
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventUpdateRequest,
)
from app.modules.social.calendar.service import CalendarService

ERROR_RESPONSE = {
    "description": "Error envelope with code, message and correlation_id",
    "model": ErrorEnvelope,
}
router = APIRouter(
    prefix="/api/v1",
    tags=["Social Calendar"],
    responses={status: ERROR_RESPONSE for status in (400, 401, 403, 404, 409, 422, 500, 503)},
)


def get_calendar_service(session: Annotated[Session, Depends(get_db)]) -> CalendarService:
    return CalendarService(session)


Service = Annotated[CalendarService, Depends(get_calendar_service)]
User = Annotated[CurrentUser, Depends(get_current_user)]
PageParam = Annotated[Pagination, Depends(get_pagination)]
FromParam = Annotated[datetime | None, Query(alias="from")]
ToParam = Annotated[datetime | None, Query(alias="to")]


def _json(model: BaseModel, status: int = 200) -> Response:
    return JSONResponse(
        model.model_dump(mode="json"),
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/classes/{class_id}/calendar", response_model=CalendarEventListResponse)
def list_events(
    class_id: UUID,
    user: User,
    pagination: PageParam,
    service: Service,
    from_time: FromParam = None,
    to_time: ToParam = None,
) -> Response:
    return _json(
        service.list_events(
            class_id,
            pagination,
            user,
            from_time=from_time,
            to_time=to_time,
        )
    )


@router.post("/classes/{class_id}/calendar", response_model=CalendarEventResponse, status_code=201)
def create_event(
    class_id: UUID,
    body: CalendarEventCreateRequest,
    user: User,
    service: Service,
) -> Response:
    return _json(service.create_event(class_id, body, user), 201)


@router.patch("/classes/{class_id}/calendar/{event_id}", response_model=CalendarEventResponse)
def update_event(
    class_id: UUID,
    event_id: UUID,
    body: CalendarEventUpdateRequest,
    user: User,
    service: Service,
) -> Response:
    return _json(service.update_event(class_id, event_id, body, user))


@router.delete("/classes/{class_id}/calendar/{event_id}", status_code=204)
def delete_event(
    class_id: UUID,
    event_id: UUID,
    user: User,
    service: Service,
) -> Response:
    service.delete_event(class_id, event_id, user)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})

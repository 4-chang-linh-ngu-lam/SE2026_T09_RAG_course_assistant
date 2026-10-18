from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.db import get_db
from app.common.errors import ErrorEnvelope
from app.common.pagination import Pagination, get_pagination
from app.modules.notification.schemas import MarkReadResponse, NotificationListResponse
from app.modules.notification.service import NotificationService

router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["Notifications"],
    responses={status: {"model": ErrorEnvelope} for status in (400, 401, 404, 422, 500, 503)},
)


def get_notification_service(session: Annotated[Session, Depends(get_db)]) -> NotificationService:
    return NotificationService(session)


User = Annotated[CurrentUser, Depends(get_current_user)]
Service = Annotated[NotificationService, Depends(get_notification_service)]


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    user: User, pagination: Annotated[Pagination, Depends(get_pagination)], service: Service
) -> Response:
    result = service.list_notifications(user.id, pagination)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.patch("/{id}/read", response_model=MarkReadResponse)
def mark_read(id: UUID, user: User, service: Service) -> Response:
    result = service.mark_as_read(id, user.id)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.post("/read-all", status_code=204)
def read_all(user: User, service: Service) -> Response:
    service.mark_all_as_read(user.id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})

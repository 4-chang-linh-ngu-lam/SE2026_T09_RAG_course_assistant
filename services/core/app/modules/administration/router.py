from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, require_roles
from app.common.db import get_db
from app.common.errors import AppError, ErrorEnvelope
from app.common.pagination import Page, Pagination, get_pagination
from app.modules.administration.schemas import (
    AdminCreateUserRequest,
    AdminDataRequestResolve,
    AdminUserRolesRequest,
    AdminUserStatusRequest,
    AuditEventResponse,
    ImportConfirmRequest,
    ImportConfirmResponse,
    ImportPreviewRequest,
    ImportPreviewResponse,
)
from app.modules.administration.service import AdministrationService
from app.modules.identity.public import (
    AdminReason,
    AdminUserReadDTO,
    DataRequestResponse,
    UserSummaryDTO,
    get_token_sender,
)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Administration"],
    responses={status: {"model": ErrorEnvelope} for status in (400, 401, 403, 404, 409, 422, 503)},
)
Admin = Annotated[CurrentUser, Depends(require_roles("ADMIN"))]
PageParam = Annotated[Pagination, Depends(get_pagination)]


def get_service(
    request: Request, session: Annotated[Session, Depends(get_db)]
) -> AdministrationService:
    return AdministrationService(session, UUID(str(request.state.correlation_id)))


def get_reason(value: Annotated[str, Header(alias="X-Admin-Reason")]) -> AdminReason:
    if value not in {"ADMIN_INTERVENTION", "POLICY_VIOLATION", "USER_REQUEST"}:
        raise AppError(400, "Unknown Admin reason code")
    return value


Service = Annotated[AdministrationService, Depends(get_service)]
Reason = Annotated[AdminReason, Depends(get_reason)]


def _json(model: BaseModel, *, status=200) -> Response:
    return JSONResponse(
        model.model_dump(mode="json"), status_code=status, headers={"Cache-Control": "no-store"}
    )


@router.get("/users", response_model=Page[AdminUserReadDTO])
def list_users(user: Admin, pagination: PageParam, service: Service):
    return _json(service.list_users(user.id, pagination))


@router.get("/users/{id}", response_model=AdminUserReadDTO)
def get_user(id: UUID, user: Admin, service: Service):
    return _json(service.get_user(user.id, id))


@router.post("/users", response_model=UserSummaryDTO, status_code=201)
def create_user(
    body: AdminCreateUserRequest,
    user: Admin,
    reason: Reason,
    service: Service,
    sender: Annotated[object, Depends(get_token_sender)],
):
    return _json(service.create_staff(user.id, body, sender, reason), status=201)


@router.patch("/users/{id}/status", status_code=204)
def set_status(
    id: UUID, body: AdminUserStatusRequest, user: Admin, reason: Reason, service: Service
):
    service.set_status(user.id, id, body.status, reason)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.put("/users/{id}/roles", response_model=UserSummaryDTO)
def set_roles(id: UUID, body: AdminUserRolesRequest, user: Admin, reason: Reason, service: Service):
    return _json(service.set_roles(user.id, id, body.roles, reason))


@router.get("/audit-events", response_model=Page[AuditEventResponse])
def list_audits(
    user: Admin,
    pagination: PageParam,
    service: Service,
    actor_id: UUID | None = None,
    action: Annotated[str | None, Query(max_length=100, pattern=r"^[A-Z_]+$")] = None,
    since: AwareDatetime | None = None,
    until: AwareDatetime | None = None,
):
    return _json(
        service.list_audits(
            user.id, pagination, filter_actor=actor_id, action=action, since=since, until=until
        )
    )


@router.get("/data-requests", response_model=Page[DataRequestResponse])
def list_data_requests(user: Admin, pagination: PageParam, service: Service):
    return _json(service.list_data_requests(user.id, pagination))


@router.get("/data-requests/{id}", response_model=DataRequestResponse)
def get_data_request(id: UUID, user: Admin, service: Service):
    return _json(service.get_data_request(user.id, id))


@router.patch("/data-requests/{id}", response_model=DataRequestResponse)
def resolve_data_request(
    id: UUID, body: AdminDataRequestResolve, user: Admin, reason: Reason, service: Service
):
    return _json(service.resolve_data_request(user.id, id, body, reason))


@router.post("/students/imports/preview", response_model=ImportPreviewResponse)
def preview_students(body: ImportPreviewRequest, user: Admin, service: Service):
    return _json(service.preview_students(user.id, body))


@router.post("/students/imports/confirm", response_model=ImportConfirmResponse)
def confirm_students(body: ImportConfirmRequest, user: Admin, reason: Reason, service: Service):
    return _json(service.confirm_students(user.id, body.preview_id, reason))

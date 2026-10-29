import json
from typing import Annotated, Literal
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
    AdminUserUpdateRequest,
    AuditEventResponse,
    ImportConfirmRequest,
    ImportConfirmResponse,
    ImportPreviewRequest,
    ImportPreviewResponse,
    ImportStatusResponse,
)
from app.modules.administration.service import AdministrationService
from app.modules.identity.public import (
    AdminReason,
    AdminUserListItem,
    DataRequestResponse,
    Mutation,
    UserSummaryDTO,
    admin_actor,
    get_mutation,
    get_token_sender,
    get_user_summary,
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
Mutator = Annotated[Mutation, Depends(get_mutation)]


def _json(model: BaseModel, *, status=200, extra_headers: dict[str, str] | None = None) -> Response:
    headers = {"Cache-Control": "no-store", **(extra_headers or {})}
    return JSONResponse(model.model_dump(mode="json"), status_code=status, headers=headers)


def _validate_cached_user_scope(response: Response, actor_id: UUID, session: Session) -> None:
    actor = admin_actor(actor_id, session=session)
    try:
        target_id = UUID(json.loads(response.body)["id"])
    except (KeyError, TypeError, ValueError):
        raise AppError(404) from None
    target = get_user_summary(target_id, session=session)
    if target is None or target.school_id is None or target.school_id != actor.school_id:
        raise AppError(404)


@router.post("/users", response_model=UserSummaryDTO, status_code=201)
def create_user(
    body: AdminCreateUserRequest,
    user: Admin,
    reason: Reason,
    service: Service,
    sender: Annotated[object, Depends(get_token_sender)],
    mutation: Mutator,
):
    def create() -> Response:
        created, delivery_status = service.create_staff(user.id, body, sender, reason)
        return _json(
            created,
            status=201,
            extra_headers={"X-Token-Delivery-Status": delivery_status},
        )

    return mutation.run(
        "user:" + str(user.id),
        {**body.model_dump(mode="json"), "reason_code": reason},
        create,
        lambda response: _validate_cached_user_scope(response, user.id, service.session),
    )


@router.get("/users", response_model=Page[AdminUserListItem])
def list_users(
    user: Admin,
    pagination: PageParam,
    service: Service,
    user_id: UUID | None = None,
    account_type: Annotated[Literal["STUDENT", "STAFF"] | None, Query()] = None,
    role: Annotated[str | None, Query(pattern=r"^(ADMIN|LECTURER|STUDENT)$")] = None,
    status: Annotated[str | None, Query(pattern=r"^(ACTIVE|PENDING_VERIFICATION|LOCKED)$")] = None,
    search: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    username_missing: bool = False,
):
    return _json(
        service.list_users(
            user.id,
            pagination,
            user_id=user_id,
            account_type=account_type,
            role=role,
            status=status,
            search=search,
            username_missing=username_missing,
        )
    )


@router.patch("/users/{id}", response_model=UserSummaryDTO)
def update_user(
    id: UUID,
    body: AdminUserUpdateRequest,
    user: Admin,
    reason: Reason,
    service: Service,
    mutation: Mutator,
):
    def update() -> Response:
        return _json(service.update_user(user.id, id, body, reason))

    return mutation.run(
        "user:" + str(user.id),
        {**body.model_dump(mode="json"), "user_id": str(id), "reason_code": reason},
        update,
        lambda response: _validate_cached_user_scope(response, user.id, service.session),
    )


@router.post("/users/{id}/invitation/reissue", response_model=UserSummaryDTO)
def reissue_user_invitation(
    id: UUID,
    user: Admin,
    reason: Reason,
    service: Service,
    sender: Annotated[object, Depends(get_token_sender)],
    mutation: Mutator,
):
    def reissue() -> Response:
        reissued, delivery_status = service.reissue_staff_invitation(user.id, id, sender, reason)
        return _json(reissued, extra_headers={"X-Token-Delivery-Status": delivery_status})

    return mutation.run(
        "user:" + str(user.id),
        {"user_id": str(id), "reason_code": reason},
        reissue,
        lambda response: _validate_cached_user_scope(response, user.id, service.session),
    )


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


@router.get("/students/imports/{preview_id}", response_model=ImportStatusResponse)
def get_import_status(preview_id: UUID, user: Admin, service: Service):
    return _json(service.import_status(user.id, preview_id))

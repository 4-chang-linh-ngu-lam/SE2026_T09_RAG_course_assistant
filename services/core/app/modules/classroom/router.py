import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, get_current_user, verify_internal_service_key
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import AppError, ErrorEnvelope
from app.common.pagination import Page, Pagination, get_pagination
from app.modules.classroom.models import ClassRole, ClassStatus, MembershipStatus
from app.modules.classroom.permissions import is_admin
from app.modules.classroom.schemas import (
    ClassCreateRequest,
    ClassResponse,
    ClassStatusResponse,
    ClassUpdateRequest,
    CoLecturerInvitationResponse,
    CoLecturerInviteRequest,
    CourseCreateRequest,
    CourseResponse,
    InternalAccessResponse,
    JoinCodeResponse,
    JoinRequestCreatedResponse,
    JoinRequestCreateRequest,
    JoinRequestResponse,
    MembershipResponse,
    OwnershipTransferRequest,
)
from app.modules.classroom.service import ClassroomService
from app.modules.identity.idempotency import Mutation, get_mutation
from app.modules.identity.public import verify_user_active
from app.modules.identity.rate_limit import RateLimiter, get_rate_limiter

logger = logging.getLogger(__name__)


def get_classroom_service(request: Request, session: Annotated[Session, Depends(get_db)]):
    raw = getattr(request.state, "correlation_id", None)
    correlation_id = None
    if raw:
        try:
            correlation_id = UUID(str(raw))
        except ValueError:
            correlation_id = None
    return ClassroomService(session, correlation_id=correlation_id)


Service = Annotated[ClassroomService, Depends(get_classroom_service)]
User = Annotated[CurrentUser, Depends(get_current_user)]
Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]
Mutator = Annotated[Mutation, Depends(get_mutation)]
ServiceScopes = Annotated[frozenset[str], Depends(verify_internal_service_key)]
AdminReason = Annotated[str | None, Header(max_length=512, alias="X-Admin-Reason")]

# Actions any caller may probe through the internal access endpoint.
INTERNAL_ACTIONS = frozenset(
    {"READ_DOCUMENTS", "SUBMIT_ASSESSMENT", "ASK_AI", "VIEW_CLASS", "DOWNLOAD_MATERIALS"}
)
# WRITE actions require an ACTIVE lecturer; the class must not be ARCHIVED.
LECTURER_ONLY_ACTIONS = frozenset({"SUBMIT_ASSESSMENT", "DOWNLOAD_MATERIALS"})

ERROR_RESPONSE = {
    "description": "Error envelope with code, message and correlation_id",
    "model": ErrorEnvelope,
}
router = APIRouter(
    prefix="/api/v1",
    tags=["Classroom"],
    responses={status: ERROR_RESPONSE for status in (400, 401, 403, 404, 409, 422, 429, 500, 503)},
)


def _json(model: BaseModel, status: int = 200) -> Response:
    return JSONResponse(
        model.model_dump(mode="json"), status_code=status, headers={"Cache-Control": "no-store"}
    )


def _empty() -> Response:
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


def _require_admin_reason(user: CurrentUser, admin_reason: str | None) -> None:
    """Endpoints that let an admin bypass class membership demand a stated reason.

    The reason is enforced as present-but-blank-free, never persisted verbatim;
    the audit trail records reason_code=ADMIN_INTERVENTION instead.
    """
    if is_admin(user) and not (admin_reason and admin_reason.strip()):
        raise AppError(400, "X-Admin-Reason is required for admin intervention")


@router.post("/courses", response_model=CourseResponse, status_code=201)
def create_course(body: CourseCreateRequest, user: User, service: Service, mutation: Mutator):
    def perform() -> Response:
        return _json(service.create_course(user, body), 201)

    return mutation.run("course-code:" + body.code, body.model_dump(), perform)


@router.get("/courses", response_model=Page[CourseResponse])
def list_courses(
    user: User, service: Service, pagination: Annotated[Pagination, Depends(get_pagination)]
) -> Response:
    return _json(service.list_courses(pagination))


@router.post("/classes", response_model=JoinCodeResponse, status_code=201)
def create_class(body: ClassCreateRequest, user: User, service: Service, mutation: Mutator):
    def perform() -> Response:
        klass, join_code = service.create_class(user, body)
        return _json(JoinCodeResponse(class_id=klass.id, join_code=join_code), 201)

    return mutation.run("class-create:" + str(body.course_id), body.model_dump(), perform)


@router.get("/classes", response_model=Page[ClassResponse])
def list_my_classes(
    user: User, service: Service, pagination: Annotated[Pagination, Depends(get_pagination)]
) -> Response:
    return _json(service.list_my_classes(user, pagination))


@router.get("/classes/{class_id}", response_model=ClassResponse)
def get_class(class_id: UUID, user: User, service: Service) -> Response:
    return _json(service.get_class(class_id, user))


@router.patch("/classes/{class_id}", response_model=ClassResponse)
def update_class(
    class_id: UUID,
    body: ClassUpdateRequest,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        return _json(service.update_class(class_id, user, body))

    return mutation.run(f"class-update:{class_id}", body.model_dump(), perform)


@router.post("/classes/join-requests", response_model=JoinRequestCreatedResponse, status_code=201)
def create_join_request(
    body: JoinRequestCreateRequest,
    request: Request,
    user: User,
    service: Service,
    limiter: Limiter,
    mutation: Mutator,
):
    def perform() -> Response:
        limiter.consume(
            "join_code",
            str(user.id),
            settings.classroom_join_limit,
            settings.classroom_join_window_seconds,
        )
        return _json(service.create_join_request(user, body.join_code.get_secret_value()), 201)

    return mutation.run("join-request:" + str(user.id), body.model_dump(), perform)


@router.get("/classes/{class_id}/join-requests", response_model=Page[JoinRequestResponse])
def list_join_requests(
    class_id: UUID,
    user: User,
    service: Service,
    pagination: Annotated[Pagination, Depends(get_pagination)],
    pending_only: Annotated[bool, Query()] = False,
) -> Response:
    return _json(service.list_join_requests(class_id, user, pagination, pending_only=pending_only))


@router.post(
    "/classes/{class_id}/join-requests/{request_id}/approve", response_model=MembershipResponse
)
def approve_join_request(
    class_id: UUID,
    request_id: UUID,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        return _json(service.approve_join_request(class_id, request_id, user))

    return mutation.run(f"join-approve:{request_id}", {}, perform)


@router.post(
    "/classes/{class_id}/join-requests/{request_id}/reject", response_model=JoinRequestResponse
)
def reject_join_request(
    class_id: UUID,
    request_id: UUID,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        return _json(service.reject_join_request(class_id, request_id, user))

    return mutation.run(f"join-reject:{request_id}", {}, perform)


@router.post(
    "/classes/{class_id}/join-requests/{request_id}/cancel", response_model=JoinRequestResponse
)
def cancel_join_request(
    class_id: UUID, request_id: UUID, user: User, service: Service, mutation: Mutator
) -> Response:
    def perform() -> Response:
        return _json(service.cancel_join_request(class_id, request_id, user))

    return mutation.run(f"join-cancel:{request_id}", {}, perform)


@router.get("/classes/{class_id}/members", response_model=Page[MembershipResponse])
def list_members(
    class_id: UUID,
    user: User,
    service: Service,
    pagination: Annotated[Pagination, Depends(get_pagination)],
) -> Response:
    return _json(service.list_members(class_id, user, pagination))


@router.delete("/classes/{class_id}/members/me", status_code=204)
def leave_class(class_id: UUID, user: User, service: Service, mutation: Mutator) -> Response:
    def perform() -> Response:
        service.leave_class(class_id, user)
        return _empty()

    return mutation.run(f"leave:{class_id}", {}, perform)


@router.delete("/classes/{class_id}/members/{user_id}", status_code=204)
def remove_member(
    class_id: UUID,
    user_id: UUID,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        service.remove_member(class_id, user_id, user)
        return _empty()

    return mutation.run(f"remove:{class_id}:{user_id}", {}, perform)


@router.post("/classes/{class_id}/members/{user_id}/readmit", response_model=MembershipResponse)
def readmit_student(
    class_id: UUID,
    user_id: UUID,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    """Lecturer re-admits a REMOVED student (API_CONTRACT: rejoining needs permission)."""
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        return _json(service.readmit_student(class_id, user_id, user))

    return mutation.run(f"readmit:{class_id}:{user_id}", {}, perform)


@router.post(
    "/classes/{class_id}/co-lecturers/invitations",
    response_model=CoLecturerInvitationResponse,
    status_code=201,
)
def invite_co_lecturer(
    class_id: UUID,
    body: CoLecturerInviteRequest,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        return _json(service.invite_co_lecturer(class_id, user, body), 201)

    return mutation.run(f"invite:{class_id}", body.model_dump(), perform)


@router.post(
    "/classes/{class_id}/co-lecturers/invitations/{invitation_id}/accept",
    response_model=CoLecturerInvitationResponse,
)
def accept_co_lecturer_invitation(
    class_id: UUID, invitation_id: UUID, user: User, service: Service, mutation: Mutator
) -> Response:
    def perform() -> Response:
        return _json(service.accept_co_lecturer_invitation(class_id, invitation_id, user))

    return mutation.run(f"invitation-accept:{invitation_id}", {}, perform)


@router.post(
    "/classes/{class_id}/co-lecturers/invitations/{invitation_id}/reject",
    response_model=CoLecturerInvitationResponse,
)
def reject_co_lecturer_invitation(
    class_id: UUID, invitation_id: UUID, user: User, service: Service, mutation: Mutator
) -> Response:
    def perform() -> Response:
        return _json(service.reject_co_lecturer_invitation(class_id, invitation_id, user))

    return mutation.run(f"invitation-reject:{invitation_id}", {}, perform)


@router.post(
    "/classes/{class_id}/co-lecturers/invitations/{invitation_id}/cancel",
    response_model=CoLecturerInvitationResponse,
)
def cancel_co_lecturer_invitation(
    class_id: UUID,
    invitation_id: UUID,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    """Owner withdraws a pending invitation; expired pending rows retire via re-invite."""
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        return _json(service.cancel_co_lecturer_invitation(class_id, invitation_id, user))

    return mutation.run(f"invitation-cancel:{invitation_id}", {}, perform)


@router.post("/classes/{class_id}/ownership-transfer", response_model=ClassResponse)
def transfer_ownership(
    class_id: UUID,
    body: OwnershipTransferRequest,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        return _json(service.transfer_ownership(class_id, user, body))

    return mutation.run(f"transfer:{class_id}", body.model_dump(), perform)


@router.post("/classes/{class_id}/archive", response_model=ClassStatusResponse)
def archive_class(
    class_id: UUID,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        klass = service.archive_class(class_id, user)
        return _json(ClassStatusResponse(class_id=klass.id, status=klass.status))

    return mutation.run(f"archive:{class_id}", {}, perform)


@router.post("/classes/{class_id}/restore", response_model=ClassStatusResponse)
def restore_class(
    class_id: UUID,
    user: User,
    service: Service,
    mutation: Mutator,
    admin_reason: AdminReason = None,
) -> Response:
    _require_admin_reason(user, admin_reason)

    def perform() -> Response:
        klass = service.restore_class(class_id, user)
        return _json(ClassStatusResponse(class_id=klass.id, status=klass.status))

    return mutation.run(f"restore:{class_id}", {}, perform)


# -- Internal service API (no browser access; fail closed) -------------------------

internal_router = APIRouter(
    prefix="/internal/v1",
    tags=["Internal"],
    responses={status: ERROR_RESPONSE for status in (401, 403, 500, 503)},
)


def _denied(class_id: UUID, user_id: UUID, action: str, **extra) -> InternalAccessResponse:
    return InternalAccessResponse(
        allowed=False, class_id=class_id, user_id=user_id, action=action, **extra
    )


@internal_router.get("/classes/{class_id}/access", response_model=InternalAccessResponse)
def check_class_access(
    class_id: UUID,
    user_id: UUID,
    action: Annotated[str, Query(max_length=64)],
    scopes: ServiceScopes,
    service: Service,
) -> InternalAccessResponse:
    """Service-to-service membership check; any unverifiable condition denies access."""
    if action not in INTERNAL_ACTIONS:
        return _denied(class_id, user_id, action)
    try:
        return _evaluate_class_access(service, class_id, user_id, action)
    except Exception:
        # Fail closed: an internal error must never open access.
        logger.exception("check_class_access failed; denying")
        return _denied(class_id, user_id, action)


def _evaluate_class_access(
    service: ClassroomService, class_id: UUID, user_id: UUID, action: str
) -> InternalAccessResponse:
    klass = service.repository.get_class_by_id(class_id)
    if klass is None:
        return _denied(class_id, user_id, action)
    if not verify_user_active(user_id, session=service.session):
        # A locked/archived account loses access even with an ACTIVE membership row.
        return _denied(class_id, user_id, action, class_status=klass.status.value)
    membership = service.repository.get_active_membership(class_id, user_id)
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        return _denied(class_id, user_id, action, class_status=klass.status.value)
    allowed = True
    if action == "ASK_AI" and klass.status == ClassStatus.ARCHIVED:
        allowed = False  # Archived classes accept no new AI questions (Rule H5).
    if action == "VIEW_CLASS" and klass.status == ClassStatus.ARCHIVED:
        allowed = True  # Read-only view survives archive; writes are rejected elsewhere.
    if action in LECTURER_ONLY_ACTIONS and membership.class_role not in {
        ClassRole.OWNER,
        ClassRole.CO_LECTURER,
    }:
        allowed = False
    return InternalAccessResponse(
        allowed=allowed,
        class_id=class_id,
        user_id=user_id,
        action=action,
        class_role=membership.class_role.value,
        class_status=klass.status.value,
    )

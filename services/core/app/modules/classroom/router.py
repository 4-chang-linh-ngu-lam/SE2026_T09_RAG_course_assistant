from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, get_current_user, verify_internal_service_key
from app.common.db import get_db
from app.common.errors import AppError, ErrorEnvelope
from app.common.pagination import Page, Pagination, get_pagination
from app.modules.classroom.permissions import require_admin
from app.modules.classroom.public import check_class_action
from app.modules.classroom.schemas import (
    ClassAccessAction,
    ClassCreateRequest,
    ClassResponse,
    CourseCreateRequest,
    CourseResponse,
    EnrollmentModeRequest,
    EnrollmentPreviewResponse,
    HomeroomCreateRequest,
    HomeroomResponse,
    HomeroomTransferRequest,
    InternalAccessResponse,
    MembershipRequest,
    MembershipResponse,
    RosterRequest,
    RosterResponse,
    TeachingAssignmentResponse,
    TeachingAssignmentsRequest,
    TransferRequest,
)
from app.modules.classroom.service import ClassroomService
from app.modules.identity.idempotency import Mutation, get_mutation

User = Annotated[CurrentUser, Depends(get_current_user)]
Mutator = Annotated[Mutation, Depends(get_mutation)]
ServiceScopes = Annotated[frozenset[str], Depends(verify_internal_service_key)]
REASON_CODES = frozenset({"ADMIN_INTERVENTION", "POLICY_VIOLATION", "USER_REQUEST"})
ERROR_RESPONSE = {"model": ErrorEnvelope, "description": "Core error envelope"}

router = APIRouter(
    prefix="/api/v1",
    tags=["Classroom"],
    responses={status: ERROR_RESPONSE for status in (400, 401, 403, 404, 409, 422, 429, 503)},
)
internal_router = APIRouter(
    prefix="/internal/v1",
    tags=["Internal"],
    responses={status: ERROR_RESPONSE for status in (400, 401, 403, 404, 422, 503)},
)


def get_classroom_service(request: Request, session: Annotated[Session, Depends(get_db)]):
    raw = getattr(request.state, "correlation_id", None)
    reason_code = request.headers.get("X-Admin-Reason")
    if reason_code is not None and reason_code not in REASON_CODES:
        raise AppError(400, "Unknown Admin reason code")
    return ClassroomService(
        session,
        correlation_id=UUID(str(raw)) if raw else None,
        reason_code=reason_code or "ADMIN_INTERVENTION",
        reason_supplied=reason_code is not None,
    )


Service = Annotated[ClassroomService, Depends(get_classroom_service)]


def _json(model: BaseModel | list[BaseModel], status: int = 200) -> Response:
    if isinstance(model, list):
        body = [item.model_dump(mode="json") for item in model]
    else:
        body = model.model_dump(mode="json")
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def _mutate(
    actor: CurrentUser,
    service: ClassroomService,
    mutation: Mutation,
    scope: str,
    payload: dict,
    operation,
    *,
    reason_required: bool = False,
) -> Response:
    require_admin(actor)
    if reason_required and not service.reason_supplied:
        raise AppError(400, "X-Admin-Reason is required")
    return mutation.run(
        f"{actor.id}:{scope}",
        {**payload, "reason_code": service.reason_code},
        operation,
        validate_cached=lambda _: require_admin(actor),
    )


@router.post("/admin/courses", response_model=CourseResponse, status_code=201)
def create_course(body: CourseCreateRequest, user: User, service: Service, mutation: Mutator):
    return _mutate(
        user,
        service,
        mutation,
        "course",
        body.model_dump(mode="json"),
        lambda: _json(service.create_course(user, body), 201),
    )


@router.post("/admin/homeroom-classes", response_model=HomeroomResponse, status_code=201)
def create_homeroom(body: HomeroomCreateRequest, user: User, service: Service, mutation: Mutator):
    return _mutate(
        user,
        service,
        mutation,
        "homeroom",
        body.model_dump(mode="json"),
        lambda: _json(service.create_homeroom(user, body), 201),
    )


@router.put("/admin/homeroom-classes/{homeroom_id}/roster", response_model=RosterResponse)
def set_roster(
    homeroom_id: UUID, body: RosterRequest, user: User, service: Service, mutation: Mutator
):
    return _mutate(
        user,
        service,
        mutation,
        f"roster:{homeroom_id}",
        body.model_dump(mode="json"),
        lambda: _json(service.set_roster(user, homeroom_id, body.student_ids)),
        reason_required=True,
    )


@router.post(
    "/admin/homeroom-classes/{homeroom_id}/students/{student_id}/transfer",
    response_model=RosterResponse,
)
def transfer_homeroom_student(
    homeroom_id: UUID,
    student_id: UUID,
    body: HomeroomTransferRequest,
    user: User,
    service: Service,
    mutation: Mutator,
):
    return _mutate(
        user,
        service,
        mutation,
        f"homeroom-transfer:{homeroom_id}:{student_id}",
        body.model_dump(mode="json"),
        lambda: _json(
            service.transfer_homeroom_student(
                homeroom_id, body.destination_homeroom_id, student_id, user
            )
        ),
        reason_required=True,
    )


@router.post("/admin/classes", response_model=ClassResponse, status_code=201)
def create_class(body: ClassCreateRequest, user: User, service: Service, mutation: Mutator):
    return _mutate(
        user,
        service,
        mutation,
        "class",
        body.model_dump(mode="json"),
        lambda: _json(service.create_class(user, body), 201),
    )


@router.get("/classes", response_model=Page[ClassResponse])
def list_classes(
    user: User, service: Service, pagination: Annotated[Pagination, Depends(get_pagination)]
):
    return _json(service.list_classes(user, pagination))


@router.get("/classes/{class_id}", response_model=ClassResponse)
def get_class(class_id: UUID, user: User, service: Service):
    return _json(service.get_class(class_id, user))


@router.get("/classes/{class_id}/members", response_model=list[MembershipResponse])
def list_members(class_id: UUID, user: User, service: Service):
    return _json(service.list_members(class_id, user))


@router.put(
    "/admin/classes/{class_id}/teaching-assignments",
    response_model=list[TeachingAssignmentResponse],
)
def set_teachers(
    class_id: UUID,
    body: TeachingAssignmentsRequest,
    user: User,
    service: Service,
    mutation: Mutator,
):
    return _mutate(
        user,
        service,
        mutation,
        f"teachers:{class_id}",
        body.model_dump(mode="json"),
        lambda: _json(service.set_teachers(class_id, user, body)),
        reason_required=True,
    )


@router.post(
    "/admin/classes/{class_id}/enrollment/preview", response_model=EnrollmentPreviewResponse
)
def preview_auto(class_id: UUID, user: User, service: Service):
    require_admin(user)
    return _json(service.preview_auto(class_id, user))


@router.patch("/admin/classes/{class_id}/enrollment-mode", response_model=ClassResponse)
def set_enrollment_mode(
    class_id: UUID,
    body: EnrollmentModeRequest,
    user: User,
    service: Service,
    mutation: Mutator,
):
    return _mutate(
        user,
        service,
        mutation,
        f"mode:{class_id}",
        body.model_dump(mode="json"),
        lambda: _json(service.set_enrollment_mode(class_id, user, body)),
        reason_required=True,
    )


@router.post("/admin/classes/{class_id}/enrollment/sync", response_model=ClassResponse)
def sync_enrollment(class_id: UUID, user: User, service: Service, mutation: Mutator):
    return _mutate(
        user,
        service,
        mutation,
        f"sync:{class_id}",
        {},
        lambda: _json(service.sync_enrollment(class_id, user)),
        reason_required=True,
    )


@router.post(
    "/admin/classes/{class_id}/members", response_model=MembershipResponse, status_code=201
)
def add_member(
    class_id: UUID, body: MembershipRequest, user: User, service: Service, mutation: Mutator
):
    return _mutate(
        user,
        service,
        mutation,
        f"member:{class_id}",
        body.model_dump(mode="json"),
        lambda: _json(service.add_member(class_id, user, body.student_id), 201),
        reason_required=True,
    )


@router.delete("/admin/classes/{class_id}/members/{student_id}", status_code=204)
def end_member(class_id: UUID, student_id: UUID, user: User, service: Service, mutation: Mutator):
    def perform():
        service.end_member(class_id, user, student_id)
        return Response(status_code=204)

    return _mutate(
        user,
        service,
        mutation,
        f"member-end:{class_id}:{student_id}",
        {},
        perform,
        reason_required=True,
    )


@router.post(
    "/admin/classes/{class_id}/members/{student_id}/transfer",
    response_model=MembershipResponse,
)
def transfer_member(
    class_id: UUID,
    student_id: UUID,
    body: TransferRequest,
    user: User,
    service: Service,
    mutation: Mutator,
):
    return _mutate(
        user,
        service,
        mutation,
        f"transfer:{class_id}:{student_id}",
        body.model_dump(mode="json"),
        lambda: _json(service.transfer(class_id, body.destination_class_id, student_id, user)),
        reason_required=True,
    )


@router.post("/admin/classes/{class_id}/archive", response_model=ClassResponse)
def archive_class(class_id: UUID, user: User, service: Service, mutation: Mutator):
    return _mutate(
        user,
        service,
        mutation,
        f"archive:{class_id}",
        {},
        lambda: _json(service.set_archived(class_id, user, archived=True)),
        reason_required=True,
    )


@router.post("/admin/classes/{class_id}/restore", response_model=ClassResponse)
def restore_class(class_id: UUID, user: User, service: Service, mutation: Mutator):
    return _mutate(
        user,
        service,
        mutation,
        f"restore:{class_id}",
        {},
        lambda: _json(service.set_archived(class_id, user, archived=False)),
        reason_required=True,
    )


@internal_router.get("/classes/{class_id}/access", response_model=InternalAccessResponse)
def check_class_access(
    class_id: UUID,
    user_id: UUID,
    action: ClassAccessAction,
    scopes: ServiceScopes,
    service: Service,
) -> InternalAccessResponse:
    if "core:check_access" not in scopes:
        raise AppError(403)
    decision = check_class_action(class_id, user_id, action, session=service.session)
    return InternalAccessResponse(**decision.model_dump(), user_id=user_id, action=action)

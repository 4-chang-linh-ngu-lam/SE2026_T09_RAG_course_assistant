import json
import logging
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, get_current_user, require_roles
from app.common.config import settings
from app.common.db import get_db, transaction
from app.common.errors import AppError, ErrorEnvelope
from app.common.pagination import Page, Pagination, get_pagination
from app.common.security import hash_refresh_token
from app.modules.identity.email_delivery import SMTPTokenSender, get_token_sender
from app.modules.identity.http_security import (
    COOKIE_PATH,
    REFRESH_COOKIE,
    client_identity,
    verify_cookie_origin,
)
from app.modules.identity.idempotency import Mutation, get_mutation
from app.modules.identity.rate_limit import RateLimiter, get_rate_limiter
from app.modules.identity.schemas import (
    ActivateStudentRequest,
    AdminCreateStudentRequest,
    CreateDataRequest,
    DataRequestResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    IssueStudentCodeRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    StudentCodeResponse,
    TokenResponse,
    UpdateProfileRequest,
    UserProfile,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.modules.identity.service import AuthTokens, IdentityService, StudentCode

logger = logging.getLogger(__name__)


def get_identity_service(session: Annotated[Session, Depends(get_db)]) -> IdentityService:
    return IdentityService(session)


Service = Annotated[IdentityService, Depends(get_identity_service)]
User = Annotated[CurrentUser, Depends(get_current_user)]
Admin = Annotated[CurrentUser, Depends(require_roles("ADMIN"))]
Sender = Annotated[SMTPTokenSender, Depends(get_token_sender)]
Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]
Mutator = Annotated[Mutation, Depends(get_mutation)]
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE, max_length=256)]

ERROR_RESPONSE = {
    "description": "Error envelope with code, message and correlation_id",
    "model": ErrorEnvelope,
}
router = APIRouter(
    prefix="/api/v1",
    tags=["Identity"],
    responses={status: ERROR_RESPONSE for status in (400, 401, 403, 409, 422, 429, 500, 503)},
)


def _json(model: BaseModel, status: int = 200) -> Response:
    return JSONResponse(
        model.model_dump(mode="json"), status_code=status, headers={"Cache-Control": "no-store"}
    )


def _empty() -> Response:
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


def _tokens(tokens: AuthTokens) -> Response:
    response = _json(tokens.response)
    refresh_expires_at = tokens.refresh_expires_at
    if refresh_expires_at.tzinfo is None or refresh_expires_at.utcoffset() is None:
        raise ValueError("Refresh token expiry must be timezone-aware")
    refresh_expires_at = refresh_expires_at.astimezone(UTC)
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token.get_secret_value(),
        max_age=max(0, int((refresh_expires_at - datetime.now(UTC)).total_seconds())),
        expires=refresh_expires_at,
        path=COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=settings.cookie_httponly,
        samesite=settings.cookie_samesite,
    )
    return response


def _clear_cookie(response: Response) -> Response:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=settings.cookie_httponly,
        samesite=settings.cookie_samesite,
    )
    return response


def _validate_cached_tokens(response: Response, service: IdentityService) -> None:
    cookies = SimpleCookie()
    cookies.load(response.headers["set-cookie"])
    refresh = cookies[REFRESH_COOKIE].value
    model = TokenResponse.model_validate(json.loads(response.body))
    expiry = service.validate_cached_refresh(refresh, model.access_token)
    # Recalculate Max-Age so replay cannot extend the browser cookie beyond the DB expiry.
    response.raw_headers = _tokens(AuthTokens(model, SecretStr(refresh), expiry)).raw_headers


@router.post("/auth/register", deprecated=True, status_code=403, response_model=ErrorEnvelope)
def register(body: RegisterRequest) -> Response:
    # Resolve no DB/SMTP/cache dependency: legacy retries must not create another Student.
    raise AppError(403, "Student accounts must be provisioned by an administrator")


@router.post("/auth/verify-email", response_model=VerifyEmailResponse)
def verify_email(
    body: VerifyEmailRequest,
    request: Request,
    service: Service,
    limiter: Limiter,
    mutation: Mutator,
) -> Response:
    def perform() -> Response:
        limiter.consume(
            "verify",
            client_identity(request),
            settings.auth_reset_limit,
            settings.auth_login_window_seconds,
        )
        service.verify_email(body)
        return _json(VerifyEmailResponse())

    return mutation.run(
        "token:" + hash_refresh_token(body.token.get_secret_value()), body.model_dump(), perform
    )


@router.post("/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest, request: Request, service: Service, limiter: Limiter, mutation: Mutator
) -> Response:
    def perform() -> Response:
        with limiter.login_attempt(client_identity(request), body.login_key):
            return _tokens(service.login(body))

    def validate_cached(response: Response) -> None:
        with limiter.login_attempt(client_identity(request), body.login_key):
            service.validate_cached_login(body, json.loads(response.body)["access_token"])
            _validate_cached_tokens(response, service)

    # Origin is checked before a cached response can set a cookie as well.
    if "origin" in request.headers:
        verify_cookie_origin(request)
    return mutation.run(body.login_key, body.model_dump(), perform, validate_cached)


@router.post("/auth/activate", status_code=204)
def activate_student(
    body: ActivateStudentRequest,
    request: Request,
    service: Service,
    limiter: Limiter,
) -> Response:
    _reject_code_idempotency(request)
    limiter.consume(
        "activate",
        client_identity(request),
        settings.auth_reset_limit,
        settings.auth_login_window_seconds,
    )
    service.activate_student(body, correlation_id=UUID(request.state.correlation_id))
    return _clear_cookie(_empty())


def _reject_code_idempotency(request: Request) -> None:
    # One-time code disclosures/consumption are never stored in the response cache.
    if "idempotency-key" in request.headers:
        raise AppError(400, "Idempotency-Key is not supported for one-time code operations")


def _student_code_response(result: StudentCode, status: int) -> Response:
    return _json(
        StudentCodeResponse(
            student=result.student,
            purpose=result.purpose,
            code=result.code.get_secret_value(),
            expires_at=result.expires_at,
        ),
        status,
    )


@router.post("/admin/students", response_model=StudentCodeResponse, status_code=201)
def create_student(
    body: AdminCreateStudentRequest,
    request: Request,
    actor: Admin,
    service: Service,
) -> Response:
    _reject_code_idempotency(request)
    with transaction(service.session):
        result = service.admin_create_student(
            body, actor_id=actor.id, correlation_id=UUID(request.state.correlation_id)
        )
    return _student_code_response(result, 201)


@router.post("/admin/students/{user_id}/activation-codes", response_model=StudentCodeResponse)
def issue_student_code(
    user_id: UUID,
    body: IssueStudentCodeRequest,
    request: Request,
    actor: Admin,
    service: Service,
) -> Response:
    _reject_code_idempotency(request)
    with transaction(service.session):
        result = service.admin_issue_student_code(
            user_id,
            actor_id=actor.id,
            correlation_id=UUID(request.state.correlation_id),
            identity_verified=body.identity_verified,
        )
    return _student_code_response(result, 200)


@router.post(
    "/auth/refresh", response_model=TokenResponse, dependencies=[Depends(verify_cookie_origin)]
)
def refresh(service: Service, mutation: Mutator, token: RefreshCookie = None) -> Response:
    if not token:
        raise AppError(401)

    def validate_cached(response: Response) -> None:
        _validate_cached_tokens(response, service)

    return mutation.run(
        "user:" + str(service.get_refresh_owner(token)),
        {"refresh_token": token},
        lambda: _tokens(service.refresh(token)),
        validate_cached,
    )


@router.post("/auth/logout", status_code=204, dependencies=[Depends(verify_cookie_origin)])
def logout(service: Service, mutation: Mutator, token: RefreshCookie = None) -> Response:
    def perform() -> Response:
        if token:
            service.logout(token)
        return _clear_cookie(_empty())

    return mutation.run(
        "refresh:" + hash_refresh_token(token or ""), {"refresh_token": token}, perform
    )


@router.post("/auth/logout-all", status_code=204)
def logout_all(user: User, service: Service, mutation: Mutator) -> Response:
    def perform() -> Response:
        service.logout_all(user.id)
        return _clear_cookie(_empty())

    return mutation.run("user:" + str(user.id), {}, perform)


@router.post("/auth/password/forgot", response_model=ForgotPasswordResponse)
def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    service: Service,
    sender: Sender,
    limiter: Limiter,
    mutation: Mutator,
) -> Response:
    def perform() -> Response:
        limiter.consume(
            "forgot",
            client_identity(request),
            settings.auth_forgot_limit,
            settings.auth_request_window_seconds,
        )
        delivery = service.forgot_password(body)
        if delivery is not None and delivery.token_id is not None:
            status = service.attempt_token_delivery(delivery.token_id, sender.send)
            if status != "DELIVERED":
                # Keep the response generic; do not reveal account existence or provider details.
                logger.warning(
                    "Chưa thể hoàn tất email khôi phục; hệ thống sẽ xử lý tiếp theo lịch. "
                    "Mã theo dõi %s.",
                    request.state.correlation_id,
                )
        return _json(ForgotPasswordResponse())

    return mutation.run("email:" + body.email, body.model_dump(), perform)


@router.post("/auth/password/reset", status_code=204)
def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    service: Service,
    limiter: Limiter,
    mutation: Mutator,
) -> Response:
    def perform() -> Response:
        limiter.consume(
            "reset",
            client_identity(request),
            settings.auth_reset_limit,
            settings.auth_login_window_seconds,
        )
        service.reset_password(body, correlation_id=UUID(request.state.correlation_id))
        return _clear_cookie(_empty())

    return mutation.run(
        "token:" + hash_refresh_token(body.token.get_secret_value()), body.model_dump(), perform
    )


@router.get("/users/me", response_model=UserProfile)
def get_profile(user: User, service: Service) -> Response:
    return _json(service.get_profile(user.id))


@router.patch("/users/me", response_model=UserProfile)
def update_profile(
    body: UpdateProfileRequest, user: User, service: Service, mutation: Mutator
) -> Response:
    return mutation.run(
        "user:" + str(user.id),
        body.model_dump(exclude_unset=True),
        lambda: _json(service.update_profile(user.id, body)),
    )


@router.get("/users/me/data-requests", response_model=Page[DataRequestResponse])
def list_data_requests(
    user: User,
    service: Service,
    pagination: Annotated[Pagination, Depends(get_pagination)],
) -> Response:
    return _json(service.list_data_requests(user.id, pagination))


@router.post("/users/me/data-requests", response_model=DataRequestResponse, status_code=201)
def create_data_request(
    body: CreateDataRequest,
    user: User,
    service: Service,
    mutation: Mutator,
) -> Response:
    return mutation.run(
        "user:" + str(user.id),
        body.model_dump(mode="json"),
        lambda: _json(service.create_data_request(user.id, body), 201),
    )

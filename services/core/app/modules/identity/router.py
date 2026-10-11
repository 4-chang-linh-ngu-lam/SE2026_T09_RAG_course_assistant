import json
import logging
from datetime import UTC, datetime
from http.cookies import SimpleCookie
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.config import settings
from app.common.db import get_db
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
    CreateDataRequest,
    DataRequestResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserProfile,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.modules.identity.service import AuthTokens, IdentityService

logger = logging.getLogger(__name__)


def get_identity_service(session: Annotated[Session, Depends(get_db)]) -> IdentityService:
    return IdentityService(session)


Service = Annotated[IdentityService, Depends(get_identity_service)]
User = Annotated[CurrentUser, Depends(get_current_user)]
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
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token.get_secret_value(),
        max_age=max(0, int((tokens.refresh_expires_at - datetime.now(UTC)).total_seconds())),
        expires=tokens.refresh_expires_at,
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


@router.post("/auth/register", response_model=RegisterResponse, status_code=201)
def register(
    body: RegisterRequest,
    request: Request,
    service: Service,
    sender: Sender,
    limiter: Limiter,
    mutation: Mutator,
) -> Response:
    def perform() -> Response:
        limiter.consume(
            "register",
            client_identity(request),
            settings.auth_register_limit,
            settings.auth_request_window_seconds,
        )
        result = service.register(body, deliver=sender.send)
        return _json(result.response, 201)

    return mutation.run("email:" + body.email, body.model_dump(), perform)


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
        with limiter.login_attempt(client_identity(request), body.email):
            return _tokens(service.login(body))

    def validate_cached(response: Response) -> None:
        with limiter.login_attempt(client_identity(request), body.email):
            service.validate_cached_login(body, json.loads(response.body)["access_token"])
            _validate_cached_tokens(response, service)

    # Origin is checked before a cached response can set a cookie as well.
    if "origin" in request.headers:
        verify_cookie_origin(request)
    return mutation.run("email:" + body.email, body.model_dump(), perform, validate_cached)


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
        try:
            service.forgot_password(body, deliver=sender.send)
        except AppError as exc:
            if exc.status_code != 503:
                raise
            # Preserve the generic response on delivery failure without exposing account existence.
            logger.error("Password reset email delivery failed")
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
        service.reset_password(body)
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

from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}


class ErrorDetail(BaseModel):
    code: str
    message: str
    correlation_id: UUID


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class AppError(HTTPException):
    def __init__(self, status_code: int, message: str | None = None):
        super().__init__(status_code, message or ERROR_CODES.get(status_code, "HTTP_ERROR"))


def error_response(request: Request, status: int, message: str, headers=None) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": ERROR_CODES.get(status, "HTTP_ERROR"),
                "message": message,
                "correlation_id": correlation_id,
            }
        },
        headers={
            **(headers or {}),
            "X-Correlation-ID": correlation_id,
            "Cache-Control": "no-store",
        },
    )


class CorrelationIdMiddleware:
    """Attach correlation metadata without splitting a request into extra tasks."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            correlation_id = str(UUID(Headers(scope=scope).get("X-Correlation-ID", "")))
        except ValueError:
            correlation_id = str(uuid4())
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def correlated_send(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Correlation-ID"] = correlation_id
            await send(message)

        await self.app(scope, receive, correlated_send)


def register_error_handlers(app: FastAPI) -> None:
    app.add_middleware(CorrelationIdMiddleware)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        # Never expose arbitrary exception detail or resource information for hidden resources.
        message = ERROR_CODES.get(exc.status_code, "HTTP_ERROR")
        if isinstance(exc, AppError) and exc.status_code != 404:
            message = str(exc.detail)
        return error_response(request, exc.status_code, message, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic errors can include passwords/tokens in the input field.
        return error_response(request, 422, "Invalid request")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return error_response(request, 500, "Internal server error")

from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
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


def register_error_handlers(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        try:
            correlation_id = str(UUID(request.headers.get("X-Correlation-ID", "")))
        except ValueError:
            correlation_id = str(uuid4())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

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

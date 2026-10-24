import re
from tempfile import TemporaryFile
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.auth import CoreGateway, get_access
from app.config import settings
from app.db import SessionLocal
from app.errors import DocumentError
from app.models import Document
from app.routes import internal, router

app = FastAPI(title="RAG Course Assistant — Document", version="0.1.0")
app.state.core = CoreGateway()


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_upload = scope.get("method") == "POST" and re.fullmatch(
            r"/api/v1/documents(?:/[0-9a-fA-F-]{36}/versions)?", scope.get("path", "")
        )
        size, maximum = 0, settings.max_file_size_bytes + 65536 if is_upload else 65536

        async def bounded():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > maximum:
                raise HTTPException(413, "Tệp vượt giới hạn tải lên.")
            return message

        await self.app(scope, bounded, send)


app.add_middleware(BodyLimit)


@app.middleware("http")
async def correlation(request: Request, call_next):
    incoming = request.headers.get("X-Correlation-ID", "")
    try:
        request.state.correlation_id = str(UUID(incoming)) if len(incoming) == 36 else str(uuid4())
    except ValueError:
        request.state.correlation_id = str(uuid4())
    # Reject invalid sessions before multipart parsing/spooling. Mutations also
    # re-check identity in the endpoint dependency after the body has arrived.
    if request.url.path.startswith("/api/v1/"):
        try:
            request.state.document_access = await run_in_threadpool(get_access, request)
        except DocumentError as error:
            return error_response(request, error.status, error.code, error.message)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Correlation-ID"] = request.state.correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def error_response(request, status, code, message):
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    return JSONResponse(
        {"error": {"code": code, "message": message}, "correlation_id": correlation_id},
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Correlation-ID": correlation_id},
    )


@app.exception_handler(DocumentError)
async def document_error(request, error):
    return error_response(request, error.status, error.code, error.message)


@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    return error_response(request, 422, "VALIDATION_ERROR", "Thông tin yêu cầu chưa hợp lệ.")


@app.exception_handler(HTTPException)
async def http_error(request, error):
    return error_response(
        request,
        error.status_code,
        "FILE_TOO_LARGE" if error.status_code == 413 else "REQUEST_FAILED",
        "Yêu cầu chưa hợp lệ.",
    )


@app.exception_handler(SQLAlchemyError)
async def database_error(request, error):
    return error_response(request, 503, "DATABASE_UNAVAILABLE", "Dịch vụ dữ liệu chưa sẵn sàng.")


@app.exception_handler(OSError)
async def storage_error(request, error):
    return error_response(request, 503, "STORAGE_UNAVAILABLE", "Dịch vụ lưu trữ chưa sẵn sàng.")


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    with SessionLocal() as session:
        session.execute(select(Document.id).limit(1))
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    with TemporaryFile(dir=settings.storage_root) as probe:
        probe.write(b"ready")
        probe.flush()
    if settings.internal_service_secret is None:
        raise DocumentError(503, "CONFIGURATION_ERROR", "Chưa cấu hình quyền Core.")
    app.state.core.request("/health/ready")
    return {"status": "ready"}


app.include_router(router)
app.include_router(internal)

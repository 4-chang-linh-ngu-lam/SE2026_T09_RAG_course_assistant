from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap import register_routers
from app.common.admission import DatabaseAdmissionMiddleware
from app.common.config import settings
from app.common.errors import register_error_handlers

app = FastAPI(title="RAG Course Assistant — Core", version="0.1.0")
app.add_middleware(
    DatabaseAdmissionMiddleware,
    capacity=max(1, settings.database_pool_size + settings.database_max_overflow - 1),
    timeout=settings.database_pool_timeout_seconds,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-CSRF-Token",
        "Idempotency-Key",
        "X-Correlation-ID",
        "X-Admin-Reason",
    ],
    expose_headers=["X-Correlation-ID"],
)
register_error_handlers(app)
register_routers(app)

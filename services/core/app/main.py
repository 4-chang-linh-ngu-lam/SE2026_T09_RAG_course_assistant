from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.bootstrap import register_routers
from app.common.config import settings

app = FastAPI(title="RAG Course Assistant — Core", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "Idempotency-Key"],
)
register_routers(app)

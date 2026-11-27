from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from document_service.db import Database, DatabaseConfigurationError, database


class LivenessResponse(BaseModel):
    status: Literal["live"] = "live"


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    db: Literal["connected"] = "connected"


def create_app(database_instance: Database = database) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        database_instance.dispose()

    app = FastAPI(
        title="Lumi Document",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/health/live", response_model=LivenessResponse)
    def live() -> LivenessResponse:
        return LivenessResponse()

    @app.get("/health/ready", response_model=ReadinessResponse)
    def ready() -> ReadinessResponse:
        try:
            database_instance.ping()
        except (DatabaseConfigurationError, SQLAlchemyError) as exc:
            raise HTTPException(status_code=503, detail="Document database unavailable") from exc
        return ReadinessResponse()

    return app


app = create_app()

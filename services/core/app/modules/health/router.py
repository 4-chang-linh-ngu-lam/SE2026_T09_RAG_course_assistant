from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.common.db import ping_database
from app.common.errors import ErrorEnvelope

router = APIRouter(tags=["Health"])


class LivenessResponse(BaseModel):
    status: Literal["live"] = "live"


class ReadinessResponse(BaseModel):
    status: Literal["ready"] = "ready"
    db: Literal["connected"] = "connected"


@router.get("/health/live", response_model=LivenessResponse)
def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ErrorEnvelope, "description": "DB/core schema unavailable"}},
)
def ready() -> ReadinessResponse:
    try:
        ping_database()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return ReadinessResponse()

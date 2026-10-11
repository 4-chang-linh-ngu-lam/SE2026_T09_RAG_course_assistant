from fastapi import APIRouter, HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.common.db import ping_database

router = APIRouter(tags=["Health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready() -> dict[str, str]:
    try:
        ping_database()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready"}

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.db import get_db
from app.common.errors import ErrorEnvelope
from app.common.pagination import Pagination, get_pagination
from app.modules.social.feed.schemas import (
    PostCreateRequest,
    PostListResponse,
    PostResponse,
    PostUpdateRequest,
)
from app.modules.social.feed.service import FeedService

__all__ = ["router"]

ERROR_RESPONSE = {
    "description": "Error envelope with code, message and correlation_id",
    "model": ErrorEnvelope,
}

router = APIRouter(
    prefix="/api/v1",
    tags=["Social Feed"],
    responses={status: ERROR_RESPONSE for status in (400, 401, 403, 404, 409, 422, 500, 503)},
)


def get_feed_service(session: Annotated[Session, Depends(get_db)]) -> FeedService:
    return FeedService(session)


Service = Annotated[FeedService, Depends(get_feed_service)]
User = Annotated[CurrentUser, Depends(get_current_user)]
PageParam = Annotated[Pagination, Depends(get_pagination)]


def _json(model: BaseModel, status: int = 200) -> Response:
    return JSONResponse(
        model.model_dump(mode="json"),
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def _empty() -> Response:
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


def _correlation_id(request: Request) -> UUID:
    raw = getattr(request.state, "correlation_id", None)
    if raw:
        try:
            return UUID(str(raw))
        except (ValueError, TypeError):
            pass
    header_val = request.headers.get("X-Correlation-ID")
    if header_val:
        try:
            return UUID(header_val)
        except (ValueError, TypeError):
            pass
    return uuid4()


@router.get("/classes/{class_id}/posts", response_model=PostListResponse)
def list_posts(
    class_id: UUID,
    user: User,
    pagination: PageParam,
    service: Service,
) -> Response:
    return _json(service.list_posts(class_id, pagination, user))


@router.post("/classes/{class_id}/posts", response_model=PostResponse, status_code=201)
def create_post(
    class_id: UUID,
    body: PostCreateRequest,
    user: User,
    service: Service,
) -> Response:
    return _json(service.create_post(class_id, body, user), status=201)


@router.patch("/classes/{class_id}/posts/{post_id}", response_model=PostResponse)
def update_post(
    class_id: UUID,
    post_id: UUID,
    body: PostUpdateRequest,
    user: User,
    service: Service,
) -> Response:
    return _json(service.update_post(class_id, post_id, body, user))


@router.delete("/classes/{class_id}/posts/{post_id}", status_code=204)
def delete_post(
    class_id: UUID,
    post_id: UUID,
    user: User,
    request: Request,
    service: Service,
) -> Response:
    service.delete_post(class_id, post_id, user, _correlation_id(request))
    return _empty()

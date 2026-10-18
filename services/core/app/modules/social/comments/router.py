from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.db import get_db
from app.common.errors import ErrorEnvelope
from app.common.pagination import Pagination, get_pagination
from app.modules.social.comments.schemas import (
    CommentCreateRequest,
    CommentListResponse,
    CommentResponse,
    CommentUpdateRequest,
)
from app.modules.social.comments.service import CommentsService

ERROR_RESPONSE = {
    "description": "Error envelope with code, message and correlation_id",
    "model": ErrorEnvelope,
}
router = APIRouter(
    prefix="/api/v1",
    tags=["Social Comments"],
    responses={status: ERROR_RESPONSE for status in (400, 401, 403, 404, 409, 422, 500, 503)},
)


def get_comments_service(session: Annotated[Session, Depends(get_db)]) -> CommentsService:
    return CommentsService(session)


Service = Annotated[CommentsService, Depends(get_comments_service)]
User = Annotated[CurrentUser, Depends(get_current_user)]
PageParam = Annotated[Pagination, Depends(get_pagination)]


def _json(model: BaseModel, status: int = 200) -> Response:
    return JSONResponse(
        model.model_dump(mode="json"),
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/classes/{class_id}/posts/{post_id}/comments", response_model=CommentListResponse)
def list_comments(
    class_id: UUID, post_id: UUID, user: User, pagination: PageParam, service: Service
) -> Response:
    return _json(service.list_comments(class_id, post_id, pagination, user))


@router.post(
    "/classes/{class_id}/posts/{post_id}/comments",
    response_model=CommentResponse,
    status_code=201,
)
def create_comment(
    class_id: UUID,
    post_id: UUID,
    body: CommentCreateRequest,
    user: User,
    service: Service,
) -> Response:
    return _json(service.create_comment(class_id, post_id, body, user), 201)


@router.patch(
    "/classes/{class_id}/posts/{post_id}/comments/{comment_id}",
    response_model=CommentResponse,
)
def update_comment(
    class_id: UUID,
    post_id: UUID,
    comment_id: UUID,
    body: CommentUpdateRequest,
    user: User,
    service: Service,
) -> Response:
    return _json(service.update_comment(class_id, post_id, comment_id, body, user))


@router.delete("/classes/{class_id}/posts/{post_id}/comments/{comment_id}", status_code=204)
def delete_comment(
    class_id: UUID,
    post_id: UUID,
    comment_id: UUID,
    request: Request,
    user: User,
    service: Service,
) -> Response:
    service.delete_comment(
        class_id,
        post_id,
        comment_id,
        user,
        UUID(str(request.state.correlation_id)),
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})

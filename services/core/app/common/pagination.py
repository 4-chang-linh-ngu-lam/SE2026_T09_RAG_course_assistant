import base64
import binascii
from typing import Annotated
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel

from app.common.errors import AppError


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class Pagination(BaseModel):
    limit: int
    cursor: UUID | None


def encode_cursor(last_id: UUID) -> str:
    return base64.urlsafe_b64encode(last_id.bytes).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> UUID:
    try:
        if len(cursor) != 22:
            raise ValueError("Invalid cursor length")
        decoded = base64.b64decode(cursor + "==", altchars=b"-_", validate=True)
        result = UUID(bytes=decoded)
        if encode_cursor(result) != cursor:
            raise ValueError("Noncanonical cursor")
        return result
    except (ValueError, binascii.Error) as exc:
        raise AppError(400, "Invalid cursor") from exc


async def get_pagination(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=22)] = None,
) -> Pagination:
    return Pagination(limit=limit, cursor=decode_cursor(cursor) if cursor is not None else None)

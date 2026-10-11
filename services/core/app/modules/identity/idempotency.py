import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request, Response
from pydantic import SecretStr

from app.common.config import settings
from app.common.errors import AppError


@dataclass
class Entry:
    digest: str
    expires_at: float
    lock: Lock = field(default_factory=Lock, repr=False)
    response: Response | None = field(default=None, repr=False)


class IdempotencyStore:
    """Bounded process-local response cache; credentials are never persisted or logged."""

    def __init__(self, clock: Callable[[], float] = monotonic):
        self.clock = clock
        self.lock = Lock()
        self.entries: dict[tuple[str, str, UUID], Entry] = {}

    def run(
        self,
        scope: str,
        path: str,
        key: UUID | None,
        payload: dict,
        operation: Callable[[], Response],
        validate_cached: Callable[[Response], None] | None = None,
    ) -> Response:
        if key is None:
            return operation()
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: (
                value.get_secret_value() if (isinstance(value, SecretStr)) else str(value)
            ),
        )
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        cache_key = hashlib.sha256(scope.encode()).hexdigest(), path, key
        now = self.clock()
        with self.lock:
            for item_key, entry in list(self.entries.items()):
                if entry.expires_at <= now and not entry.lock.locked():
                    del self.entries[item_key]
            entry = self.entries.get(cache_key)
            if entry is None:
                if len(self.entries) >= settings.auth_idempotency_max_keys:
                    raise AppError(503, "Idempotency store unavailable")
                entry = self.entries[cache_key] = Entry(digest, now + 24 * 60 * 60)
            if entry.digest != digest:
                raise AppError(409, "Idempotency key payload mismatch")
        with entry.lock:
            if entry.response is None:
                entry.response = operation()
            elif validate_cached is not None:
                validate_cached(entry.response)
            copied = Response(content=entry.response.body, status_code=entry.response.status_code)
            copied.raw_headers = list(entry.response.raw_headers)
            return copied


store = IdempotencyStore()


def get_idempotency_store() -> IdempotencyStore:
    return store


@dataclass
class Mutation:
    path: str
    key: UUID | None
    store: IdempotencyStore

    def run(
        self,
        scope: str,
        payload: dict,
        operation: Callable[[], Response],
        validate_cached: Callable[[Response], None] | None = None,
    ) -> Response:
        return self.store.run(scope, self.path, self.key, payload, operation, validate_cached)


def get_mutation(
    request: Request,
    storage: Annotated[IdempotencyStore, Depends(get_idempotency_store)],
    idempotency_key: Annotated[UUID | None, Header()] = None,
) -> Mutation:
    return Mutation(request.url.path, idempotency_key, storage)

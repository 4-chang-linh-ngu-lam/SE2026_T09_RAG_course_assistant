from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Protocol


class StorageError(Exception):
    """Base class for storage failures safe to map to service-level errors."""


class InvalidStorageKey(StorageError):
    pass


class ObjectNotFound(StorageError):
    pass


class ObjectAlreadyExists(StorageError):
    pass


class StorageSecurityError(StorageError):
    pass


class StorageUnavailable(StorageError):
    pass


@dataclass(frozen=True)
class StorageMetadata:
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class StaleTemporaryObject:
    temporary_key: str
    modified_at: datetime


class StorageBackend(Protocol):
    """Storage contract; callers own streams returned by `open_read`."""

    def write(self, key: str, source: BinaryIO, *, chunk_size: int = 64 * 1024) -> StorageMetadata:
        """Publish immutable object; return metadata once the final key is atomically visible.

        The input stream remains caller-owned. Temporary-file cleanup after publication is
        best-effort and must not change the successful commit result.
        """
        ...

    def open_read(self, key: str) -> BinaryIO: ...

    def metadata(self, key: str) -> StorageMetadata: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> bool: ...

    def list_stale_temporary_objects(self, older_than: datetime) -> list[StaleTemporaryObject]: ...

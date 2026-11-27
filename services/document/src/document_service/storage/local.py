from __future__ import annotations

import errno
import hashlib
import logging
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import BinaryIO
from uuid import uuid4

from document_service.storage.interface import (
    InvalidStorageKey,
    ObjectAlreadyExists,
    ObjectNotFound,
    StaleTemporaryObject,
    StorageMetadata,
    StorageSecurityError,
    StorageUnavailable,
)

_KEY_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_TEMP_PREFIX = ".lumi-write-"
_TEMP_SUFFIX = ".tmp"
_LOGGER = logging.getLogger(__name__)


class LocalFileStorage:
    """Immutable-key, streamed storage rooted at one configured directory."""

    def __init__(self, root: Path | str) -> None:
        configured_root = Path(root).expanduser()
        if configured_root.is_symlink():
            raise StorageSecurityError("Storage root must not be a symlink")
        try:
            configured_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            resolved_root = configured_root.resolve(strict=True)
        except OSError:
            raise StorageUnavailable("Storage root is unavailable") from None
        if not resolved_root.is_dir():
            raise StorageUnavailable("Storage root is not a directory")
        self._root = resolved_root

    def write(self, key: str, source: BinaryIO, *, chunk_size: int = 64 * 1024) -> StorageMetadata:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        path = self._path_for(key, create_parent=True)
        self._raise_if_symlink(path)
        try:
            path.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ObjectAlreadyExists("A stored object already uses this key")

        temporary_path = path.parent / f"{_TEMP_PREFIX}{uuid4().hex}{_TEMP_SUFFIX}"
        descriptor: int | None = None
        temporary_owned = False
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(temporary_path, flags, 0o600)
            temporary_owned = True
            digest = hashlib.sha256()
            size_bytes = 0
            with os.fdopen(descriptor, "wb") as destination:
                descriptor = None
                while True:
                    chunk = source.read(chunk_size)
                    if chunk == b"":
                        break
                    if not isinstance(chunk, bytes):
                        raise TypeError("source stream must return bytes")
                    destination.write(chunk)
                    digest.update(chunk)
                    size_bytes += len(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            self._assert_safe_parent(path.parent)
            return_metadata = StorageMetadata(size_bytes=size_bytes, sha256=digest.hexdigest())
            try:
                os.link(temporary_path, path, follow_symlinks=False)
            except FileExistsError:
                raise ObjectAlreadyExists("A stored object already uses this key") from None
        except BaseException as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    exc.add_note("The temporary file descriptor could not be closed")
            if temporary_owned:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    exc.add_note("A temporary storage file could not be cleaned up")
                    _LOGGER.warning(
                        "Document temporary-file cleanup failed before atomic publication"
                    )
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            if isinstance(exc, (InvalidStorageKey, ObjectAlreadyExists, StorageSecurityError)):
                raise
            if isinstance(exc, FileExistsError) and not temporary_owned:
                raise StorageUnavailable(
                    "Temporary key collision; existing temporary object was left unchanged"
                ) from None
            if isinstance(exc, OSError):
                raise StorageUnavailable("Unable to write the stored object") from None
            raise StorageUnavailable("The input stream could not be stored") from None

        try:
            temporary_path.unlink()
        except OSError:
            _LOGGER.warning(
                "Document temporary-file cleanup failed after atomic publication; "
                "the final object remains published"
            )
        return return_metadata

    def open_read(self, key: str) -> BinaryIO:
        path = self._path_for(key)
        self._raise_if_symlink(path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            raise ObjectNotFound("Stored object was not found") from None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise StorageSecurityError("Symbolic links are not valid storage objects") from None
            raise StorageUnavailable("Unable to open the stored object") from None
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise StorageSecurityError("Storage key does not identify a regular file")
            return os.fdopen(descriptor, "rb")
        except BaseException:
            os.close(descriptor)
            raise

    def metadata(self, key: str) -> StorageMetadata:
        digest = hashlib.sha256()
        size_bytes = 0
        with self.open_read(key) as source:
            while chunk := source.read(64 * 1024):
                digest.update(chunk)
                size_bytes += len(chunk)
        return StorageMetadata(size_bytes=size_bytes, sha256=digest.hexdigest())

    def exists(self, key: str) -> bool:
        path = self._path_for(key)
        self._raise_if_symlink(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(info.st_mode):
            raise StorageSecurityError("Storage key does not identify a regular file")
        return True

    def delete(self, key: str) -> bool:
        path = self._path_for(key)
        self._raise_if_symlink(path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            return False
        if not stat.S_ISREG(info.st_mode):
            raise StorageSecurityError("Storage key does not identify a regular file")
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        except OSError:
            raise StorageUnavailable("Unable to delete the stored object") from None
        return True

    def list_stale_temporary_objects(self, older_than: datetime) -> list[StaleTemporaryObject]:
        if older_than.tzinfo is None or older_than.utcoffset() is None:
            raise ValueError("older_than must be timezone-aware")
        stale: list[StaleTemporaryObject] = []
        for directory, subdirectories, filenames in os.walk(self._root, followlinks=False):
            parent = Path(directory)
            for name in subdirectories:
                candidate = parent / name
                self._raise_if_symlink(candidate)
            for name in filenames:
                if not (name.startswith(_TEMP_PREFIX) and name.endswith(_TEMP_SUFFIX)):
                    continue
                candidate = parent / name
                self._raise_if_symlink(candidate)
                try:
                    info = candidate.lstat()
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise StorageSecurityError("Temporary storage entry is not a regular file")
                modified_at = datetime.fromtimestamp(info.st_mtime, tz=UTC)
                if modified_at <= older_than:
                    stale.append(
                        StaleTemporaryObject(
                            temporary_key=candidate.relative_to(self._root).as_posix(),
                            modified_at=modified_at,
                        )
                    )
        return sorted(stale, key=lambda item: item.temporary_key)

    def _path_for(self, key: str, *, create_parent: bool = False) -> Path:
        parts = self._validated_parts(key)
        parent = self._root
        for part in parts[:-1]:
            parent = parent / part
            self._raise_if_symlink(parent)
            if create_parent:
                try:
                    parent.mkdir(mode=0o700)
                except FileExistsError:
                    pass
                except OSError:
                    raise StorageUnavailable("Unable to prepare the storage directory") from None
            if not parent.exists():
                return self._root.joinpath(*parts)
            if not parent.is_dir():
                raise StorageSecurityError("Storage key has a non-directory parent")
            self._assert_contained(parent)
        path = parent / parts[-1]
        self._raise_if_symlink(path)
        self._assert_contained(path)
        return path

    def _validated_parts(self, key: str) -> tuple[str, ...]:
        if not isinstance(key, str) or not key or len(key) > 1024 or "\x00" in key:
            raise InvalidStorageKey("Storage key is invalid")
        windows_path = PureWindowsPath(key)
        if key.startswith(("/", "\\")) or "\\" in key or windows_path.drive or windows_path.root:
            raise InvalidStorageKey("Storage key must be a relative POSIX key")
        parts = tuple(key.split("/"))
        if any(
            not part or part in {".", ".."} or part.endswith(".") or not _KEY_PART.fullmatch(part)
            for part in parts
        ):
            raise InvalidStorageKey("Storage key contains an invalid path component")
        if any(part.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES for part in parts):
            raise InvalidStorageKey("Storage key contains a reserved path component")
        return parts

    def _assert_safe_parent(self, parent: Path) -> None:
        self._assert_contained(parent)
        current = self._root
        for part in parent.relative_to(self._root).parts:
            current = current / part
            self._raise_if_symlink(current)
            if not current.is_dir():
                raise StorageSecurityError("Storage parent is not a directory")

    def _assert_contained(self, path: Path) -> None:
        try:
            resolved = path.resolve(strict=False)
            resolved.relative_to(self._root)
        except (OSError, ValueError):
            raise StorageSecurityError("Storage key resolves outside the configured root") from None

    @staticmethod
    def _raise_if_symlink(path: Path) -> None:
        try:
            is_symlink = path.is_symlink()
        except OSError:
            raise StorageUnavailable("Unable to inspect a storage path") from None
        if is_symlink:
            raise StorageSecurityError("Symbolic links are not allowed in storage paths")

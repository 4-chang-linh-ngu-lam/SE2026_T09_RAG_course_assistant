"""Atomic local artifact writes that tolerate brief Windows reader locks.

Owned by tools/idp. Staged file data is synced before publication. This is not
a queue claim, writer lock, full power-loss guarantee or recognition retry.
"""
from __future__ import annotations

from pathlib import Path
import os
import sys
import time
import uuid

_WINDOWS = sys.platform == "win32"
_REPLACE_ATTEMPTS = 8
_replace_file = os.replace


def _retry_windows_file_operation(operation):
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            return operation()
        except PermissionError as exc:
            if (not _WINDOWS or getattr(exc, "winerror", None) not in {5, 32, 33}
                    or attempt == _REPLACE_ATTEMPTS - 1):
                raise
            # File readers on Windows may omit FILE_SHARE_DELETE. Their short
            # read must not make an otherwise complete status/proof write fail.
            # Permanent ACL failures still surface after a bounded 390ms wait.
            time.sleep(min(.01 * 2 ** attempt, .08))


def atomic_write_bytes(path: str | Path, content: bytes) -> None:
    # Snapshot mutable byte buffers before staging. Match Path.write_bytes'
    # bytes-like contract without accepting implicit integer/string conversion.
    data = content if isinstance(content, bytes) else bytes(memoryview(content))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / (".idp-" + uuid.uuid4().hex + ".tmp")
    created = False
    try:
        # Exclusive creation prevents writers from truncating each other's
        # staging files. Default permissions/umask match the previous writers.
        with temporary.open("xb") as stream:
            created = True
            stream.write(data)
            # Closing a buffered stream does not request storage synchronization.
            # A checkpoint/proof must not replace its previous value when the
            # storage layer reports a flush/sync failure. Directory/rename
            # persistence across power loss remains filesystem-dependent.
            stream.flush()
            os.fsync(stream.fileno())
        _retry_windows_file_operation(lambda: _replace_file(temporary, path))
    finally:
        if created:
            _retry_windows_file_operation(lambda: temporary.unlink(missing_ok=True))


def atomic_write_text(path: str | Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))

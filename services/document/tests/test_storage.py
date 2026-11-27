from __future__ import annotations

import ast
import hashlib
import io
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from document_service.storage import (
    InvalidStorageKey,
    LocalFileStorage,
    ObjectAlreadyExists,
    ObjectNotFound,
    StorageSecurityError,
    StorageUnavailable,
)
from document_service.storage import local as local_storage_module


class ChunkStream:
    def __init__(self, total_bytes: int, chunk: bytes = b"x") -> None:
        self.remaining = total_bytes
        self.chunk = chunk
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if self.remaining == 0:
            return b""
        count = min(size, self.remaining)
        self.remaining -= count
        return self.chunk * count


def test_streamed_write_read_and_metadata_round_trip(tmp_path):
    storage = LocalFileStorage(tmp_path / "objects")
    source = io.BytesIO(b"document bytes")

    result = storage.write("documents/doc-1/version-1", source, chunk_size=3)

    assert result.size_bytes == len(b"document bytes")
    assert result.sha256 == hashlib.sha256(b"document bytes").hexdigest()
    assert not source.closed
    assert storage.exists("documents/doc-1/version-1")
    assert storage.metadata("documents/doc-1/version-1") == result
    with storage.open_read("documents/doc-1/version-1") as reader:
        assert reader.read() == b"document bytes"


def test_empty_object_is_valid_and_has_empty_sha256(tmp_path):
    storage = LocalFileStorage(tmp_path / "objects")
    result = storage.write("empty/object", io.BytesIO(b""))

    assert result.size_bytes == 0
    assert result.sha256 == hashlib.sha256(b"").hexdigest()
    with storage.open_read("empty/object") as reader:
        assert reader.read() == b""


def test_multi_chunk_stream_never_requests_unbounded_read(tmp_path):
    storage = LocalFileStorage(tmp_path / "objects")
    total_bytes = 4 * 1024 * 1024
    chunk_size = 32 * 1024
    source = ChunkStream(total_bytes)
    expected_hash = hashlib.sha256()
    for _ in range(total_bytes // chunk_size):
        expected_hash.update(b"x" * chunk_size)

    result = storage.write("large/multi-chunk", source, chunk_size=chunk_size)

    assert result.size_bytes == total_bytes
    assert result.sha256 == expected_hash.hexdigest()
    assert len(source.read_sizes) > 100
    assert all(0 < size <= chunk_size for size in source.read_sizes)
    assert not source.closed


def test_interrupted_write_removes_temporary_object(tmp_path):
    storage = LocalFileStorage(tmp_path / "objects")

    class InterruptedStream:
        calls = 0

        def read(self, size=-1):
            self.calls += 1
            if self.calls == 1:
                return b"partial"
            raise OSError("synthetic source interruption")

    with pytest.raises(StorageUnavailable):
        storage.write("docs/interrupted", InterruptedStream())

    assert not storage.exists("docs/interrupted")
    assert storage.list_stale_temporary_objects(datetime.now(UTC) + timedelta(minutes=1)) == []


def test_failed_exclusive_temp_create_does_not_delete_another_operations_file(
    tmp_path, monkeypatch
):
    root = tmp_path / "objects"
    storage = LocalFileStorage(root)
    parent = root / "docs"
    parent.mkdir()
    existing_temp = parent / ".lumi-write-collision.tmp"
    existing_temp.write_bytes(b"owned by another operation")
    monkeypatch.setattr(local_storage_module, "uuid4", lambda: SimpleNamespace(hex="collision"))

    with pytest.raises(StorageUnavailable, match="Temporary key collision"):
        storage.write("docs/object", io.BytesIO(b"new object"))

    assert existing_temp.read_bytes() == b"owned by another operation"
    assert not storage.exists("docs/object")


def test_duplicate_key_does_not_overwrite_existing_object(tmp_path):
    storage = LocalFileStorage(tmp_path / "objects")
    storage.write("docs/immutable", io.BytesIO(b"first"))

    with pytest.raises(ObjectAlreadyExists):
        storage.write("docs/immutable", io.BytesIO(b"second"))

    with storage.open_read("docs/immutable") as reader:
        assert reader.read() == b"first"


def test_post_publish_temp_cleanup_failure_returns_published_metadata(
    tmp_path, monkeypatch, caplog
):
    storage = LocalFileStorage(tmp_path / "objects")
    root = tmp_path / "objects"
    original_unlink = Path.unlink

    def fail_temporary_unlink(path, *args, **kwargs):
        if path.name.startswith(".lumi-write-"):
            raise PermissionError("synthetic temp cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_temporary_unlink)
    payload = b"final object remains published"
    with caplog.at_level("WARNING", logger=local_storage_module.__name__):
        metadata = storage.write("docs/published", io.BytesIO(payload))

    assert metadata.size_bytes == len(payload)
    assert metadata.sha256 == hashlib.sha256(payload).hexdigest()
    assert storage.exists("docs/published")
    assert storage.metadata("docs/published") == metadata
    assert any("after atomic publication" in record.message for record in caplog.records)
    assert all(str(root) not in record.message for record in caplog.records)
    assert any(
        item.temporary_key.startswith("docs/.lumi-write-")
        for item in storage.list_stale_temporary_objects(datetime.now(UTC) + timedelta(minutes=1))
    )
    with pytest.raises(ObjectAlreadyExists):
        storage.write("docs/published", io.BytesIO(b"retry must not replace"))
    with storage.open_read("docs/published") as reader:
        assert reader.read() == payload


def test_concurrent_writers_have_one_winner_and_no_partial_object(tmp_path):
    storage = LocalFileStorage(tmp_path / "objects")
    barrier = Barrier(2)
    payloads = [b"a" * 300_000, b"b" * 300_000]

    def write(payload: bytes):
        barrier.wait()
        try:
            return storage.write("docs/race", io.BytesIO(payload), chunk_size=4096)
        except ObjectAlreadyExists:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(write, payloads))

    assert sum(result is not None for result in results) == 1
    with storage.open_read("docs/race") as reader:
        final = reader.read()
    assert final in payloads


def test_missing_object_and_delete_are_idempotent(tmp_path):
    storage = LocalFileStorage(tmp_path / "objects")

    assert not storage.exists("missing/object")
    assert storage.delete("missing/object") is False
    with pytest.raises(ObjectNotFound):
        storage.metadata("missing/object")
    with pytest.raises(ObjectNotFound):
        storage.open_read("missing/object")

    storage.write("docs/removable", io.BytesIO(b"remove me"))
    assert storage.delete("docs/removable") is True
    assert storage.delete("docs/removable") is False


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/etc/passwd",
        "../outside",
        "docs/../../outside",
        "docs//empty",
        "docs/./current",
        "windows-trailing-dot.",
        "C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "\\\\server\\share\\file",
        "\\\\?\\C:\\outside",
        "docs\\file",
        "NUL/file",
        "bad:name",
    ],
)
def test_invalid_and_windows_storage_keys_are_rejected(tmp_path, key):
    storage = LocalFileStorage(tmp_path / "objects")

    with pytest.raises(InvalidStorageKey):
        storage.write(key, io.BytesIO(b"no"))


def _make_symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        if directory:
            link.symlink_to(target, target_is_directory=True)
        else:
            link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable for this test account")


def test_symlink_parent_cannot_escape_storage_root(tmp_path):
    root = tmp_path / "objects"
    outside = tmp_path / "outside"
    outside.mkdir()
    storage = LocalFileStorage(root)
    _make_symlink_or_skip(root / "escape", outside, directory=True)

    with pytest.raises(StorageSecurityError):
        storage.write("escape/created", io.BytesIO(b"no"))
    with pytest.raises(StorageSecurityError):
        storage.open_read("escape/existing")
    with pytest.raises(StorageSecurityError):
        storage.delete("escape/existing")
    assert list(outside.iterdir()) == []


def test_symlink_object_is_not_read_or_deleted(tmp_path):
    root = tmp_path / "objects"
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"private")
    storage = LocalFileStorage(root)
    _make_symlink_or_skip(root / "shortcut", outside)

    with pytest.raises(StorageSecurityError):
        storage.exists("shortcut")
    with pytest.raises(StorageSecurityError):
        storage.open_read("shortcut")
    with pytest.raises(StorageSecurityError):
        storage.delete("shortcut")
    assert outside.read_bytes() == b"private"


def test_reopened_adapter_reads_persistent_object_and_stale_temp_is_only_reported(tmp_path):
    root = tmp_path / "objects"
    first = LocalFileStorage(root)
    first.write("docs/persistent", io.BytesIO(b"persisted"))
    stale_file = root / "docs" / ".lumi-write-old.tmp"
    stale_file.write_bytes(b"partial")
    old_time = datetime.now(UTC) - timedelta(days=2)
    os.utime(stale_file, (old_time.timestamp(), old_time.timestamp()))

    reopened = LocalFileStorage(root)
    with reopened.open_read("docs/persistent") as reader:
        assert reader.read() == b"persisted"
    stale = reopened.list_stale_temporary_objects(datetime.now(UTC) - timedelta(days=1))
    assert [item.temporary_key for item in stale] == ["docs/.lumi-write-old.tmp"]
    assert stale_file.exists()


def test_storage_interface_has_no_framework_database_or_core_imports():
    package_root = Path(__file__).parents[1] / "src" / "document_service" / "storage"
    for source_path in package_root.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        forbidden = [
            module
            for module in imports
            if module.startswith(("fastapi", "sqlalchemy", "document_service.db", "app."))
        ]
        assert forbidden == []

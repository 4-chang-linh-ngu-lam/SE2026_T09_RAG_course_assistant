"""SQLite document registry for idempotent ingestion.

A document version is identified by source hash + parser identity + pipeline
version + page scope. The registry is intentionally independent of chunking and
retrieval; it records whether a canonical parsed document already exists.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REGISTRY_VERSION = 2


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(**fields: str) -> str:
    value = "|".join(f"{key}={fields[key]}" for key in sorted(fields))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DocumentRegistry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _init(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    parser_name TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    pipeline_version TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    canonical_path TEXT,
                    pages INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(fingerprint)
                );
                CREATE INDEX IF NOT EXISTS idx_documents_doc
                    ON documents(doc_id, updated_at);
                """
            )
            columns = {r[1] for r in connection.execute("PRAGMA table_info(documents)")}
            if "canonical_sha256" not in columns:
                connection.execute("ALTER TABLE documents ADD COLUMN canonical_sha256 TEXT")
            connection.execute(f"PRAGMA user_version={REGISTRY_VERSION}")

    def lookup(
        self,
        source_sha256: str,
        parser_name: str,
        parser_version: str,
        pipeline_version: str,
        scope: str,
    ) -> dict | None:
        fingerprint = _fingerprint(
            source_sha256=source_sha256,
            parser_name=parser_name,
            parser_version=parser_version,
            pipeline_version=pipeline_version,
            scope=scope,
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
        return dict(row) if row else None

    def should_skip(
        self,
        source_sha256: str,
        parser_name: str,
        parser_version: str,
        pipeline_version: str,
        scope: str,
    ) -> bool:
        row = self.lookup(
            source_sha256, parser_name, parser_version, pipeline_version, scope
        )
        if not row or row.get("status") != "succeeded":
            return False
        canonical = row.get("canonical_path")
        if not canonical:
            return False
        canonical_path = Path(canonical)
        if not canonical_path.exists():
            return False
        stored_sha = row.get("canonical_sha256")
        if stored_sha:
            # Bind the registry hit to the exact artifact bytes: another run
            # with a different scope/config sharing this output directory may
            # have overwritten the canonical file.
            try:
                return _sha256_file(canonical_path) == stored_sha
            except OSError:
                return False
        # Legacy rows without a stored hash: fall back to the identity embedded
        # in the canonical artifact.
        try:
            artifact = json.loads(canonical_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return (
            artifact.get("doc_id") == row.get("source_sha256")
            and artifact.get("source_sha256") == row.get("source_sha256")
            and artifact.get("pipeline_version") == row.get("pipeline_version")
        )

    def record(
        self,
        doc_id: str,
        source_path: str,
        source_sha256: str,
        parser_name: str,
        parser_version: str,
        pipeline_version: str,
        scope: str,
        status: str,
        canonical_path: str | None = None,
        pages: int | None = None,
    ) -> dict:
        fingerprint = _fingerprint(
            source_sha256=source_sha256,
            parser_name=parser_name,
            parser_version=parser_version,
            pipeline_version=pipeline_version,
            scope=scope,
        )
        now = _utc_now()
        canonical_sha256 = None
        if canonical_path and Path(canonical_path).exists():
            try:
                canonical_sha256 = _sha256_file(canonical_path)
            except OSError:
                canonical_sha256 = None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    doc_id, source_path, source_sha256, parser_name,
                    parser_version, pipeline_version, scope, fingerprint,
                    status, canonical_path, canonical_sha256, pages,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    status=excluded.status,
                    canonical_path=excluded.canonical_path,
                    canonical_sha256=excluded.canonical_sha256,
                    pages=excluded.pages,
                    updated_at=excluded.updated_at
                """,
                (
                    doc_id, source_path, source_sha256, parser_name,
                    parser_version, pipeline_version, scope, fingerprint,
                    status, canonical_path, canonical_sha256, pages, now, now,
                ),
            )
        return self.lookup(
            source_sha256, parser_name, parser_version, pipeline_version, scope
        ) or {}

    def versions(self, doc_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE doc_id=? ORDER BY updated_at DESC",
                (doc_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_failed(
        self,
        doc_id: str,
        source_path: str,
        source_sha256: str,
        parser_name: str,
        parser_version: str,
        pipeline_version: str,
        scope: str,
        error: str | None = None,
    ) -> dict:
        return self.record(
            doc_id=doc_id,
            source_path=source_path,
            source_sha256=source_sha256,
            parser_name=parser_name,
            parser_version=parser_version,
            pipeline_version=pipeline_version,
            scope=scope,
            status="failed" if not error else f"failed: {error[:200]}",
        )

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.auth import CoreGateway
from app.config import settings
from app.db import SessionLocal
from app.documents import ERROR_MESSAGES
from app.errors import DocumentError
from app.events import append_event, grant_event
from app.models import Document, Grant, Outbox, Version
from app.storage import path_for


def claim():
    with SessionLocal() as session:
        now = session.scalar(select(func.clock_timestamp()))
        version = session.scalar(
            select(Version)
            .join(Document)
            .where(
                Document.deleted.is_(False),
                or_(
                    Version.status == "PENDING",
                    (Version.status == "PROCESSING") & (Version.lease_until < now),
                ),
            )
            .order_by(Version.created_at, Version.id)
            .with_for_update(of=Version, skip_locked=True)
            .limit(1)
        )
        if version is None:
            return None
        version.status, version.error_code = "PROCESSING", None
        version.generation += 1
        version.lease_until = now + timedelta(seconds=settings.job_lease_seconds)
        session.commit()
        return {
            "id": version.id,
            "document_id": version.document_id,
            "generation": version.generation,
            "storage_key": version.storage_key,
            "sha256": version.sha256,
            "format": version.format,
        }


def process(job):
    try:
        target = path_for(job["storage_key"])
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != job["sha256"]:
            return {"error": "STORAGE_UNAVAILABLE"}
        completed = subprocess.run(
            [sys.executable, "-m", "app.processing", str(target), job["format"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=settings.processing_timeout_seconds,
            check=False,
        )
        if completed.returncode != 0 or len(completed.stdout) > 32 * 1024 * 1024:
            return {"error": "RESOURCE_LIMIT"}
        result = json.loads(completed.stdout)
        if not isinstance(result, dict) or ("content" not in result and "error" not in result):
            return {"error": "INVALID_FORMAT"}
        return result
    except subprocess.TimeoutExpired:
        return {"error": "RESOURCE_LIMIT"}
    except (OSError, ValueError):
        return {"error": "STORAGE_UNAVAILABLE"}


def publish(job, result):
    with SessionLocal() as session:
        doc = session.scalar(
            select(Document).where(Document.id == job["document_id"]).with_for_update()
        )
        version = session.scalar(select(Version).where(Version.id == job["id"]).with_for_update())
        now = session.scalar(select(func.clock_timestamp()))
        if (
            doc is None
            or doc.deleted
            or version is None
            or version.generation != job["generation"]
            or version.status != "PROCESSING"
            or version.lease_until is None
            or version.lease_until < now
        ):
            return False
        if "error" in result:
            code = result["error"]
            version.status, version.error_code = (
                "FAILED",
                code if code in ERROR_MESSAGES else "INVALID_FORMAT",
            )
            version.content = None
        else:
            version.content, version.status, version.error_code = result["content"], "READY", None
            doc.revision += 1
            advances = doc.serving_version is None or version.number > doc.serving_version
            if advances:
                doc.serving_version = version.number
            append_event(
                session,
                doc,
                "document.version.ready.v1",
                {
                    "document_id": str(doc.id),
                    "owner_user_id": str(doc.owner_id),
                    "document_version": version.number,
                    "artifact_revision": version.generation,
                },
            )
            if advances:
                grants = session.scalars(
                    select(Grant)
                    .where(Grant.document_id == doc.id, Grant.active.is_(True))
                    .with_for_update()
                )
                for grant in grants:
                    grant.revision += 1
                    grant_event(session, doc, grant, doc.owner_id)
        version.lease_until = None
        session.commit()
        return True


def deliver(gateway=None):
    gateway = gateway or CoreGateway()
    with SessionLocal() as session:
        now = session.scalar(select(func.clock_timestamp()))
        event = session.scalar(
            select(Outbox)
            .where(
                Outbox.notification_payload.is_(True),
                Outbox.delivered_at.is_(None),
                Outbox.available_at <= now,
            )
            .order_by(Outbox.sequence)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if event is None:
            return False
        event.attempts += 1
        try:
            receipt = gateway.request(
                "/internal/v1/document-events", body=event.envelope, event=True
            )
            if (
                receipt.get("event_id") != event.envelope["event_id"]
                or receipt.get("accepted") is not True
            ):
                raise DocumentError(503, "INVALID_RECEIPT", "Unconfirmed delivery")
            event.delivered_at = now
        except DocumentError:
            event.available_at = now + timedelta(seconds=min(300, 2 ** min(event.attempts, 8)))
        session.commit()
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            job = claim()
            if job:
                publish(job, process(job))
            delivered = deliver()
            if args.once:
                return
            if not job and not delivered:
                time.sleep(2)
        except (SQLAlchemyError, OSError, DocumentError):
            # No exception objects: parser/DB errors can carry file contents/secrets.
            print("Document worker dependency unavailable; retrying", flush=True)
            if args.once:
                raise SystemExit(1)
            time.sleep(2)


if __name__ == "__main__":
    main()

"""Offline Core maintenance. Mutations cross modules only through public interfaces."""

import hashlib
import json
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from app.common.audit import AuditEvent, AuditMetadata, record_audit
from app.common.outbox import OUTBOX_SCHEMA_VERSION, OutboxEvent
from app.maintenance.migration_safety import MIGRATION_LOCK
from app.model_registry import load_metadata
from app.modules.classroom.public import (
    maintenance_provision_schools,
    maintenance_schools,
    maintenance_user_schools,
    seed_dev_classroom,
)
from app.modules.identity.public import (
    bootstrap_dev_identity,
    maintenance_assign_school,
    maintenance_identity_report,
)


class MappingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schools: dict[UUID, str] = Field(default_factory=dict)
    assignments: dict[UUID, UUID] = Field(default_factory=dict)


def outbox_delivery_report(session: Session) -> dict:
    """Return only aggregate outbox counts; never select or serialize payloads."""
    _head(session)
    rows = session.execute(
        select(
            OutboxEvent.schema_version,
            OutboxEvent.published_at.is_(None),
            func.count(),
        ).group_by(OutboxEvent.schema_version, OutboxEvent.published_at.is_(None))
    ).all()
    counts = {version: {"pending": 0, "published": 0} for version in {1, OUTBOX_SCHEMA_VERSION}}
    for schema_version, is_pending, count in rows:
        counts.setdefault(schema_version, {"pending": 0, "published": 0})[
            "pending" if is_pending else "published"
        ] = count
    by_schema_version = [
        {
            "schema_version": version,
            **counts[version],
        }
        for version in sorted(counts)
    ]
    return {
        "total": sum(row["pending"] + row["published"] for row in by_schema_version),
        "by_schema_version": by_schema_version,
    }


def _head(session: Session) -> None:
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    if len(script.get_heads()) != 1:
        raise ValueError("Review and merge Core migration heads before maintenance")
    current = list(session.scalars(text("SELECT version_num FROM core.alembic_version")))
    if current != script.get_heads():
        raise ValueError("Run alembic upgrade head before maintenance")


def _lock_core(session: Session) -> None:
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
    _head(session)
    # Maintenance runs offline. Block writers throughout preflight and mutation;
    # ordered locks also make concurrent invocations deterministic.
    for table in sorted(inspect(session.connection()).get_table_names(schema="core")):
        quoted = session.bind.dialect.identifier_preparer.quote(table)
        session.execute(text(f"LOCK TABLE core.{quoted} IN SHARE ROW EXCLUSIVE MODE"))


def mapping_plan(session: Session, manifest: MappingManifest) -> dict:
    _head(session)
    identities = maintenance_identity_report(session=session)
    resource_schools = maintenance_user_schools(session=session)
    for user in identities:
        user["resource_school_ids"] = resource_schools.get(user["user_id"], [])
        if len(user["resource_school_ids"]) > 1 or (
            user["school_id"]
            and any(scope != user["school_id"] for scope in user["resource_school_ids"])
        ):
            user["issues"].append("CROSS_SCHOOL_HISTORY")
    schools = maintenance_schools(session=session)
    available = {UUID(row["school_id"]) for row in schools} | set(manifest.schools)
    existing_names = {UUID(row["school_id"]): row["name"] for row in schools}
    for school_id, name in manifest.schools.items():
        if not name.strip() or len(name) > 200 or existing_names.get(school_id) not in (None, name):
            raise ValueError("Invalid School name or existing School name mismatch")
    accounts = {UUID(row["user_id"]): row for row in identities}
    for user_id, school_id in manifest.assignments.items():
        user = accounts.get(user_id)
        if user is None or school_id not in available:
            raise ValueError("Mapping references an unknown user or undeclared School")
        if user["school_id"] not in (None, str(school_id)):
            raise ValueError("Cross-school reassignment requires a separate reviewed migration")
        if any(scope != str(school_id) for scope in user["resource_school_ids"]):
            raise ValueError("Mapping conflicts with existing Classroom history; review mapping")
    real_schools = {row["school_id"] for row in schools}
    for user in identities:
        if user["school_id"] and user["school_id"] not in real_schools:
            user["issues"].append("SCHOOL_ENTITY_MISSING")
    state = {"manifest": manifest.model_dump(mode="json"), "users": identities, "schools": schools}
    # Bind approval to the exact database and migration as well as reviewed data.
    state["database"] = session.scalar(text("SELECT current_database()"))
    state["database_oid"] = session.scalar(
        text("SELECT oid FROM pg_database WHERE datname=current_database()")
    )
    state["revision"] = session.scalar(text("SELECT version_num FROM core.alembic_version"))
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return {"plan_sha256": hashlib.sha256(encoded).hexdigest(), **state}


def apply_mapping(session: Session, manifest: MappingManifest, *, approved_sha256: str) -> dict:
    """Caller commits. Approval means review of this manifest, not policy inference."""
    _lock_core(session)
    plan = mapping_plan(session, manifest)
    if not approved_sha256 or approved_sha256 != plan["plan_sha256"]:
        raise ValueError(
            "Mapping approval mismatch or data changed; generate and review a new plan"
        )
    maintenance_provision_schools(manifest.schools, session=session)
    correlation_id = uuid4()
    maintenance_assign_school(manifest.assignments, session=session, correlation_id=correlation_id)
    for school_id in manifest.schools:
        record_audit(
            session,
            actor_id=None,
            school_id=school_id,
            action="LEGACY_REVIEW_SCHOOL",
            target_type="SCHOOL",
            target_id=school_id,
            correlation_id=correlation_id,
            metadata_json=AuditMetadata(reason_code="ADMIN_INTERVENTION"),
        )
    session.flush()
    return mapping_plan(session, MappingManifest())


def seed_development(
    session: Session,
    *,
    environment: str,
    expected_database: str,
    school_id: UUID,
    school_name: str,
    admin_password: SecretStr,
) -> dict:
    if environment not in ("development", "test"):
        raise ValueError("Seed is restricted to development/test databases")
    actual = session.scalar(text("SELECT current_database()"))
    if actual != expected_database or not expected_database.startswith(("dev_", "test_")):
        raise ValueError("Specify the exact dedicated database name prefixed dev_ or test_")
    _lock_core(session)
    profile = {"version": 1, "school_id": str(school_id), "school_name": school_name}
    signature = UUID(hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()[:32])
    marker = session.scalar(select(AuditEvent).where(AuditEvent.action == "DEV_SEED_COMPLETED"))
    if marker is not None:
        if marker.target_id != school_id or marker.correlation_id != signature:
            raise ValueError("This database was seeded with a different profile")
        return {"school_id": str(school_id), "created": False}
    # Generic schema preflight only; business writes stay in their owning module.
    metadata = load_metadata()
    for table in metadata.sorted_tables:
        if session.scalar(select(table.c.id).limit(1)) is not None:
            raise ValueError(
                "Initial seed requires an empty Core database; use a dedicated database"
            )
    maintenance_provision_schools({school_id: school_name}, session=session)
    identities = bootstrap_dev_identity(
        school_id=school_id, admin_password=admin_password, session=session
    )
    seed_dev_classroom(identities=identities, session=session)
    record_audit(
        session,
        actor_id=identities["admin_id"],
        school_id=school_id,
        action="DEV_SEED_COMPLETED",
        target_type="SCHOOL",
        target_id=school_id,
        correlation_id=signature,
        metadata_json=AuditMetadata(),
    )
    session.flush()
    return {"school_id": str(school_id), "created": True}

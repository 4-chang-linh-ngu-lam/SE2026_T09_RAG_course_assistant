"""Offline Core maintenance. Mutations cross modules only through public interfaces."""

import hashlib
import json
from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

from app.common.audit import AuditEvent, AuditMetadata, record_audit
from app.common.config import settings
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
    get_user_roles,
    get_user_summary,
    maintenance_assign_school,
    maintenance_identity_report,
)
from app.modules.identity.public import (
    bootstrap_production_admin as identity_bootstrap_production_admin,
)
from app.modules.identity.public import (
    bootstrap_staging_admin as identity_bootstrap_staging_admin,
)
from app.modules.identity.public import (
    maintenance_correct_staging_admin_email as identity_correct_staging_admin_email,
)


class MappingManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schools: dict[UUID, str] = Field(default_factory=dict)
    assignments: dict[UUID, UUID] = Field(default_factory=dict)


def validate_staging_database_url(database_url: URL, *, expected_host: str) -> None:
    """Reject PostgreSQL URI options that can redirect a staging connection."""
    target_overrides = {"host", "hostaddr", "service", "servicefile"}
    if any(key.casefold() in target_overrides for key in database_url.query):
        raise ValueError("Staging database URL must not override its connection target")
    actual_host = database_url.host
    if (
        not actual_host
        or actual_host.rstrip(".").casefold() != expected_host.rstrip(".").casefold()
    ):
        raise ValueError("Staging bootstrap database host mismatch")


def validate_production_database_url(database_url: URL, *, expected_host: str) -> None:
    """Reject PostgreSQL URI options that can redirect a Production connection."""
    target_overrides = {"host", "hostaddr", "service", "servicefile"}
    if any(key.casefold() in target_overrides for key in database_url.query):
        raise ValueError("Production database URL must not override its connection target")
    actual_host = database_url.host
    if (
        not actual_host
        or actual_host.rstrip(".").casefold() != expected_host.rstrip(".").casefold()
    ):
        raise ValueError("Production bootstrap database host mismatch")


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
    result = mapping_plan(session, MappingManifest())
    if any("SCHOOL_ENTITY_MISSING" in user["issues"] for user in result["users"]):
        raise ValueError("Resolve every existing School reference before validating the users FK")
    session.execute(text("ALTER TABLE core.users VALIDATE CONSTRAINT fk_users_school_id_schools"))
    return result


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


def _bootstrap_first_admin(
    session: Session,
    *,
    school_name: str,
    admin_email: str,
    environment_label: Literal["Staging", "Production"],
    marker_action: Literal["STAGING_BOOTSTRAP_ADMIN", "PRODUCTION_BOOTSTRAP_ADMIN"],
    identity_bootstrap: Callable[..., object],
) -> dict:
    _lock_core(session)
    markers = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == marker_action)
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        )
    )
    if markers:
        if len(markers) != 1:
            raise ValueError(f"Unexpected {environment_label.lower()} bootstrap audit state")
        marker = markers[0]
        admin = get_user_summary(marker.target_id, session=session)
        school = next(
            (
                item
                for item in maintenance_schools(session=session)
                if item["school_id"] == str(marker.school_id)
            ),
            None,
        )
        if (
            marker.target_type != "USER"
            or marker.school_id is None
            or admin is None
            or admin.email is None
            or admin.email.casefold() != admin_email.strip().casefold()
            or admin.school_id != marker.school_id
            or "ADMIN" not in get_user_roles(admin.id, session=session)
            or school is None
            or school["name"] != school_name
        ):
            raise ValueError(
                f"{environment_label} bootstrap marker does not match the requested profile"
            )
        return {
            "created": False,
            "school_id": str(marker.school_id),
            "admin_user_id": str(admin.id),
            "status": str(admin.status),
            "correlation_id": str(marker.correlation_id),
        }

    for table in load_metadata().sorted_tables:
        if session.scalar(select(table.c.id).limit(1)) is not None:
            raise ValueError(f"{environment_label} bootstrap requires an empty Core database")

    smtp_password = (
        settings.smtp_password.get_secret_value().strip() if settings.smtp_password else ""
    )
    if (
        not settings.smtp_host
        or not settings.smtp_username
        or not settings.smtp_from
        or not smtp_password
    ):
        raise ValueError(
            f"Configure the {environment_label.lower()} SMTP sender and App Password before bootstrap"
        )

    school_id = uuid4()
    maintenance_provision_schools({school_id: school_name}, session=session)
    correlation_id = uuid4()
    admin = identity_bootstrap(
        email=admin_email,
        school_id=school_id,
        correlation_id=correlation_id,
        session=session,
    )
    return {
        "created": True,
        "school_id": str(school_id),
        "admin_user_id": str(admin.id),
        "status": str(admin.status),
        "invitation_delivery": "PENDING",
        "correlation_id": str(correlation_id),
    }


def bootstrap_staging_admin(
    session: Session,
    *,
    environment: str,
    expected_database: str,
    expected_host: str,
    school_name: str,
    admin_email: str,
    confirm_staging_bootstrap: bool,
) -> dict:
    """One-time staging bootstrap. The Cloud Run job must use the staging DB secret."""
    if environment != "staging" or not confirm_staging_bootstrap:
        raise ValueError("Staging bootstrap requires explicit staging confirmation")
    if not expected_database or not expected_host:
        raise ValueError("Provide the exact staging database name and host")
    if session.scalar(text("SELECT current_database()")) != expected_database:
        raise ValueError("Staging bootstrap database name mismatch")
    bind = session.get_bind()
    database_url = getattr(bind, "url", None) or getattr(getattr(bind, "engine", None), "url", None)
    if database_url is None:
        raise ValueError("Staging bootstrap database host is unavailable")
    validate_staging_database_url(database_url, expected_host=expected_host)
    return _bootstrap_first_admin(
        session,
        school_name=school_name,
        admin_email=admin_email,
        environment_label="Staging",
        marker_action="STAGING_BOOTSTRAP_ADMIN",
        identity_bootstrap=identity_bootstrap_staging_admin,
    )


def bootstrap_production_admin(
    session: Session,
    *,
    environment: str,
    expected_database: str,
    expected_host: str,
    school_name: str,
    admin_email: str,
    confirm_production_bootstrap: bool,
) -> dict:
    """One-time bootstrap for the approved synthetic Production school only."""
    if environment != "production" or not confirm_production_bootstrap:
        raise ValueError("Production bootstrap requires explicit Production confirmation")
    if school_name.strip() != "Lumi Mock School":
        raise ValueError("Production mock bootstrap only permits Lumi Mock School")
    if not expected_database or not expected_host:
        raise ValueError("Provide the exact Production database name and host")
    if session.scalar(text("SELECT current_database()")) != expected_database:
        raise ValueError("Production bootstrap database name mismatch")
    bind = session.get_bind()
    database_url = getattr(bind, "url", None) or getattr(getattr(bind, "engine", None), "url", None)
    if database_url is None:
        raise ValueError("Production bootstrap database host is unavailable")
    validate_production_database_url(database_url, expected_host=expected_host)
    return _bootstrap_first_admin(
        session,
        school_name=school_name,
        admin_email=admin_email,
        environment_label="Production",
        marker_action="PRODUCTION_BOOTSTRAP_ADMIN",
        identity_bootstrap=identity_bootstrap_production_admin,
    )


def correct_staging_admin_email(
    session: Session,
    *,
    environment: str,
    expected_database: str,
    expected_host: str,
    school_name: str,
    expected_email: str,
    new_email: str,
    confirm_staging_admin_email_correction: bool,
) -> dict:
    """Correct an unsent bootstrap invitation recipient on the approved staging DB."""
    if environment != "staging" or not confirm_staging_admin_email_correction:
        raise ValueError("Staging Admin email correction requires explicit staging confirmation")
    if not expected_database or not expected_host:
        raise ValueError("Provide the exact staging database name and host")
    if session.scalar(text("SELECT current_database()")) != expected_database:
        raise ValueError("Staging bootstrap database name mismatch")
    bind = session.get_bind()
    database_url = getattr(bind, "url", None) or getattr(getattr(bind, "engine", None), "url", None)
    if database_url is None:
        raise ValueError("Staging bootstrap database host is unavailable")
    validate_staging_database_url(database_url, expected_host=expected_host)
    _lock_core(session)

    markers = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "STAGING_BOOTSTRAP_ADMIN")
            .order_by(AuditEvent.occurred_at, AuditEvent.id)
        )
    )
    if len(markers) != 1:
        raise ValueError("Expected exactly one staging bootstrap Admin marker")
    marker = markers[0]
    if marker.target_type != "USER" or marker.school_id is None:
        raise ValueError("Staging bootstrap marker is invalid")
    school = next(
        (
            item
            for item in maintenance_schools(session=session)
            if item["school_id"] == str(marker.school_id)
        ),
        None,
    )
    admin = get_user_summary(marker.target_id, session=session)
    if (
        school is None
        or school["name"] != school_name
        or admin is None
        or admin.school_id != marker.school_id
        or "ADMIN" not in get_user_roles(admin.id, session=session)
    ):
        raise ValueError("Staging bootstrap marker does not match the requested School and Admin")

    correlation_id = uuid4()
    corrected_admin, changed = identity_correct_staging_admin_email(
        user_id=admin.id,
        school_id=marker.school_id,
        expected_email=expected_email,
        new_email=new_email,
        correlation_id=correlation_id,
        session=session,
    )
    return {
        "changed": changed,
        "school_id": str(marker.school_id),
        "admin_user_id": str(corrected_admin.id),
        "status": str(corrected_admin.status),
        "invitation_delivery": "PENDING",
        "correlation_id": str(correlation_id),
    }

"""Guard previously-applied destructive downgrades without rewriting revisions."""

from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

MIGRATION_LOCK = 7338401401

# Rows in these feature tables have no representation below their introduction.
TABLES_INTRODUCED = {
    "0002": ("audit_events",),
    "0003": ("users", "role_assignments", "auth_sessions", "one_time_tokens"),
    "0004": ("data_requests",),
    "0008": (
        "schools",
        "academic_years",
        "semesters",
        "courses",
        "homeroom_classes",
        "homeroom_rosters",
        "subject_classes",
        "teaching_assignments",
        "class_memberships",
    ),
    "0009": ("outbox_events",),
    "0010": ("class_posts", "post_comments", "calendar_events"),
    "0011": ("notifications",),
    "0012": ("student_import_batches",),
    "0013": ("document_event_receipts",),
}


def removed_revisions(script: ScriptDirectory, current: str | None, target) -> list[str]:
    if current is None:
        return []
    chain = [revision.revision for revision in script.walk_revisions(base="base", head=current)]
    if isinstance(target, str) and target.startswith("-") and target[1:].isdigit():
        count = int(target[1:])
        if count > len(chain):
            raise RuntimeError("Downgrade target precedes the migration baseline")
        return chain[:count]
    if target is None:
        return chain
    if isinstance(target, tuple):
        if len(target) != 1:
            raise RuntimeError("Core requires a single migration destination")
        target = target[0]
    if target in chain:
        return chain[: chain.index(target)]
    # An upgrade target is a descendant, not part of the current ancestry.
    return []


def guard_downgrade(connection: Connection, script: ScriptDirectory, current, target) -> None:
    removed = set(removed_revisions(script, current, target))
    if not removed:
        return
    tables = set(inspect(connection).get_table_names(schema="core")) - {"alembic_version"}
    # Block writers before examining rows. This prevents an insert committing
    # between an empty-table check and DROP TABLE in an older revision.
    for table in sorted(tables):
        quoted = connection.dialect.identifier_preparer.quote(table)
        connection.execute(text(f"LOCK TABLE core.{quoted} IN SHARE MODE"))

    for revision, affected in TABLES_INTRODUCED.items():
        if revision not in removed:
            continue
        for table in affected:
            if table in tables and connection.scalar(
                text(f'SELECT EXISTS(SELECT 1 FROM core."{table}")')
            ):
                if revision == "0011":
                    raise RuntimeError(
                        "Downgrade would discard notifications; preserve inbox data first"
                    )
                if revision == "0012":
                    raise RuntimeError("Preserve student import records before downgrade")
                raise RuntimeError(
                    f"Unsafe downgrade: preserve core.{table} before removing revision {revision}"
                )
    if (
        "0012" in removed
        and "audit_events" in tables
        and connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM core.audit_events WHERE school_id IS NOT NULL)")
        )
    ):
        raise RuntimeError("Preserve audit school scope before downgrade")
    if (
        "0011" in removed
        and "outbox_events" in tables
        and connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM core.outbox_events WHERE schema_version <> 1 "
                "OR attempts <> 0 OR last_error_code IS NOT NULL OR available_at > CURRENT_TIMESTAMP "
                "OR (aggregate_version IS NOT NULL AND aggregate_version::text IS DISTINCT FROM payload_json->>'version'))"
            )
        )
    ):
        raise RuntimeError("Preserve outbox envelope/retry history before downgrade")
    if "0006" in removed and "users" in tables:
        # Email-free rows already trigger the original NOT NULL check (DBAPIError).
        # For email-compatible rows, also protect fields that 0006 used to drop.
        has_email_free = connection.scalar(
            text("SELECT EXISTS(SELECT 1 FROM core.users WHERE email IS NULL)")
        )
        has_new_fields = connection.scalar(
            text(
                "SELECT EXISTS(SELECT 1 FROM core.users WHERE username IS NOT NULL OR school_id IS NOT NULL OR activated_at IS NOT NULL)"
            )
        )
        if has_new_fields and not has_email_free:
            raise RuntimeError(
                "Preserve Student identifiers and school/activation data before downgrade"
            )

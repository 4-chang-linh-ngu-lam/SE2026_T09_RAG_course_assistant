"""Tenant-scoped audit and durable Student import previews/results.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_events", sa.Column("school_id", sa.Uuid(), nullable=True), schema="core")
    # Historical events lack an authoritative tenant-at-event-time mapping.
    # Leave them null/hidden; do not infer scope from an actor's current school.
    for name, columns in (
        ("idx_audit_school_occurred", ["school_id", "occurred_at", "id"]),
        ("idx_audit_actor_occurred", ["actor_id", "occurred_at"]),
        ("idx_audit_action_occurred", ["action", "occurred_at"]),
    ):
        op.create_index(name, "audit_events", columns, schema="core")
    op.create_table(
        "student_import_batches",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("school_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("core.users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rows_json", postgresql.JSONB(), nullable=False),
        sa.Column("checks_json", postgresql.JSONB(), nullable=False),
        sa.Column("results_json", postgresql.JSONB(), nullable=False),
        sa.Column("homeroom_id", sa.Uuid(), nullable=True),
        sa.Column("roster_version", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('PREVIEW','COMPLETED')", name="ck_student_import_status"),
        schema="core",
    )
    op.create_index(
        "idx_student_import_actor", "student_import_batches", ["actor_id", "id"], schema="core"
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(sa.text("SELECT EXISTS(SELECT 1 FROM core.student_import_batches)")):
        raise RuntimeError("Preserve student import records before downgrade")
    if connection.scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM core.audit_events WHERE school_id IS NOT NULL)")
    ):
        raise RuntimeError("Preserve audit school scope before downgrade")
    op.drop_table("student_import_batches", schema="core")
    for name in (
        "idx_audit_school_occurred",
        "idx_audit_actor_occurred",
        "idx_audit_action_occurred",
    ):
        op.drop_index(name, table_name="audit_events", schema="core")
    op.drop_column("audit_events", "school_id", schema="core")

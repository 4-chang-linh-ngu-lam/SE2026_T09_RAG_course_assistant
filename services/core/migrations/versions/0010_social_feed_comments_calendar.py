"""Social feed, comments and calendar.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "class_posts",
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("core.subject_classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Uuid(),
            sa.ForeignKey("core.users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.String(10000), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.CheckConstraint(
            "length(body) >= 1 AND length(body) <= 10000", name="ck_posts_body_length"
        ),
        schema="core",
    )
    op.create_index("ix_core_class_posts_class_id", "class_posts", ["class_id"], schema="core")
    op.create_index("ix_core_class_posts_author_id", "class_posts", ["author_id"], schema="core")
    op.create_index(
        "idx_posts_class_created",
        "class_posts",
        ["class_id", sa.text("created_at DESC"), sa.text("id DESC")],
        schema="core",
    )

    op.create_table(
        "post_comments",
        sa.Column(
            "post_id",
            sa.Uuid(),
            sa.ForeignKey("core.class_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Uuid(),
            sa.ForeignKey("core.users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("body", sa.String(10000), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.CheckConstraint(
            "length(body) >= 1 AND length(body) <= 10000", name="ck_comments_body_length"
        ),
        schema="core",
    )
    op.create_index("ix_core_post_comments_post_id", "post_comments", ["post_id"], schema="core")
    op.create_index(
        "ix_core_post_comments_author_id", "post_comments", ["author_id"], schema="core"
    )
    op.create_index(
        "idx_comments_post_created",
        "post_comments",
        ["post_id", sa.text("created_at ASC"), sa.text("id ASC")],
        schema="core",
    )

    op.create_table(
        "calendar_events",
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("core.subject_classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(10000), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("origin", sa.String(8), nullable=False),
        sa.Column("external_ref", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        *_base_columns(),
        sa.CheckConstraint(
            "length(title) >= 1 AND length(title) <= 200", name="ck_calendar_title_length"
        ),
        sa.CheckConstraint(
            "description IS NULL OR length(description) <= 10000",
            name="ck_calendar_description_length",
        ),
        sa.CheckConstraint("starts_at < ends_at", name="ck_calendar_time_order"),
        sa.CheckConstraint("origin IN ('CORE', 'LEARNING')", name="ck_calendar_origin"),
        sa.CheckConstraint("version >= 1", name="ck_calendar_version_positive"),
        schema="core",
    )
    op.create_index(
        "ix_core_calendar_events_class_id", "calendar_events", ["class_id"], schema="core"
    )
    op.create_index(
        "idx_calendar_class_time",
        "calendar_events",
        ["class_id", "starts_at"],
        schema="core",
    )
    op.create_index(
        "uq_calendar_origin_ext_ref",
        "calendar_events",
        ["origin", "external_ref"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_table("calendar_events", schema="core")
    op.drop_table("post_comments", schema="core")
    op.drop_table("class_posts", schema="core")

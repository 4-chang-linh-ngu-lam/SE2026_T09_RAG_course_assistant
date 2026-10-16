"""classroom_schema

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("code <> ''", name="ck_courses_code_not_empty"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
        schema="core",
    )
    op.create_table(
        "classes",
        sa.Column(
            "course_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("join_code_hash", sa.String(length=64), nullable=False),
        sa.Column("join_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "ARCHIVED",
                name="class_status",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("name <> ''", name="ck_classes_name_not_empty"),
        sa.CheckConstraint("join_code_hash <> ''", name="ck_classes_join_code_hash_not_empty"),
        sa.ForeignKeyConstraint(["course_id"], ["core.courses.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["core.users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("join_code_hash"),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_classes_course_id"), "classes", ["course_id"], unique=False, schema="core"
    )
    op.create_index(
        op.f("ix_core_classes_owner_user_id"),
        "classes",
        ["owner_user_id"],
        unique=False,
        schema="core",
    )
    op.create_table(
        "class_memberships",
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "class_role",
            sa.Enum(
                "OWNER",
                "CO_LECTURER",
                "STUDENT",
                name="class_role",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "LEFT",
                "REMOVED",
                name="membership_status",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            nullable=False,
        ),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["class_id"], ["core.classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["core.users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_class_memberships_class_id"),
        "class_memberships",
        ["class_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_class_memberships_user_id"),
        "class_memberships",
        ["user_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_class_memberships_active",
        "class_memberships",
        ["class_id", "user_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "join_requests",
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "APPROVED",
                "REJECTED",
                "CANCELLED",
                name="join_request_status",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["class_id"], ["core.classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by"], ["core.users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["student_id"], ["core.users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_join_requests_class_id"),
        "join_requests",
        ["class_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_join_requests_student_id"),
        "join_requests",
        ["student_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_join_requests_decided_by"),
        "join_requests",
        ["decided_by"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_join_requests_pending",
        "join_requests",
        ["class_id", "student_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_table(
        "co_lecturer_invitations",
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("lecturer_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "ACCEPTED",
                "REJECTED",
                "CANCELLED",
                name="co_lecturer_invitation_status",
                native_enum=False,
                create_constraint=True,
                schema="core",
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["class_id"], ["core.classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lecturer_id"], ["core.users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        schema="core",
    )
    op.create_index(
        op.f("ix_core_co_lecturer_invitations_class_id"),
        "co_lecturer_invitations",
        ["class_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        op.f("ix_core_co_lecturer_invitations_lecturer_id"),
        "co_lecturer_invitations",
        ["lecturer_id"],
        unique=False,
        schema="core",
    )
    op.create_index(
        "ix_core_co_lecturer_invitations_pending",
        "co_lecturer_invitations",
        ["class_id", "lecturer_id"],
        unique=True,
        schema="core",
        postgresql_where=sa.text("status = 'PENDING'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_core_co_lecturer_invitations_pending",
        table_name="co_lecturer_invitations",
        schema="core",
    )
    op.drop_index(
        op.f("ix_core_co_lecturer_invitations_lecturer_id"),
        table_name="co_lecturer_invitations",
        schema="core",
    )
    op.drop_index(
        op.f("ix_core_co_lecturer_invitations_class_id"),
        table_name="co_lecturer_invitations",
        schema="core",
    )
    op.drop_table("co_lecturer_invitations", schema="core")
    op.drop_index("ix_core_join_requests_pending", table_name="join_requests", schema="core")
    op.drop_index(
        op.f("ix_core_join_requests_decided_by"), table_name="join_requests", schema="core"
    )
    op.drop_index(
        op.f("ix_core_join_requests_student_id"), table_name="join_requests", schema="core"
    )
    op.drop_index(op.f("ix_core_join_requests_class_id"), table_name="join_requests", schema="core")
    op.drop_table("join_requests", schema="core")
    op.drop_index("ix_core_class_memberships_active", table_name="class_memberships", schema="core")
    op.drop_index(
        op.f("ix_core_class_memberships_user_id"), table_name="class_memberships", schema="core"
    )
    op.drop_index(
        op.f("ix_core_class_memberships_class_id"), table_name="class_memberships", schema="core"
    )
    op.drop_table("class_memberships", schema="core")
    op.drop_index(op.f("ix_core_classes_owner_user_id"), table_name="classes", schema="core")
    op.drop_index(op.f("ix_core_classes_course_id"), table_name="classes", schema="core")
    op.drop_table("classes", schema="core")
    op.drop_table("courses", schema="core")

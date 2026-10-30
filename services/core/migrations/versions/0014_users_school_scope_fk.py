"""Add a nullable School foreign key to legacy Identity scope.

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

CONSTRAINT = "fk_users_school_id_schools"


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE core.users ADD CONSTRAINT {CONSTRAINT} "
        "FOREIGN KEY (school_id) REFERENCES core.schools (id) NOT VALID"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS ("
        "SELECT 1 FROM core.users AS users "
        "LEFT JOIN core.schools AS schools ON schools.id = users.school_id "
        "WHERE users.school_id IS NOT NULL AND schools.id IS NULL"
        ") THEN "
        f"ALTER TABLE core.users VALIDATE CONSTRAINT {CONSTRAINT}; "
        "END IF; END; $$"
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "users", schema="core", type_="foreignkey")

"""School, roster, subject classes and teaching assignments for Lumi.

Revision ID: 0008
Revises: 0007
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE core.schools (
	name VARCHAR(200),
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id)
)""")
    op.execute("""CREATE TABLE core.academic_years (
	school_id UUID NOT NULL,
	label VARCHAR(30) NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_academic_year_school_label UNIQUE (school_id, label),
	FOREIGN KEY(school_id) REFERENCES core.schools (id)
)""")
    op.execute(
        """CREATE INDEX ix_core_academic_years_school_id ON core.academic_years (school_id)"""
    )
    op.execute("""CREATE TABLE core.semesters (
	academic_year_id UUID NOT NULL,
	name VARCHAR(50) NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_semester_year_name UNIQUE (academic_year_id, name),
	FOREIGN KEY(academic_year_id) REFERENCES core.academic_years (id)
)""")
    op.execute(
        """CREATE INDEX ix_core_semesters_academic_year_id ON core.semesters (academic_year_id)"""
    )
    op.execute("""CREATE TABLE core.courses (
	school_id UUID NOT NULL,
	code VARCHAR(50) NOT NULL,
	name VARCHAR(200) NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_course_school_code UNIQUE (school_id, code),
	CONSTRAINT ck_courses_code_not_empty CHECK (code <> ''),
	FOREIGN KEY(school_id) REFERENCES core.schools (id)
)""")
    op.execute("""CREATE INDEX ix_core_courses_school_id ON core.courses (school_id)""")
    op.execute("""CREATE TABLE core.homeroom_classes (
	school_id UUID NOT NULL,
	academic_year_id UUID NOT NULL,
	name VARCHAR(200) NOT NULL,
	grade_level INTEGER NOT NULL,
	roster_version INTEGER DEFAULT 1 NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_homeroom_year_name UNIQUE (school_id, academic_year_id, name),
	CONSTRAINT ck_homeroom_grade_level CHECK (grade_level BETWEEN 6 AND 12),
	CONSTRAINT ck_homeroom_roster_version CHECK (roster_version >= 1),
	FOREIGN KEY(school_id) REFERENCES core.schools (id),
	FOREIGN KEY(academic_year_id) REFERENCES core.academic_years (id)
)""")
    op.execute(
        """CREATE INDEX ix_core_homeroom_classes_academic_year_id ON core.homeroom_classes (academic_year_id)"""
    )
    op.execute(
        """CREATE INDEX ix_core_homeroom_classes_school_id ON core.homeroom_classes (school_id)"""
    )
    op.execute("""CREATE TABLE core.homeroom_rosters (
	homeroom_class_id UUID NOT NULL,
	student_id UUID NOT NULL,
	joined_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(homeroom_class_id) REFERENCES core.homeroom_classes (id),
	FOREIGN KEY(student_id) REFERENCES core.users (id)
)""")
    op.execute(
        """CREATE INDEX ix_core_homeroom_rosters_homeroom_class_id ON core.homeroom_rosters (homeroom_class_id)"""
    )
    op.execute(
        """CREATE INDEX ix_core_homeroom_rosters_student_id ON core.homeroom_rosters (student_id)"""
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_active_homeroom_student ON core.homeroom_rosters (homeroom_class_id, student_id) WHERE ended_at IS NULL"""
    )
    op.execute("""CREATE TABLE core.subject_classes (
	school_id UUID NOT NULL,
	academic_year_id UUID NOT NULL,
	semester_id UUID NOT NULL,
	course_id UUID NOT NULL,
	homeroom_class_id UUID,
	name VARCHAR(200) NOT NULL,
	grade_level INTEGER NOT NULL,
	enrollment_mode VARCHAR(6) NOT NULL,
	status VARCHAR(8) DEFAULT 'ACTIVE' NOT NULL,
	version INTEGER DEFAULT 1 NOT NULL,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	CONSTRAINT uq_subject_class_identity UNIQUE (school_id, academic_year_id, semester_id, course_id, name),
	CONSTRAINT ck_subject_grade_level CHECK (grade_level BETWEEN 6 AND 12),
	CONSTRAINT ck_subject_version CHECK (version >= 1),
	FOREIGN KEY(school_id) REFERENCES core.schools (id),
	FOREIGN KEY(academic_year_id) REFERENCES core.academic_years (id),
	FOREIGN KEY(semester_id) REFERENCES core.semesters (id),
	FOREIGN KEY(course_id) REFERENCES core.courses (id),
	FOREIGN KEY(homeroom_class_id) REFERENCES core.homeroom_classes (id),
	CONSTRAINT enrollment_mode CHECK (enrollment_mode IN ('AUTO', 'MANUAL')),
	CONSTRAINT class_status CHECK (status IN ('ACTIVE', 'ARCHIVED'))
)""")
    op.execute(
        """CREATE INDEX ix_core_subject_classes_academic_year_id ON core.subject_classes (academic_year_id)"""
    )
    op.execute(
        """CREATE INDEX ix_core_subject_classes_course_id ON core.subject_classes (course_id)"""
    )
    op.execute(
        """CREATE INDEX ix_core_subject_classes_homeroom_class_id ON core.subject_classes (homeroom_class_id)"""
    )
    op.execute(
        """CREATE INDEX ix_core_subject_classes_school_id ON core.subject_classes (school_id)"""
    )
    op.execute(
        """CREATE INDEX ix_core_subject_classes_semester_id ON core.subject_classes (semester_id)"""
    )
    op.execute("""CREATE TABLE core.teaching_assignments (
	class_id UUID NOT NULL,
	lecturer_id UUID NOT NULL,
	role VARCHAR(9) NOT NULL,
	assigned_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(class_id) REFERENCES core.subject_classes (id),
	FOREIGN KEY(lecturer_id) REFERENCES core.users (id),
	CONSTRAINT teaching_role CHECK (role IN ('PRIMARY', 'ASSISTING'))
)""")
    op.execute(
        """CREATE INDEX ix_core_teaching_assignments_class_id ON core.teaching_assignments (class_id)"""
    )
    op.execute(
        """CREATE INDEX ix_core_teaching_assignments_lecturer_id ON core.teaching_assignments (lecturer_id)"""
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_active_primary_teacher ON core.teaching_assignments (class_id) WHERE role = 'PRIMARY' AND ended_at IS NULL"""
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_active_teacher_per_class ON core.teaching_assignments (class_id, lecturer_id) WHERE ended_at IS NULL"""
    )
    op.execute("""CREATE TABLE core.class_memberships (
	class_id UUID NOT NULL,
	student_id UUID NOT NULL,
	source VARCHAR(6) NOT NULL,
	status VARCHAR(6) NOT NULL,
	joined_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	id UUID DEFAULT gen_random_uuid() NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (id),
	FOREIGN KEY(class_id) REFERENCES core.subject_classes (id),
	FOREIGN KEY(student_id) REFERENCES core.users (id),
	CONSTRAINT membership_source CHECK (source IN ('AUTO', 'MANUAL')),
	CONSTRAINT membership_status CHECK (status IN ('ACTIVE', 'ENDED'))
)""")
    op.execute(
        """CREATE INDEX ix_core_class_memberships_class_id ON core.class_memberships (class_id)"""
    )
    op.execute(
        """CREATE INDEX ix_core_class_memberships_student_id ON core.class_memberships (student_id)"""
    )
    op.execute(
        """CREATE UNIQUE INDEX uq_active_class_membership ON core.class_memberships (class_id, student_id) WHERE status = 'ACTIVE'"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE core.class_memberships")
    op.execute("DROP TABLE core.teaching_assignments")
    op.execute("DROP TABLE core.subject_classes")
    op.execute("DROP TABLE core.homeroom_rosters")
    op.execute("DROP TABLE core.homeroom_classes")
    op.execute("DROP TABLE core.courses")
    op.execute("DROP TABLE core.semesters")
    op.execute("DROP TABLE core.academic_years")
    op.execute("DROP TABLE core.schools")

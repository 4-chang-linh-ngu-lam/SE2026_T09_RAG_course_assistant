from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class StudentImportBatch(Base):
    __tablename__ = "student_import_batches"
    __table_args__ = (
        CheckConstraint("status IN ('PREVIEW','COMPLETED')", name="ck_student_import_status"),
        Index("idx_student_import_actor", "actor_id", "id"),
    )

    school_id: Mapped[UUID]
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("core.users.id"))
    status: Mapped[str] = mapped_column(String(16))
    rows_json: Mapped[list] = mapped_column(JSONB)
    checks_json: Mapped[list] = mapped_column(JSONB)
    results_json: Mapped[list] = mapped_column(JSONB)
    homeroom_id: Mapped[UUID | None]
    roster_version: Mapped[int | None]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

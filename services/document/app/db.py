from collections.abc import Iterator
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    metadata = MetaData(schema="document")
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.clock_timestamp()
    )


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=3,
    connect_args={"connect_timeout": 3, "options": "-c timezone=UTC -c statement_timeout=15000"},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        try:
            yield session
        except BaseException:
            session.rollback()
            raise

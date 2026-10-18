from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, create_engine, func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.common.config import settings


class Base(DeclarativeBase):
    metadata = MetaData(schema="core")

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    hide_parameters=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
    connect_args={
        "options": "-c timezone=UTC",
        "connect_timeout": settings.database_connect_timeout_seconds,
    },
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


@contextmanager
def transaction(session: Session) -> Iterator[Session]:
    """Commit the caller's unit of work, including any transaction started by a read."""
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise


def ping_database() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        usable = connection.scalar(
            text(
                "SELECT has_schema_privilege(current_user, oid, 'USAGE') "
                "FROM pg_namespace WHERE nspname = 'core'"
            )
        )
        if not usable:
            raise SQLAlchemyError("Core schema unavailable")

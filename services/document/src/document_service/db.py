from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from threading import Lock
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, create_engine, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from document_service.config import Settings, settings


class DatabaseConfigurationError(RuntimeError):
    """Raised when Document has no independently configured PostgreSQL URL."""


class Base(DeclarativeBase):
    metadata = MetaData(schema="document")

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Database:
    def __init__(self, configuration: Settings) -> None:
        self._configuration = configuration
        self._engine: Engine | None = None
        self._sessions: sessionmaker[Session] | None = None
        self._lock = Lock()

    @property
    def engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            database_url = self._configuration.database_url
            if database_url is None:
                raise DatabaseConfigurationError("DOCUMENT_DATABASE_URL is not configured")
            self._engine = create_engine(
                database_url.get_secret_value(),
                pool_pre_ping=True,
                hide_parameters=True,
                pool_size=self._configuration.database_pool_size,
                max_overflow=self._configuration.database_max_overflow,
                pool_timeout=self._configuration.database_pool_timeout_seconds,
                connect_args={
                    "options": "-c timezone=UTC",
                    "connect_timeout": self._configuration.database_connect_timeout_seconds,
                },
            )
            self._sessions = sessionmaker(
                bind=self._engine, autoflush=False, expire_on_commit=False
            )
            return self._engine

    def session_factory(self) -> sessionmaker[Session]:
        _ = self.engine
        assert self._sessions is not None
        return self._sessions

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            schema_available = connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'document') "
                    "AND has_schema_privilege(current_user, 'document', 'USAGE')"
                )
            )
            if not schema_available:
                raise SQLAlchemyError("Document schema unavailable")

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._sessions = None


database = Database(settings)


def get_db() -> Iterator[Session]:
    with database.session_factory()() as session:
        yield session


@contextmanager
def transaction(session: Session) -> Iterator[Session]:
    """Commit one caller-owned unit of work and roll it back on failure."""
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise

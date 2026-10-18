from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.common.audit import AuditEvent  # noqa: F401 -- register audit metadata for Alembic
from app.common.config import settings
from app.common.db import Base
from app.common.outbox import OutboxEvent  # noqa: F401 -- register outbox metadata for Alembic
from app.modules.classroom import models as classroom_models  # noqa: F401 -- register Classroom tables
from app.modules.identity import models as identity_models  # noqa: F401 -- register Identity tables
from app.modules.social.calendar import models as calendar_models  # noqa: F401
from app.modules.social.comments import models as comments_models  # noqa: F401
from app.modules.social.feed import models as feed_models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    # Core migrations must never inspect or modify another service's schema.
    return type_ != "schema" or name == "core"


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        version_table_schema="core",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        connection.commit()
        connection.execute(text("SET search_path TO public"))
        # End SQLAlchemy's implicit transaction so Alembic owns and commits its DDL transaction.
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="core",
            include_schemas=True,
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from document_service.config import settings
from document_service.migration_config import migration_comparison_options

config = context.config
comparison_options = migration_comparison_options()


def _database_url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    if settings.database_url is None:
        raise RuntimeError("DOCUMENT_DATABASE_URL is required for migrations")
    return settings.database_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        literal_binds=True,
        **comparison_options,
    )
    with context.begin_transaction():
        context.execute("CREATE SCHEMA IF NOT EXISTS document")
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={
            "options": "-c timezone=UTC",
            "connect_timeout": settings.database_connect_timeout_seconds,
        },
    )
    with connectable.connect() as connection, connection.begin():
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS document"))
        connection.execute(text("SET LOCAL search_path TO public"))
        context.configure(
            connection=connection,
            **comparison_options,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

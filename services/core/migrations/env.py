from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app.common.config import settings
from app.maintenance.migration_safety import MIGRATION_LOCK, guard_downgrade, removed_revisions
from app.model_registry import load_metadata

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
target_metadata = load_metadata()


def include_name(name, type_, parent_names):
    # Core migrations must never inspect or modify another service's schema.
    return type_ != "schema" or name == "core"


def run_migrations_offline() -> None:
    starting = context.get_starting_revision_argument()
    if starting is not None and removed_revisions(
        context.script, starting, context.get_revision_argument()
    ):
        raise RuntimeError("Offline downgrade cannot validate data safety; use online migrations")
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
    with connectable.connect() as connection, connection.begin():
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK})
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS core"))
        connection.execute(text("SET LOCAL search_path TO public"))
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="core",
            include_schemas=True,
            include_name=include_name,
        )
        try:
            destination = context.get_revision_argument()
        except KeyError:  # check/autogenerate do not request a revision transition.
            destination = "head"
        with context.begin_transaction():
            guard_downgrade(
                connection,
                context.script,
                context.get_context().get_current_revision(),
                destination,
            )
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

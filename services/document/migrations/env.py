from alembic import context
from sqlalchemy import engine_from_config, pool, text

from app import models  # noqa: F401
from app.config import settings
from app.db import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))


def run():
    if context.is_offline_mode():
        context.configure(
            url=settings.database_url,
            target_metadata=Base.metadata,
            literal_binds=True,
            version_table_schema="document",
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection, connection.begin():
        connection.execute(text("SELECT pg_advisory_xact_lock(170172026)"))
        # Schema must already be provisioned to the isolated role by bootstrap.
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            version_table_schema="document",
            include_schemas=True,
            include_name=lambda name, type_, parents: type_ != "schema" or name == "document",
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


run()

"""Explicit role/schema provisioning; no Core data queries or environment echo."""

import os
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql

from app.config import settings


def main():
    admin_url = os.environ.get("DOCUMENT_ADMIN_DATABASE_URL")
    if not admin_url:
        raise SystemExit("DOCUMENT_ADMIN_DATABASE_URL is required for provisioning only")
    target = urlsplit(settings.database_url.replace("postgresql+psycopg:", "postgresql:"))
    role, password = unquote(target.username or ""), unquote(target.password or "")
    if not role or not password or len(password) < 24 or password.startswith("configure"):
        raise SystemExit("Configure a separate Document DB credential (password 24+ characters)")
    with (
        psycopg.connect(admin_url.replace("postgresql+psycopg:", "postgresql:")) as connection,
        connection.cursor() as cursor,
    ):
        existing = cursor.execute("SELECT oid FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if existing is None:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                ).format(sql.Identifier(role), sql.Literal(password))
            )
        # Never rotate an existing login or seize an existing schema silently.
        owner = cursor.execute(
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'document'"
        ).fetchone()
        if owner is not None and owner[0] != role:
            raise RuntimeError("Document schema already belongs to another role; review ownership")
        cursor.execute(
            sql.SQL("CREATE SCHEMA IF NOT EXISTS document AUTHORIZATION {}").format(
                sql.Identifier(role)
            )
        )
        cursor.execute(sql.SQL("REVOKE ALL ON SCHEMA document FROM PUBLIC"))
    # Verify actual credential, including an existing role that might be privileged.
    with psycopg.connect(
        settings.database_url.replace("postgresql+psycopg:", "postgresql:")
    ) as connection:
        row = connection.execute(
            "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if any(row):
            raise RuntimeError("Document runtime role must not be privileged")
        core = connection.execute(
            "SELECT has_schema_privilege(current_user, oid, 'USAGE') FROM pg_namespace WHERE nspname = 'core'"
        ).fetchone()
        if core is not None and core[0]:
            raise RuntimeError("Document runtime must not have access to Core schema")
    print("Document isolated role/schema verified")


if __name__ == "__main__":
    main()

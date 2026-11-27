"""Explicitly opted-in local/test provisioning for the Document database."""

import re
from dataclasses import dataclass

from psycopg import Error as PsycopgError
from psycopg import connect, sql
from sqlalchemy.engine import URL, make_url

from document_service.config import Settings, settings

_LOCAL_HOSTS = {"db", "localhost", "127.0.0.1", "::1"}
_TEST_DATABASE = re.compile(r"test_document_([a-z0-9_]{1,32})\Z")
_TEST_MARKER = "lumi-document-test-disposable:v1"


@dataclass(frozen=True)
class RoleState:
    oid: int
    can_login: bool
    superuser: bool
    createdb: bool
    createrole: bool
    replication: bool
    bypass_rls: bool

    @classmethod
    def from_row(cls, row: tuple) -> "RoleState":
        return cls(*row)


@dataclass(frozen=True)
class DatabaseState:
    oid: int
    owner_oid: int
    comment: str | None


@dataclass(frozen=True)
class ProvisioningPlan:
    create_role: bool
    create_database: bool


def _database_identity(configuration: Settings) -> tuple[URL, URL, bool]:
    if not configuration.allow_local_database_provisioning:
        raise RuntimeError("Local database provisioning requires explicit opt-in")
    if configuration.database_admin_url is None:
        raise RuntimeError("DOCUMENT_DATABASE_ADMIN_URL is required")
    if configuration.database_url is None or configuration.database_password is None:
        raise RuntimeError("Document database URL and password must both be configured")

    admin_url = make_url(configuration.database_admin_url.get_secret_value())
    document_url = make_url(configuration.database_url.get_secret_value())
    if (
        admin_url.drivername != "postgresql+psycopg"
        or document_url.drivername != "postgresql+psycopg"
    ):
        raise RuntimeError("Provisioning requires PostgreSQL URLs using psycopg")
    if admin_url.query or document_url.query:
        raise RuntimeError("Bootstrap PostgreSQL URLs must not include query parameters")
    if admin_url.host not in _LOCAL_HOSTS:
        raise RuntimeError("Local database provisioning only accepts a local PostgreSQL host")
    if admin_url.database != "postgres":
        raise RuntimeError("Local database administration must use the postgres maintenance DB")
    if (admin_url.host, admin_url.port or 5432) != (
        document_url.host,
        document_url.port or 5432,
    ):
        raise RuntimeError("Admin and Document URLs must target the same local PostgreSQL instance")
    if document_url.database != configuration.database_name:
        raise RuntimeError("Document URL database does not match the Document database name")
    if document_url.username != configuration.database_user:
        raise RuntimeError("Document URL user does not match the dedicated Document role")
    if document_url.password != configuration.database_password.get_secret_value():
        raise RuntimeError("Document password and URL credentials do not match")
    if not admin_url.username or admin_url.username == configuration.database_user:
        raise RuntimeError("A separate PostgreSQL administrative identity is required")

    test_match = _TEST_DATABASE.fullmatch(configuration.database_name)
    if configuration.database_name == "lumi_document":
        if configuration.database_user != "lumi_document":
            raise RuntimeError("The local Document database and login names must match")
        if configuration.test_database_disposable:
            raise RuntimeError("lumi_document must not be marked as a disposable test database")
        return admin_url, document_url, False
    if test_match:
        suffix = test_match.group(1)
        if configuration.database_user != f"lumi_document_test_{suffix}":
            raise RuntimeError("Test database and dedicated test role names do not match")
        if not configuration.test_database_disposable:
            raise RuntimeError("Test database provisioning requires disposable-test opt-in")
        return admin_url, document_url, True
    raise RuntimeError("Database name is outside the Document-owned namespace")


def _validate_admin_role(role: RoleState | None, current_user: str, expected_user: str) -> None:
    if current_user != expected_user or role is None or not role.superuser:
        raise RuntimeError(
            "Local provisioning requires its configured PostgreSQL bootstrap superuser"
        )


def _validate_document_role(role: RoleState | None) -> None:
    if role is None:
        return
    if not role.can_login:
        raise RuntimeError("Existing Document role is not a login role")
    if any((role.superuser, role.createdb, role.createrole, role.replication, role.bypass_rls)):
        raise RuntimeError("Existing Document role has elevated PostgreSQL privileges")


def _provisioning_plan(role: RoleState | None, database: DatabaseState | None) -> ProvisioningPlan:
    if database is not None:
        if role is None:
            raise RuntimeError("Existing Document database has no verified Document owner role")
        if database.owner_oid != role.oid:
            raise RuntimeError("Existing Document database owner does not match the Document role")
    return ProvisioningPlan(create_role=role is None, create_database=database is None)


def _validate_database_grants(grants: list[tuple[int, str]], document_role_oid: int) -> None:
    for grantee, _privilege in grants:
        if grantee not in {0, document_role_oid}:
            raise RuntimeError("Existing Document database grants access to an unapproved role")


def _role_state(connection, role_name: str) -> RoleState | None:
    row = connection.execute(
        "SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
        "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s",
        (role_name,),
    ).fetchone()
    return RoleState.from_row(row) if row is not None else None


def _database_state(connection, database_name: str) -> DatabaseState | None:
    row = connection.execute(
        "SELECT oid, datdba, shobj_description(oid, 'pg_database') "
        "FROM pg_database WHERE datname = %s",
        (database_name,),
    ).fetchone()
    return DatabaseState(*row) if row is not None else None


def _validate_role_memberships(connection, role: RoleState) -> None:
    count = connection.execute(
        "SELECT count(*) FROM pg_auth_members WHERE member = %s OR roleid = %s",
        (role.oid, role.oid),
    ).fetchone()[0]
    if count:
        raise RuntimeError("Existing Document role has PostgreSQL role memberships")


def _validate_role_ownership(connection, role: RoleState, target_database: str) -> None:
    other_database = connection.execute(
        "SELECT datname FROM pg_database WHERE datdba = %s AND datname <> %s LIMIT 1",
        (role.oid, target_database),
    ).fetchone()
    if other_database:
        raise RuntimeError("Existing Document role owns a database outside its namespace")


def _database_grants(connection, database_name: str) -> list[tuple[int, str]]:
    rows = connection.execute(
        "SELECT acl.grantee, acl.privilege_type FROM pg_database AS d "
        "CROSS JOIN LATERAL aclexplode(COALESCE(d.datacl, "
        "acldefault('d', d.datdba))) AS acl WHERE d.datname = %s",
        (database_name,),
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


def _verify_connection(connection, expected_database: str, expected_user: str) -> None:
    current_database, current_user = connection.execute(
        "SELECT current_database(), current_user"
    ).fetchone()
    if (current_database, current_user) != (expected_database, expected_user):
        raise RuntimeError("Connected PostgreSQL identity does not match the Document identity")


def _test_database_marker_action(
    *,
    is_test_database: bool,
    database_created_in_operation: bool,
    existing_database: DatabaseState | None,
) -> bool:
    """Only a database created by this invocation may receive the disposable marker."""
    if not is_test_database:
        return False
    if database_created_in_operation:
        if existing_database is not None:
            raise RuntimeError("New test database unexpectedly existed during preflight")
        return True
    if existing_database is None or existing_database.comment != _TEST_MARKER:
        raise RuntimeError(
            "Existing test database is not marked disposable; administrator reconciliation is required"
        )
    return False


def _connect_document(document_url: URL):
    try:
        return connect(
            document_url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
    except PsycopgError:
        raise RuntimeError("Could not verify the Document database login") from None


def provision_local_database(configuration: Settings = settings) -> None:
    admin_url, document_url, is_test_database = _database_identity(configuration)
    admin_conninfo = admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    database_name = configuration.database_name
    document_user = configuration.database_user
    document_password = configuration.database_password.get_secret_value()
    plan: ProvisioningPlan
    add_test_marker = is_test_database

    try:
        with connect(admin_conninfo, autocommit=True) as admin_connection:
            current_user = admin_connection.execute("SELECT current_user").fetchone()[0]
            admin_role = _role_state(admin_connection, admin_url.username)
            _validate_admin_role(admin_role, current_user, admin_url.username)

            document_role = _role_state(admin_connection, document_user)
            _validate_document_role(document_role)
            if document_role is not None:
                _validate_role_memberships(admin_connection, document_role)
                _validate_role_ownership(admin_connection, document_role, database_name)

            existing_database = _database_state(admin_connection, database_name)
            plan = _provisioning_plan(document_role, existing_database)
            add_test_marker = _test_database_marker_action(
                is_test_database=is_test_database,
                database_created_in_operation=plan.create_database,
                existing_database=existing_database,
            )
            if existing_database is not None:
                _validate_database_grants(
                    _database_grants(admin_connection, database_name), document_role.oid
                )
                with _connect_document(document_url) as document_connection:
                    _verify_connection(document_connection, database_name, document_user)
            elif document_role is not None:
                probe_url = document_url.set(database=admin_url.database)
                with _connect_document(probe_url) as probe_connection:
                    _verify_connection(probe_connection, admin_url.database, document_user)

            if plan.create_role:
                statement = sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(document_user), sql.Literal(document_password))
                admin_connection.execute(statement)

            if plan.create_database:
                statement = sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database_name), sql.Identifier(document_user)
                )
                admin_connection.execute(statement)

        with _connect_document(document_url) as document_connection:
            _verify_connection(document_connection, database_name, document_user)
            document_connection.execute(
                sql.SQL("REVOKE ALL PRIVILEGES ON DATABASE {} FROM PUBLIC").format(
                    sql.Identifier(database_name)
                )
            )
            document_connection.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(database_name), sql.Identifier(document_user)
                )
            )
            if is_test_database and add_test_marker:
                document_connection.execute(
                    sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                        sql.Identifier(database_name), sql.Literal(_TEST_MARKER)
                    )
                )
    except PsycopgError:
        raise RuntimeError(
            "Local Document provisioning failed; no password, URL, or SQL details are logged"
        ) from None


if __name__ == "__main__":
    provision_local_database()
    print("Local Document database ACL is ready.")

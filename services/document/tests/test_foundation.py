import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlalchemy.sql.schema import ForeignKeyConstraint

from document_service import bootstrap_database
from document_service.bootstrap_database import (
    DatabaseState,
    ProvisioningPlan,
    RoleState,
)
from document_service.config import Settings
from document_service.db import Base, Database, DatabaseConfigurationError
from document_service.main import create_app
from document_service.migration_config import include_name, migration_comparison_options
from document_service.model_registry import load_metadata
from document_service.models import Document, DocumentGrant, DocumentVersion, IngestionJob
from tests.integration.test_postgres_schema import _drop_document_schema
from tests.safety_guards import (
    validate_alembic_target,
    validate_database_identity,
    validate_destructive_test_urls,
    validate_non_elevated_login_role,
)


def test_metadata_contains_exactly_four_document_owned_tables():
    metadata = load_metadata()

    assert set(metadata.tables) == {
        "document.documents",
        "document.document_versions",
        "document.document_grants",
        "document.ingestion_jobs",
    }
    assert Base.metadata.schema == "document"


def test_alembic_comparison_filters_only_document_and_excludes_version_table():
    options = migration_comparison_options()

    assert options["target_metadata"] is Base.metadata
    assert options["include_schemas"] is True
    assert options["version_table_schema"] == "document"
    assert options["include_name"] is include_name
    assert include_name("document", "schema", {})
    assert not include_name("core", "schema", {})
    assert not include_name(None, "schema", {})
    assert not include_name("alembic_version", "table", {})
    assert include_name("documents", "table", {})


def test_alembic_target_must_match_the_validated_test_url_and_have_no_query():
    expected = make_url(
        "postgresql+psycopg://lumi_document_test_run_1:synthetic@test-db:5432/test_document_run_1"
    )
    validate_alembic_target(expected, expected)
    with pytest.raises(ValueError, match="not configured"):
        validate_alembic_target(
            expected.set(database="test_document_other"),
            expected,
        )
    with pytest.raises(ValueError, match="query parameters"):
        validate_alembic_target(
            expected.update_query_dict({"sslmode": "require"}),
            expected,
        )


def test_alembic_metadata_filter_matches_document_schema_and_excludes_version_table():
    options = migration_comparison_options()

    assert options["target_metadata"] is Base.metadata
    assert options["include_schemas"] is True
    assert options["version_table_schema"] == "document"
    assert options["include_name"] is include_name
    assert include_name("document", "schema", {}) is True
    assert include_name("core", "schema", {}) is False
    assert include_name(None, "schema", {}) is False
    assert include_name("alembic_version", "table", {}) is False
    assert include_name("documents", "table", {}) is True


def test_all_persisted_timestamps_are_timezone_aware_postgresql_timestamps():
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone, f"{table.name}.{column.name} must use TIMESTAMPTZ"


def test_document_version_pointers_are_composite_same_document_foreign_keys():
    pointer_constraints = [
        constraint
        for constraint in Document.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    ]
    assert {constraint.name for constraint in pointer_constraints} == {
        "fk_documents_latest_version_same_document",
        "fk_documents_active_rag_version_same_document",
    }
    for constraint in pointer_constraints:
        assert list(constraint.column_keys) in (
            ["latest_version_id", "id"],
            ["active_rag_version_id", "id"],
        )
        assert [element.target_fullname for element in constraint.elements] == [
            "document.document_versions.id",
            "document.document_versions.document_id",
        ]


def test_core_and_classroom_ids_are_logical_references_without_foreign_keys():
    external_columns = {
        Document.__table__.c.owner_id,
        DocumentGrant.__table__.c.classroom_id,
        DocumentGrant.__table__.c.granted_by,
        DocumentGrant.__table__.c.revoked_by,
    }
    for column in external_columns:
        assert not column.foreign_keys

    foreign_key_targets = {
        element.target_fullname
        for table in Base.metadata.tables.values()
        for constraint in table.foreign_key_constraints
        for element in constraint.elements
    }
    assert all(target.startswith("document.") for target in foreign_key_targets)


def test_postgresql_ddl_keeps_database_invariants_in_the_database():
    version_ddl = str(CreateTable(DocumentVersion.__table__).compile(dialect=dialect()))
    grant_indexes = "\n".join(
        str(CreateIndex(index).compile(dialect=dialect()))
        for index in DocumentGrant.__table__.indexes
    )
    job_indexes = "\n".join(
        str(CreateIndex(index).compile(dialect=dialect()))
        for index in IngestionJob.__table__.indexes
    )

    assert "TIMESTAMP WITH TIME ZONE" in version_ddl
    assert "BIGINT" in version_ddl
    assert "CHAR(64)" in version_ddl
    assert "ck_document_versions_stored_metadata" in version_ddl
    assert "uq_document_versions_document_number" in version_ddl
    assert "uq_document_versions_storage_key" in version_ddl
    assert "WHERE revoked_at IS NULL" in grant_indexes
    assert "WHERE status IN ('PENDING', 'PROCESSING')" in job_indexes
    assert any(
        constraint.name == "uq_ingestion_jobs_idempotency_key"
        for constraint in IngestionJob.__table__.constraints
    )


def test_settings_use_document_database_url_not_core_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://core_user:core_pw@db/core_db")
    monkeypatch.setenv(
        "DOCUMENT_DATABASE_URL", "postgresql+psycopg://document_user:doc_pw@db/document_db"
    )
    configuration = Settings(_env_file=None)

    assert configuration.database_url == SecretStr(
        "postgresql+psycopg://document_user:doc_pw@db/document_db"
    )
    assert (
        configuration.database_url.get_secret_value()
        != "postgresql+psycopg://core_user:core_pw@db/core_db"
    )


def test_database_without_document_url_fails_closed(monkeypatch):
    monkeypatch.delenv("DOCUMENT_DATABASE_URL", raising=False)
    database = Database(Settings(_env_file=None))

    try:
        database.ping()
    except DatabaseConfigurationError as error:
        assert "DOCUMENT_DATABASE_URL" in str(error)
    else:
        raise AssertionError("Database readiness must require a Document-specific URL")


def _valid_test_database_urls():
    document_url = (
        "postgresql+psycopg://lumi_document_test_run_1:doc@test-db:5432/test_document_run_1"
    )
    return {
        "document_test_url": document_url,
        "document_url": document_url,
        "core_url": "postgresql+psycopg://core_ci_run:core@test-db:5432/test_core_run_1",
        "unrelated_url": "postgresql+psycopg://unrelated_document_test_run_1:unrelated@test-db:5432/test_document_run_1",
        "allowed_hosts": "test-db",
        "destructive_opt_in": True,
        "disposable_opt_in": True,
    }


def test_destructive_test_url_guard_requires_explicit_opt_ins_and_service_identities():
    urls = validate_destructive_test_urls(**_valid_test_database_urls())
    assert urls.document.database == "test_document_run_1"
    assert urls.core.database == "test_core_run_1"
    assert urls.unrelated.database == urls.document.database

    for mutation in (
        {"destructive_opt_in": False},
        {"disposable_opt_in": False},
        {"document_test_url": "sqlite:///test_document_run_1.db"},
        {"document_test_url": "postgresql+psycopg://doc@test-db:5432/lumi_document"},
        {
            "document_url": "postgresql+psycopg://lumi_document_test_run_1:wrong@test-db:5432/test_document_run_1"
        },
        {"unrelated_url": "postgresql+psycopg://doc@test-db:5432/test_document_run_1"},
        {"allowed_hosts": "localhost"},
    ):
        candidate = _valid_test_database_urls()
        candidate.update(mutation)
        with pytest.raises(ValueError):
            validate_destructive_test_urls(**candidate)

    for key in (
        "document_test_url",
        "document_url",
        "core_url",
        "unrelated_url",
    ):
        candidate = _valid_test_database_urls()
        candidate[key] += "?sslmode=require"
        with pytest.raises(ValueError, match="query parameters"):
            validate_destructive_test_urls(**candidate)


def test_destructive_identity_guard_rejects_mismatch_superuser_membership_and_public_acl():
    valid = {
        "current_database": "test_document_run_1",
        "current_user": "lumi_document_test_run_1",
        "expected_database": "test_document_run_1",
        "expected_user": "lumi_document_test_run_1",
        "owner_matches": True,
        "comment": "lumi-document-test-disposable:v1",
        "expected_comment": "lumi-document-test-disposable:v1",
        "elevated": False,
        "role_memberships": 0,
        "public_grants": False,
        "unapproved_grantees": False,
        "can_connect": True,
    }
    validate_database_identity(**valid)
    for mutation in (
        {"current_database": "production"},
        {"current_user": "postgres"},
        {"owner_matches": False},
        {"comment": None},
        {"elevated": True},
        {"role_memberships": 1},
        {"public_grants": True},
        {"unapproved_grantees": True},
        {"can_connect": False},
    ):
        candidate = valid | mutation
        with pytest.raises(ValueError):
            validate_database_identity(**candidate)

    with pytest.raises(ValueError):
        validate_non_elevated_login_role(
            role_exists=True, can_login=True, elevated=True, role_memberships=0
        )
    with pytest.raises(ValueError):
        validate_non_elevated_login_role(
            role_exists=True, can_login=True, elevated=False, role_memberships=1
        )


def test_destructive_guard_failure_does_not_execute_drop_on_the_connection():
    class Result:
        def __init__(self, row=None, values=None):
            self.row = row
            self.values = values or []

        def one(self):
            return self.row

        def scalars(self):
            return self

        def all(self):
            return self.values

    class Connection:
        def __init__(self, database_name):
            self.database_name = database_name
            self.drop_calls = []

        def execute(self, statement, _parameters=None):
            query = str(statement)
            if "SELECT current_database(), current_user" in query:
                return Result(
                    (
                        self.database_name,
                        "lumi_document_test_run_1",
                        42,
                        False,
                        False,
                        False,
                        False,
                        False,
                        42,
                        "lumi-document-test-disposable:v1",
                    )
                )
            if "SELECT DISTINCT acl.grantee" in query:
                return Result(values=[42])
            if query.startswith("DROP SCHEMA"):
                self.drop_calls.append(query)
                return Result()
            raise AssertionError(f"Unexpected guard query: {query}")

        def scalar(self, statement, _parameters=None):
            query = str(statement)
            if "pg_auth_members" in query:
                return 0
            if "acl.grantee = 0" in query:
                return False
            if "has_database_privilege" in query:
                return True
            raise AssertionError(f"Unexpected guard scalar query: {query}")

    target = make_url(
        "postgresql+psycopg://lumi_document_test_run_1:synthetic@test-db:5432/test_document_run_1"
    )
    connection = Connection("production")

    with pytest.raises(ValueError, match="Connected database/user"):
        _drop_document_schema(connection, target)
    assert connection.drop_calls == []


def test_destructive_drop_uses_the_connection_that_passed_identity_guard():
    class Result:
        def __init__(self, row=None, values=None):
            self.row = row
            self.values = values or []

        def one(self):
            return self.row

        def scalars(self):
            return self

        def all(self):
            return self.values

    class Connection:
        def __init__(self):
            self.drop_calls = []

        def execute(self, statement, _parameters=None):
            query = str(statement)
            if "SELECT current_database(), current_user" in query:
                return Result(
                    (
                        "test_document_run_1",
                        "lumi_document_test_run_1",
                        42,
                        False,
                        False,
                        False,
                        False,
                        False,
                        42,
                        "lumi-document-test-disposable:v1",
                    )
                )
            if "SELECT DISTINCT acl.grantee" in query:
                return Result(values=[42])
            if query.startswith("DROP SCHEMA"):
                self.drop_calls.append(query)
                return Result()
            raise AssertionError(f"Unexpected guard query: {query}")

        def scalar(self, statement, _parameters=None):
            query = str(statement)
            if "pg_auth_members" in query:
                return 0
            if "acl.grantee = 0" in query:
                return False
            if "has_database_privilege" in query:
                return True
            raise AssertionError(f"Unexpected guard scalar query: {query}")

    target = make_url(
        "postgresql+psycopg://lumi_document_test_run_1:synthetic@test-db:5432/test_document_run_1"
    )
    connection = Connection()

    _drop_document_schema(connection, target)

    assert len(connection.drop_calls) == 1


def _bootstrap_settings(*, admin_url, database_url, database_name, database_user):
    return Settings(
        database_admin_url=SecretStr(admin_url),
        database_url=SecretStr(database_url),
        database_name=database_name,
        database_user=database_user,
        database_password=SecretStr("synthetic-local-test-password"),
        allow_local_database_provisioning=True,
        _env_file=None,
    )


def test_bootstrap_refuses_remote_host_and_invalid_names_before_connect(monkeypatch):
    admin = "postgresql+psycopg://admin:synthetic@db.example.invalid/postgres"
    app = "postgresql+psycopg://lumi_document:synthetic-local-test-password@db.example.invalid/lumi_document"
    calls = []
    monkeypatch.setattr(bootstrap_database, "connect", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(RuntimeError, match="local PostgreSQL host"):
        bootstrap_database.provision_local_database(
            _bootstrap_settings(
                admin_url=admin,
                database_url=app,
                database_name="lumi_document",
                database_user="lumi_document",
            )
        )

    local_admin = "postgresql+psycopg://admin:synthetic@localhost/postgres"
    invalid_app = (
        "postgresql+psycopg://rag_course:synthetic-local-test-password@localhost/rag_course"
    )
    with pytest.raises(RuntimeError, match="Document-owned namespace"):
        bootstrap_database.provision_local_database(
            _bootstrap_settings(
                admin_url=local_admin,
                database_url=invalid_app,
                database_name="rag_course",
                database_user="rag_course",
            )
        )
    assert calls == []


def test_bootstrap_requires_explicit_opt_in():
    configuration = _bootstrap_settings(
        admin_url="postgresql+psycopg://admin:synthetic@localhost/postgres",
        database_url="postgresql+psycopg://lumi_document:synthetic-local-test-password@localhost/lumi_document",
        database_name="lumi_document",
        database_user="lumi_document",
    ).model_copy(update={"allow_local_database_provisioning": False})

    try:
        bootstrap_database._database_identity(configuration)
    except RuntimeError as error:
        assert "explicit opt-in" in str(error)
    else:
        raise AssertionError("Provisioning must require explicit local/test opt-in")


def test_bootstrap_rejects_admin_or_document_url_query_parameters_before_connect(monkeypatch):
    admin = "postgresql+psycopg://admin:synthetic@localhost/postgres"
    document = (
        "postgresql+psycopg://lumi_document:synthetic-local-test-password@localhost/lumi_document"
    )
    attempted_connections = []
    monkeypatch.setattr(
        bootstrap_database,
        "connect",
        lambda *args, **kwargs: attempted_connections.append(args),
    )

    for admin_url, document_url in (
        (admin + "?sslmode=require", document),
        (admin, document + "?sslmode=require"),
    ):
        configuration = _bootstrap_settings(
            admin_url=admin_url,
            database_url=document_url,
            database_name="lumi_document",
            database_user="lumi_document",
        )
        with pytest.raises(RuntimeError, match="query parameters"):
            bootstrap_database.provision_local_database(configuration)
    assert attempted_connections == []


def test_database_role_and_namespace_names_are_document_specific():
    cases = [
        ("rag_course", "rag_course"),
        ("lumi_core", "lumi_document"),
        ("lumi_document", "rag_course"),
        ("test_document_run_1", "lumi_document"),
    ]
    for database_name, database_user in cases:
        configuration = _bootstrap_settings(
            admin_url="postgresql+psycopg://admin:synthetic@localhost/postgres",
            database_url=(
                f"postgresql+psycopg://{database_user}:synthetic-local-test-password"
                f"@localhost/{database_name}"
            ),
            database_name=database_name,
            database_user=database_user,
        )
        if database_name.startswith("test_document_"):
            configuration = configuration.model_copy(update={"test_database_disposable": True})
        try:
            bootstrap_database._database_identity(configuration)
        except RuntimeError:
            continue
        raise AssertionError(
            f"Unexpectedly accepted non-Document identity: {database_name}/{database_user}"
        )


def test_bootstrap_rejects_elevated_existing_document_role():
    role = RoleState(
        oid=42,
        can_login=True,
        superuser=True,
        createdb=False,
        createrole=False,
        replication=False,
        bypass_rls=False,
    )
    with pytest.raises(RuntimeError, match="elevated PostgreSQL privileges"):
        bootstrap_database._validate_document_role(role)


def test_bootstrap_requires_a_superuser_administrator_and_does_not_claim_to_limit_it():
    non_superuser = RoleState(
        oid=7,
        can_login=True,
        superuser=False,
        createdb=True,
        createrole=True,
        replication=False,
        bypass_rls=False,
    )
    with pytest.raises(RuntimeError, match="bootstrap superuser"):
        bootstrap_database._validate_admin_role(non_superuser, "admin", "admin")


def test_bootstrap_acl_accepts_public_for_revocation_and_document_owner_only():
    bootstrap_database._validate_database_grants([(0, "CONNECT"), (42, "CREATE")], 42)
    with pytest.raises(RuntimeError, match="unapproved role"):
        bootstrap_database._validate_database_grants([(0, "CONNECT"), (88, "CONNECT")], 42)


def test_disposable_marker_only_applies_to_database_created_by_current_operation():
    already_marked = DatabaseState(oid=5, owner_oid=42, comment="lumi-document-test-disposable:v1")
    unmarked_empty = DatabaseState(oid=5, owner_oid=42, comment=None)
    unmarked_with_other_comment = DatabaseState(oid=5, owner_oid=42, comment="not disposable")

    assert (
        bootstrap_database._test_database_marker_action(
            is_test_database=True,
            database_created_in_operation=True,
            existing_database=None,
        )
        is True
    )
    assert (
        bootstrap_database._test_database_marker_action(
            is_test_database=False,
            database_created_in_operation=True,
            existing_database=None,
        )
        is False
    )
    assert (
        bootstrap_database._test_database_marker_action(
            is_test_database=True,
            database_created_in_operation=False,
            existing_database=already_marked,
        )
        is False
    )

    # Existing DBs fail closed regardless of whether the catalog appears empty;
    # an interrupted first provisioning therefore requires administrator review.
    for existing_database in (unmarked_empty, unmarked_with_other_comment):
        with pytest.raises(RuntimeError, match="administrator reconciliation"):
            bootstrap_database._test_database_marker_action(
                is_test_database=True,
                database_created_in_operation=False,
                existing_database=existing_database,
            )
    with pytest.raises(RuntimeError, match="unexpectedly existed"):
        bootstrap_database._test_database_marker_action(
            is_test_database=True,
            database_created_in_operation=True,
            existing_database=unmarked_empty,
        )


def test_bootstrap_rejects_existing_database_with_wrong_owner_before_mutation():
    role = RoleState(42, True, False, False, False, False, False)
    database = DatabaseState(oid=7, owner_oid=99, comment=None)

    with pytest.raises(RuntimeError, match="owner does not match"):
        bootstrap_database._provisioning_plan(role, database)


def test_wrong_existing_database_owner_causes_no_provisioning_mutation(monkeypatch):
    statements = []

    class Result:
        def __init__(self, row=None, rows=None):
            self.row = row
            self.rows = rows or []

        def fetchone(self):
            return self.row

        def fetchall(self):
            return self.rows

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement, parameters=None):
            query = str(statement)
            if query.startswith(("CREATE ", "ALTER ", "REVOKE ", "GRANT ", "COMMENT ")):
                statements.append(query)
            if query == "SELECT current_user":
                return Result(("admin",))
            if "FROM pg_roles WHERE rolname = %s" in query:
                role_name = parameters[0]
                if role_name == "admin":
                    return Result((1, True, True, True, True, True, True))
                return Result((42, True, False, False, False, False, False))
            if "FROM pg_auth_members" in query:
                return Result((0,))
            if "FROM pg_database WHERE datdba" in query:
                return Result(None)
            if "FROM pg_database WHERE datname = %s" in query:
                return Result((7, 99, None))
            raise AssertionError(f"Unexpected preflight query: {query}")

    monkeypatch.setattr(bootstrap_database, "connect", lambda *_args, **_kwargs: FakeConnection())
    config = _bootstrap_settings(
        admin_url="postgresql+psycopg://admin:synthetic@localhost/postgres",
        database_url="postgresql+psycopg://lumi_document:synthetic-local-test-password@localhost/lumi_document",
        database_name="lumi_document",
        database_user="lumi_document",
    )

    with pytest.raises(RuntimeError, match="owner does not match"):
        bootstrap_database.provision_local_database(config)
    assert statements == []


def test_bootstrap_plan_is_idempotent_for_existing_valid_resources():
    role = RoleState(42, True, False, False, False, False, False)
    database = DatabaseState(oid=7, owner_oid=42, comment=None)

    first = bootstrap_database._provisioning_plan(role, database)
    second = bootstrap_database._provisioning_plan(role, database)

    assert first == second
    assert first.create_role is False
    assert first.create_database is False
    assert bootstrap_database._provisioning_plan(role, None) == ProvisioningPlan(
        create_role=False, create_database=True
    )
    assert bootstrap_database._provisioning_plan(None, None) == ProvisioningPlan(
        create_role=True, create_database=True
    )


def test_health_only_app_reports_liveness_and_fails_readiness_without_database():
    app = create_app(Database(Settings(_env_file=None)))

    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/live").json() == {"status": "live"}
        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json() == {"detail": "Document database unavailable"}
        assert client.get("/api/v1/documents").status_code == 404
        assert client.get("/docs").status_code == 404


def test_storage_contract_types_are_independent_of_service_settings():
    assert Document.__table__.schema == "document"
    assert DocumentVersion.__table__.schema == "document"
    assert DocumentGrant.__table__.schema == "document"
    assert IngestionJob.__table__.schema == "document"

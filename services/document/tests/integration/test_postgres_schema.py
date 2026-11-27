from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from psycopg import Error as PsycopgError
from psycopg import connect
from pydantic import SecretStr
from sqlalchemy import create_engine, insert, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from document_service import bootstrap_database
from document_service.bootstrap_database import provision_local_database
from document_service.config import Settings
from document_service.db import Base
from document_service.migration_config import include_name, migration_comparison_options
from document_service.models import Document, DocumentGrant, DocumentVersion, IngestionJob
from tests.safety_guards import (
    validate_alembic_target,
    validate_database_identity,
    validate_destructive_test_urls,
    validate_non_elevated_login_role,
)

_TEST_URL = os.getenv("DOCUMENT_TEST_DATABASE_URL")
_DISPOSABLE_MARKER = "lumi-document-test-disposable:v1"
_CORE_DISPOSABLE_MARKER = "lumi-core-test-disposable:v1"
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not _TEST_URL, reason="DOCUMENT_TEST_DATABASE_URL is not configured"),
]


def _truthy_environment(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def _validate_test_urls():
    assert _TEST_URL is not None
    if os.getenv("DOCUMENT_TEST_DATABASE_URL") != _TEST_URL:
        pytest.fail("DOCUMENT_TEST_DATABASE_URL changed after integration-test collection")
    try:
        urls = validate_destructive_test_urls(
            document_test_url=_TEST_URL,
            document_url=os.getenv("DOCUMENT_DATABASE_URL"),
            core_url=os.getenv("CORE_TEST_DATABASE_URL"),
            unrelated_url=os.getenv("UNRELATED_TEST_DATABASE_URL"),
            allowed_hosts=os.getenv("DOCUMENT_TEST_ALLOWED_HOSTS"),
            destructive_opt_in=_truthy_environment("DOCUMENT_ALLOW_DESTRUCTIVE_TESTS"),
            disposable_opt_in=_truthy_environment("DOCUMENT_TEST_DATABASE_DISPOSABLE"),
        )
    except ValueError as error:
        pytest.fail(str(error))
    return urls.document, urls.core, urls.unrelated


def _assert_database_disposable(connection, expected_url, expected_marker: str) -> None:
    identity = connection.execute(
        text(
            "SELECT current_database(), current_user, r.oid, r.rolsuper, r.rolcreatedb, "
            "r.rolcreaterole, r.rolreplication, r.rolbypassrls, d.datdba, "
            "shobj_description(d.oid, 'pg_database') "
            "FROM pg_database AS d JOIN pg_roles AS r ON r.rolname = current_user "
            "WHERE d.datname = current_database()"
        )
    ).one()
    memberships = connection.scalar(
        text("SELECT count(*) FROM pg_auth_members WHERE member = :oid OR roleid = :oid"),
        {"oid": identity[2]},
    )
    public_grant = connection.scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM pg_database AS d "
            "CROSS JOIN LATERAL aclexplode(COALESCE(d.datacl, "
            "acldefault('d', d.datdba))) AS acl "
            "WHERE d.datname = current_database() AND acl.grantee = 0)"
        )
    )
    acl_grantees = (
        connection.execute(
            text(
                "SELECT DISTINCT acl.grantee FROM pg_database AS d "
                "CROSS JOIN LATERAL aclexplode(COALESCE(d.datacl, "
                "acldefault('d', d.datdba))) AS acl "
                "WHERE d.datname = current_database()"
            )
        )
        .scalars()
        .all()
    )
    can_connect = connection.scalar(
        text("SELECT has_database_privilege(current_user, current_database(), 'CONNECT')")
    )
    validate_database_identity(
        current_database=identity[0],
        current_user=identity[1],
        expected_database=expected_url.database,
        expected_user=expected_url.username,
        owner_matches=identity[8] == identity[2],
        comment=identity[9],
        expected_comment=expected_marker,
        elevated=any(identity[index] for index in (3, 4, 5, 6, 7)),
        role_memberships=memberships,
        public_grants=public_grant,
        unapproved_grantees=any(grantee != identity[2] for grantee in acl_grantees),
        can_connect=can_connect,
    )


def _drop_document_schema(connection, expected_url) -> None:
    _assert_database_disposable(connection, expected_url, _DISPOSABLE_MARKER)
    connection.execute(text("DROP SCHEMA IF EXISTS document CASCADE"))


def _assert_core_test_database(engine, core_url, document_url) -> None:
    with engine.connect() as connection:
        _assert_database_disposable(connection, core_url, _CORE_DISPOSABLE_MARKER)
        document_connect = connection.scalar(
            text("SELECT has_database_privilege(:role, current_database(), 'CONNECT')"),
            {"role": document_url.username},
        )
    if document_connect:
        pytest.fail("Document role unexpectedly has CONNECT access to the synthetic Core database")


def _validate_unrelated_role(engine, unrelated_url, document_url) -> None:
    with engine.connect() as connection:
        role_row = connection.execute(
            text(
                "SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole, "
                "rolreplication, rolbypassrls FROM pg_roles WHERE rolname = :role"
            ),
            {"role": unrelated_url.username},
        ).one_or_none()
        if role_row is None:
            pytest.fail("Synthetic unrelated role is missing")
        memberships = connection.scalar(
            text("SELECT count(*) FROM pg_auth_members WHERE member = :oid OR roleid = :oid"),
            {"oid": role_row[0]},
        )
        has_connect = connection.scalar(
            text("SELECT has_database_privilege(:role, current_database(), 'CONNECT')"),
            {"role": unrelated_url.username},
        )
        try:
            validate_non_elevated_login_role(
                role_exists=role_row is not None,
                can_login=bool(role_row and role_row[1]),
                elevated=bool(role_row and any(role_row[index] for index in (2, 3, 4, 5, 6))),
                role_memberships=memberships,
            )
            if has_connect:
                raise ValueError("Synthetic unrelated role has effective CONNECT privilege")
        except ValueError as error:
            pytest.fail(str(error))


@pytest.fixture(scope="module")
def document_engine():
    assert _TEST_URL is not None
    document_url, core_url, unrelated_url = _validate_test_urls()
    engine = create_engine(_TEST_URL, pool_pre_ping=True, hide_parameters=True)
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    config.set_main_option("sqlalchemy.url", _TEST_URL.replace("%", "%%"))
    try:
        validate_alembic_target(make_url(config.get_main_option("sqlalchemy.url")), document_url)
    except ValueError as error:
        pytest.fail(str(error))
    destructive_target_verified = False
    try:
        core_engine = create_engine(str(core_url), pool_pre_ping=True, hide_parameters=True)
        try:
            _assert_core_test_database(core_engine, core_url, document_url)
        finally:
            core_engine.dispose()
        _validate_unrelated_role(engine, unrelated_url, document_url)
        destructive_target_verified = True
        with engine.begin() as connection:
            _drop_document_schema(connection, document_url)
        command.upgrade(config, "head")
        yield engine
    finally:
        try:
            if destructive_target_verified:
                teardown_urls = _validate_test_urls()
                if teardown_urls != (document_url, core_url, unrelated_url):
                    pytest.fail("Disposable database identities changed before teardown")
                core_engine = create_engine(str(core_url), pool_pre_ping=True, hide_parameters=True)
                try:
                    _assert_core_test_database(core_engine, core_url, document_url)
                finally:
                    core_engine.dispose()
                _validate_unrelated_role(engine, unrelated_url, document_url)
                with engine.begin() as connection:
                    _drop_document_schema(connection, document_url)
        finally:
            engine.dispose()


def _new_document(engine) -> UUID:
    with engine.begin() as connection:
        return connection.execute(
            insert(Document)
            .values(owner_id=uuid4(), title="synthetic document")
            .returning(Document.id)
        ).scalar_one()


def _new_version(engine, document_id, **overrides):
    values = {
        "document_id": document_id,
        "version_number": 1,
        "file_status": "FAILED",
    }
    values.update(overrides)
    with engine.begin() as connection:
        return connection.execute(
            insert(DocumentVersion).values(**values).returning(DocumentVersion.id)
        ).scalar_one()


def _new_job_values(version_id, **overrides):
    values = {
        "version_id": version_id,
        "idempotency_key": str(uuid4()),
        "status": "FAILED",
        "attempt_number": 0,
    }
    values.update(overrides)
    return values


def test_initial_migration_and_metadata_are_consistent(document_engine):
    with document_engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM document.alembic_version"))
        comparison_options = migration_comparison_options()
        assert comparison_options["version_table_schema"] == "document"
        assert comparison_options["include_schemas"] is True
        assert comparison_options["include_name"] is include_name
        differences = compare_metadata(
            MigrationContext.configure(connection, opts=comparison_options), Base.metadata
        )

    assert revision == "0001"
    assert differences == []


def test_composite_pointers_reject_a_version_from_another_document(document_engine):
    first_document = _new_document(document_engine)
    second_document = _new_document(document_engine)
    first_version = _new_version(document_engine, first_document)
    second_version = _new_version(document_engine, second_document)

    with document_engine.begin() as connection:
        connection.execute(
            update(Document)
            .where(Document.id == first_document)
            .values(latest_version_id=first_version)
        )
    with pytest.raises(IntegrityError), document_engine.begin() as connection:
        connection.execute(
            update(Document)
            .where(Document.id == first_document)
            .values(active_rag_version_id=second_version)
        )


def test_unique_version_and_storage_key_and_stored_metadata_constraints(document_engine):
    document_id = _new_document(document_engine)
    storage_values = {
        "file_status": "STORED",
        "storage_key": f"documents/{uuid4()}/versions/{uuid4()}",
        "original_filename": "course.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 0,
        "sha256": "0" * 64,
        "stored_at": text("now()"),
    }
    _new_version(document_engine, document_id, **storage_values)
    other_document = _new_document(document_engine)
    _new_version(
        document_engine,
        other_document,
        file_status="STORED",
        storage_key=f"documents/{uuid4()}/versions/{uuid4()}",
        original_filename="same-content.pdf",
        mime_type="application/pdf",
        size_bytes=0,
        sha256="0" * 64,
        stored_at=text("now()"),
    )

    with pytest.raises(IntegrityError):
        _new_version(
            document_engine,
            document_id,
            version_number=1,
            file_status="STORED",
            storage_key=f"documents/{uuid4()}/versions/{uuid4()}",
            original_filename="another.pdf",
            mime_type="application/pdf",
            size_bytes=1,
            sha256="1" * 64,
            stored_at=text("now()"),
        )
    with pytest.raises(IntegrityError):
        _new_version(document_engine, document_id, file_status="STORED")
    with pytest.raises(IntegrityError):
        _new_version(
            document_engine,
            _new_document(document_engine),
            version_number=1,
            file_status="STORED",
            storage_key=storage_values["storage_key"],
            original_filename="duplicate.pdf",
            mime_type="application/pdf",
            size_bytes=1,
            sha256="2" * 64,
            stored_at=text("now()"),
        )


@pytest.mark.parametrize(
    "values",
    [
        {"version_number": 0},
        {"size_bytes": -1},
        {"sha256": "not-a-checksum"},
        {"file_status": "READY"},
    ],
)
def test_invalid_version_values_are_rejected_by_postgresql(document_engine, values):
    with pytest.raises(IntegrityError):
        _new_version(document_engine, _new_document(document_engine), **values)


def test_document_and_job_status_values_are_checked_by_postgresql(document_engine):
    with pytest.raises(IntegrityError), document_engine.begin() as connection:
        connection.execute(
            insert(Document).values(owner_id=uuid4(), title="invalid", status="READY")
        )

    document_id = _new_document(document_engine)
    version_id = _new_version(document_engine, document_id)
    with pytest.raises(IntegrityError), document_engine.begin() as connection:
        connection.execute(
            insert(IngestionJob).values(**_new_job_values(version_id, status="READY"))
        )
    with pytest.raises(IntegrityError), document_engine.begin() as connection:
        connection.execute(
            insert(IngestionJob).values(**_new_job_values(version_id, attempt_number=-1))
        )


def test_partial_unique_index_preserves_revoked_grant_history(document_engine):
    document_id = _new_document(document_engine)
    classroom_id = uuid4()
    first_grant = uuid4()
    with document_engine.begin() as connection:
        connection.execute(
            insert(DocumentGrant).values(
                id=first_grant,
                document_id=document_id,
                classroom_id=classroom_id,
                granted_by=uuid4(),
            )
        )
    with pytest.raises(IntegrityError), document_engine.begin() as connection:
        connection.execute(
            insert(DocumentGrant).values(
                document_id=document_id,
                classroom_id=classroom_id,
                granted_by=uuid4(),
            )
        )

    with document_engine.begin() as connection:
        connection.execute(
            update(DocumentGrant)
            .where(DocumentGrant.id == first_grant)
            .values(revoked_by=uuid4(), revoked_at=text("now()"))
        )
        connection.execute(
            insert(DocumentGrant).values(
                document_id=document_id,
                classroom_id=classroom_id,
                granted_by=uuid4(),
            )
        )


def test_idempotency_and_active_job_constraints(document_engine):
    document_id = _new_document(document_engine)
    first_version = _new_version(document_engine, document_id)
    second_version = _new_version(document_engine, document_id, version_number=2)
    shared_key = str(uuid4())
    with document_engine.begin() as connection:
        connection.execute(
            insert(IngestionJob).values(
                **_new_job_values(first_version, idempotency_key=shared_key)
            )
        )
    with pytest.raises(IntegrityError), document_engine.begin() as connection:
        connection.execute(
            insert(IngestionJob).values(
                **_new_job_values(second_version, idempotency_key=shared_key)
            )
        )

    with document_engine.begin() as connection:
        connection.execute(
            insert(IngestionJob).values(
                **_new_job_values(first_version, status="PENDING", idempotency_key=str(uuid4()))
            )
        )
    with pytest.raises(IntegrityError), document_engine.begin() as connection:
        connection.execute(
            insert(IngestionJob).values(
                **_new_job_values(
                    first_version,
                    status="PROCESSING",
                    idempotency_key=str(uuid4()),
                )
            )
        )


def test_concurrent_version_number_collision_is_rejected_by_database(document_engine):
    document_id = _new_document(document_engine)
    barrier = Barrier(2)

    def insert_same_version():
        with document_engine.connect() as connection:
            transaction = connection.begin()
            try:
                barrier.wait(timeout=10)
                connection.execute(
                    insert(DocumentVersion).values(
                        document_id=document_id,
                        version_number=9,
                        file_status="FAILED",
                    )
                )
                transaction.commit()
                return True
            except IntegrityError:
                transaction.rollback()
                return False
            except BaseException:
                transaction.rollback()
                raise

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: insert_same_version(), range(2)))

    assert sorted(outcomes) == [False, True]


def test_document_database_credentials_are_separate_from_core(document_engine):
    document_url, core_url, unrelated_url = _validate_test_urls()
    core_engine = create_engine(str(core_url), pool_pre_ping=True, hide_parameters=True)
    try:
        with (
            document_engine.connect() as document_connection,
            core_engine.connect() as core_connection,
        ):
            document_identity = document_connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            core_identity = core_connection.execute(
                text("SELECT current_database(), current_user")
            ).one()
            assert document_identity.current_database != core_identity.current_database
            assert document_identity.current_user != core_identity.current_user

            doc_role_has_core_access = core_connection.scalar(
                text("SELECT has_database_privilege(:role, current_database(), 'CONNECT')"),
                {"role": document_url.username},
            )
            core_role_has_document_access = document_connection.scalar(
                text("SELECT has_database_privilege(:role, current_database(), 'CONNECT')"),
                {"role": core_url.username},
            )
            unrelated_role_has_document_access = document_connection.scalar(
                text("SELECT has_database_privilege(:role, current_database(), 'CONNECT')"),
                {"role": unrelated_url.username},
            )
            assert not doc_role_has_core_access
            assert not core_role_has_document_access
            assert not unrelated_role_has_document_access

            grants = bootstrap_database._database_grants(document_connection, document_url.database)
            doc_role_oid = document_connection.scalar(
                text("SELECT oid FROM pg_roles WHERE rolname = current_user")
            )
            bootstrap_database._validate_database_grants(grants, doc_role_oid)

        with (
            pytest.raises(PsycopgError) as unrelated_error,
            connect(
                unrelated_url.set(drivername="postgresql").render_as_string(hide_password=False)
            ),
        ):
            pass
        assert unrelated_error.value.sqlstate == "42501"

        with (
            pytest.raises(PsycopgError) as cross_service_error,
            connect(
                document_url.set(
                    database=core_url.database, drivername="postgresql"
                ).render_as_string(hide_password=False)
            ),
        ):
            pass
        assert cross_service_error.value.sqlstate == "42501"
    finally:
        core_engine.dispose()


def test_local_provisioning_is_idempotent_and_does_not_reset_existing_password(
    document_engine,
):
    document_url, _core_url, _unrelated_url = _validate_test_urls()
    configuration = Settings(
        database_admin_url=SecretStr(os.environ["DOCUMENT_DATABASE_ADMIN_URL"]),
        database_url=SecretStr(os.environ["DOCUMENT_DATABASE_URL"]),
        database_name=document_url.database,
        database_user=document_url.username,
        database_password=SecretStr(document_url.password),
        allow_local_database_provisioning=True,
        test_database_disposable=True,
        _env_file=None,
    )
    provision_local_database(configuration)
    provision_local_database(configuration)

    wrong_password = "synthetic-wrong-document-password"
    wrong_url = document_url.set(password=wrong_password).render_as_string(hide_password=False)
    wrong_configuration = configuration.model_copy(
        update={
            "database_url": SecretStr(wrong_url),
            "database_password": SecretStr(wrong_password),
        }
    )
    with pytest.raises(RuntimeError, match="Could not verify the Document database login"):
        provision_local_database(wrong_configuration)

    _assert_database_disposable(document_engine, document_url, _DISPOSABLE_MARKER)

from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url


@dataclass(frozen=True)
class TestDatabaseURLs:
    document: URL
    core: URL
    unrelated: URL


def validate_destructive_test_urls(
    *,
    document_test_url: str | None,
    document_url: str | None,
    core_url: str | None,
    unrelated_url: str | None,
    allowed_hosts: str | None,
    destructive_opt_in: bool,
    disposable_opt_in: bool,
) -> TestDatabaseURLs:
    if not destructive_opt_in:
        raise ValueError("DOCUMENT_ALLOW_DESTRUCTIVE_TESTS=true is required")
    if not disposable_opt_in:
        raise ValueError("DOCUMENT_TEST_DATABASE_DISPOSABLE=true is required")
    if not document_test_url or not document_url or not core_url or not unrelated_url:
        raise ValueError("Document, Core, and unrelated test database URLs are required")
    allowed = {host.strip().lower() for host in (allowed_hosts or "").split(",") if host.strip()}
    if not allowed:
        raise ValueError(
            "DOCUMENT_TEST_ALLOWED_HOSTS must explicitly identify disposable test hosts"
        )

    document = make_url(document_test_url)
    configured_document = make_url(document_url)
    core = make_url(core_url)
    unrelated = make_url(unrelated_url)
    if any(url.query for url in (document, configured_document, core, unrelated)):
        raise ValueError("Destructive test URLs must not include query parameters")
    test_hosts = {document.host, configured_document.host, core.host, unrelated.host}
    if None in test_hosts or not {host.lower() for host in test_hosts if host} <= allowed:
        raise ValueError("A test database URL host is not in DOCUMENT_TEST_ALLOWED_HOSTS")
    suffix = (document.database or "").removeprefix("test_document_")
    if (
        document.drivername != "postgresql+psycopg"
        or not suffix
        or suffix == document.database
        or document.username != f"lumi_document_test_{suffix}"
    ):
        raise ValueError(
            "Document test URL must use its dedicated test_document_ database and role"
        )
    if (
        configured_document.drivername != "postgresql+psycopg"
        or (configured_document.database, configured_document.username)
        != (document.database, document.username)
        or configured_document.password != document.password
        or (configured_document.host, configured_document.port or 5432)
        != (document.host, document.port or 5432)
    ):
        raise ValueError("DOCUMENT_DATABASE_URL must match DOCUMENT_TEST_DATABASE_URL")
    if (
        core.drivername != "postgresql+psycopg"
        or not (core.database or "").startswith("test_core_")
        or not (core.username or "").startswith("core_ci_")
        or core.database == document.database
        or core.username == document.username
        or (core.host, core.port or 5432) != (document.host, document.port or 5432)
    ):
        raise ValueError(
            "Core test URL must identify a separate PostgreSQL test_core_ database and role"
        )
    if (
        unrelated.drivername != "postgresql+psycopg"
        or unrelated.database != document.database
        or not (unrelated.username or "").startswith("unrelated_document_test_")
        or unrelated.username == document.username
        or (unrelated.host, unrelated.port or 5432) != (document.host, document.port or 5432)
    ):
        raise ValueError(
            "Unrelated test URL must use a dedicated role on the Document test database"
        )
    return TestDatabaseURLs(document=document, core=core, unrelated=unrelated)


def validate_database_identity(
    *,
    current_database: str,
    current_user: str,
    expected_database: str | None,
    expected_user: str | None,
    owner_matches: bool,
    comment: str | None,
    expected_comment: str,
    elevated: bool,
    role_memberships: int,
    public_grants: bool,
    unapproved_grantees: bool,
    can_connect: bool,
) -> None:
    if (current_database, current_user) != (expected_database, expected_user):
        raise ValueError("Connected database/user do not match the expected test identity")
    if not owner_matches or comment != expected_comment:
        raise ValueError("Test database owner or disposable marker does not match")
    if elevated:
        raise ValueError("Destructive test role must not have elevated PostgreSQL privileges")
    if role_memberships:
        raise ValueError("Destructive test role must not have PostgreSQL role memberships")
    if public_grants:
        raise ValueError("Test database still grants privileges to PUBLIC")
    if unapproved_grantees:
        raise ValueError("Test database ACL contains a grantee outside its owner role")
    if not can_connect:
        raise ValueError("Expected test role cannot connect to its own test database")


def validate_alembic_target(configured_url: URL, expected_test_url: URL) -> None:
    if configured_url.query or expected_test_url.query:
        raise ValueError("Alembic test target URLs must not include query parameters")

    def identity(url: URL) -> tuple[str, str | None, int, str | None, str | None, str | None]:
        return (
            url.drivername,
            url.host,
            url.port or 5432,
            url.database,
            url.username,
            url.password,
        )

    if identity(configured_url) != identity(expected_test_url):
        raise ValueError("Alembic is not configured to use the validated disposable test URL")


def validate_non_elevated_login_role(
    *,
    role_exists: bool,
    can_login: bool,
    elevated: bool,
    role_memberships: int,
) -> None:
    if not role_exists or not can_login or elevated:
        raise ValueError("Synthetic unrelated role is missing or has elevated privileges")
    if role_memberships:
        raise ValueError("Synthetic unrelated role must not have PostgreSQL role memberships")

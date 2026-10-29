"""Run from services/core: python -m app.maintenance --help."""

import argparse
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr, ValidationError
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.common.config import settings
from app.common.db import SessionLocal
from app.common.errors import AppError
from app.maintenance.database import (
    MappingManifest,
    apply_mapping,
    bootstrap_staging_admin,
    mapping_plan,
    outbox_delivery_report,
    seed_development,
    validate_staging_database_url,
)


@contextmanager
def _session_scope(args):
    engine = None
    factory = SessionLocal
    if args.command == "bootstrap-staging-admin":
        staging_url = os.environ.get("STAGING_DATABASE_URL")
        configured_host = os.environ.get("STAGING_DATABASE_HOST")
        if not staging_url or not configured_host:
            raise ValueError(
                "Set STAGING_DATABASE_URL and STAGING_DATABASE_HOST for staging bootstrap"
            )
        try:
            parsed_url = make_url(staging_url)
        except (TypeError, ValueError) as exc:
            raise ValueError("STAGING_DATABASE_URL is invalid") from exc
        if parsed_url.drivername == "postgresql":
            parsed_url = parsed_url.set(drivername="postgresql+psycopg")
        validate_staging_database_url(parsed_url, expected_host=configured_host)
        validate_staging_database_url(parsed_url, expected_host=args.expected_host)
        engine = create_engine(
            parsed_url,
            pool_pre_ping=True,
            hide_parameters=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            connect_args={
                "options": "-c timezone=UTC",
                "connect_timeout": settings.database_connect_timeout_seconds,
            },
        )
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        with factory() as session, session.begin():
            yield session
    finally:
        if engine is not None:
            engine.dispose()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline Core database maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="Read-only legacy migration report")
    report.set_defaults(manifest=None)
    commands.add_parser("outbox-report", help="Read-only aggregate status by outbox schema version")
    plan = commands.add_parser("plan-school-mapping", help="Review explicit School mapping")
    plan.add_argument("--manifest", required=True)
    apply = commands.add_parser("apply-school-mapping", help="Apply a reviewed plan offline")
    apply.add_argument("--manifest", required=True)
    apply.add_argument("--approved-sha256", required=True)
    seed = commands.add_parser("seed-dev", help="Seed an empty dedicated dev/test database")
    seed.add_argument("--environment", choices=["development", "test"], required=True)
    seed.add_argument("--expected-database", required=True)
    seed.add_argument("--school-id", type=UUID, required=True)
    seed.add_argument("--school-name", required=True)
    staging = commands.add_parser(
        "bootstrap-staging-admin", help="One-time Admin invitation for an empty staging database"
    )
    staging.add_argument("--environment", choices=["staging"], required=True)
    staging.add_argument("--expected-database", required=True)
    staging.add_argument("--expected-host", required=True)
    staging.add_argument("--confirm-staging-bootstrap", action="store_true")
    args = parser.parse_args(argv)
    try:
        with _session_scope(args) as session:
            if args.command == "seed-dev":
                password = os.environ.get("CORE_SEED_ADMIN_PASSWORD")
                if not password:
                    raise ValueError(
                        "Set CORE_SEED_ADMIN_PASSWORD to a unique operator-provided password"
                    )
                result = seed_development(
                    session,
                    environment=args.environment,
                    expected_database=args.expected_database,
                    school_id=args.school_id,
                    school_name=args.school_name,
                    admin_password=SecretStr(password),
                )
            elif args.command == "bootstrap-staging-admin":
                if not args.confirm_staging_bootstrap:
                    raise ValueError(
                        "Pass --confirm-staging-bootstrap to run this one-time operation"
                    )
                email = os.environ.get("STAGING_BOOTSTRAP_ADMIN_EMAIL")
                school_name = os.environ.get("STAGING_BOOTSTRAP_SCHOOL_NAME")
                if not email or not school_name:
                    raise ValueError(
                        "Set STAGING_BOOTSTRAP_ADMIN_EMAIL and STAGING_BOOTSTRAP_SCHOOL_NAME"
                    )
                result = bootstrap_staging_admin(
                    session,
                    environment=args.environment,
                    expected_database=args.expected_database,
                    expected_host=args.expected_host,
                    school_name=school_name,
                    admin_email=email,
                    confirm_staging_bootstrap=True,
                )
            elif args.command == "outbox-report":
                result = outbox_delivery_report(session)
            else:
                manifest = (
                    MappingManifest.model_validate_json(
                        Path(args.manifest).read_text(encoding="utf-8-sig")
                    )
                    if args.manifest
                    else MappingManifest()
                )
                if args.command == "apply-school-mapping":
                    result = apply_mapping(session, manifest, approved_sha256=args.approved_sha256)
                else:
                    # A consistent multi-query report; never mixes snapshots.
                    session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
                    result = mapping_plan(session, manifest)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except ValidationError:
        print("Invalid maintenance manifest; check UUIDs, fields and JSON format", file=sys.stderr)
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
    except (SQLAlchemyError, OSError, AppError):
        # Do not serialize SQL parameters, paths/URLs or driver exceptions.
        print(
            "Maintenance failed; verify database head, connection and input file", file=sys.stderr
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

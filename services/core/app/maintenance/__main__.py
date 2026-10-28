"""Run from services/core: python -m app.maintenance --help."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from pydantic import SecretStr, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.common.db import SessionLocal
from app.common.errors import AppError
from app.maintenance.database import (
    MappingManifest,
    apply_mapping,
    mapping_plan,
    outbox_delivery_report,
    seed_development,
)


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
    args = parser.parse_args(argv)
    try:
        with SessionLocal() as session, session.begin():
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

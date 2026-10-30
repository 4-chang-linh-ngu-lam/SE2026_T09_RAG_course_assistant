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
    bootstrap_production_admin,
    bootstrap_staging_admin,
    correct_staging_admin_email,
    mapping_plan,
    outbox_delivery_report,
    seed_development,
    validate_production_database_url,
    validate_staging_database_url,
)


@contextmanager
def _session_scope(args):
    engine = None
    factory = SessionLocal
    if args.command in {"bootstrap-staging-admin", "correct-staging-admin-email"}:
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
    elif args.command == "bootstrap-production-admin":
        production_url = os.environ.get("PRODUCTION_DATABASE_URL")
        configured_host = os.environ.get("PRODUCTION_DATABASE_HOST")
        if not production_url or not configured_host:
            raise ValueError(
                "Set PRODUCTION_DATABASE_URL and PRODUCTION_DATABASE_HOST for Production bootstrap"
            )
        try:
            parsed_url = make_url(production_url)
        except (TypeError, ValueError) as exc:
            raise ValueError("PRODUCTION_DATABASE_URL is invalid") from exc
        if parsed_url.drivername == "postgresql":
            parsed_url = parsed_url.set(drivername="postgresql+psycopg")
        validate_production_database_url(parsed_url, expected_host=configured_host)
        validate_production_database_url(parsed_url, expected_host=args.expected_host)
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
    parser = argparse.ArgumentParser(description="Bảo trì cơ sở dữ liệu Core theo runbook")
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="Xem báo cáo tài khoản cũ, không thay đổi dữ liệu")
    report.set_defaults(manifest=None)
    commands.add_parser("outbox-report", help="Xem thống kê tổng hợp hàng đợi thông báo")
    plan = commands.add_parser("plan-school-mapping", help="Xem trước việc đối chiếu tài khoản với trường")
    plan.add_argument("--manifest", required=True)
    apply = commands.add_parser("apply-school-mapping", help="Áp dụng kế hoạch đối chiếu đã được duyệt")
    apply.add_argument("--manifest", required=True)
    apply.add_argument("--approved-sha256", required=True)
    seed = commands.add_parser("seed-dev", help="Khởi tạo dữ liệu cho cơ sở dữ liệu dev/test trống")
    seed.add_argument("--environment", choices=["development", "test"], required=True)
    seed.add_argument("--expected-database", required=True)
    seed.add_argument("--school-id", type=UUID, required=True)
    seed.add_argument("--school-name", required=True)
    staging = commands.add_parser(
        "bootstrap-staging-admin", help="Tạo lời mời Admin một lần cho cơ sở dữ liệu staging trống"
    )
    staging.add_argument("--environment", choices=["staging"], required=True)
    staging.add_argument("--expected-database", required=True)
    staging.add_argument("--expected-host", required=True)
    staging.add_argument("--confirm-staging-bootstrap", action="store_true")
    production = commands.add_parser(
        "bootstrap-production-admin",
        help="Tạo lời mời Admin một lần cho trường Production mô phỏng đã được cho phép",
    )
    production.add_argument("--environment", choices=["production"], required=True)
    production.add_argument("--expected-database", required=True)
    production.add_argument("--expected-host", required=True)
    production.add_argument("--confirm-production-bootstrap", action="store_true")
    correction = commands.add_parser(
        "correct-staging-admin-email",
        help="Sửa email nhận lời mời staging chưa được gửi",
    )
    correction.add_argument("--environment", choices=["staging"], required=True)
    correction.add_argument("--expected-database", required=True)
    correction.add_argument("--expected-host", required=True)
    correction.add_argument("--confirm-staging-admin-email-correction", action="store_true")
    args = parser.parse_args(argv)
    try:
        with _session_scope(args) as session:
            if args.command == "seed-dev":
                password = os.environ.get("CORE_SEED_ADMIN_PASSWORD")
                if not password:
                    raise ValueError(
                        "Cần đặt CORE_SEED_ADMIN_PASSWORD bằng mật khẩu riêng do người vận hành cung cấp."
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
                        "Hãy xác nhận đây là thao tác khởi tạo staging một lần trước khi tiếp tục."
                    )
                email = os.environ.get("STAGING_BOOTSTRAP_ADMIN_EMAIL")
                school_name = os.environ.get("STAGING_BOOTSTRAP_SCHOOL_NAME")
                if not email or not school_name:
                    raise ValueError(
                        "Cần cấu hình email Admin và tên trường staging trước khi tiếp tục."
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
            elif args.command == "bootstrap-production-admin":
                if not args.confirm_production_bootstrap:
                    raise ValueError(
                        "Hãy xác nhận đây là thao tác khởi tạo Production mô phỏng một lần trước khi tiếp tục."
                    )
                email = os.environ.get("PRODUCTION_BOOTSTRAP_ADMIN_EMAIL")
                school_name = os.environ.get("PRODUCTION_BOOTSTRAP_SCHOOL_NAME")
                if not email or not school_name:
                    raise ValueError(
                        "Cần cấu hình email Admin và tên trường Production mô phỏng trước khi tiếp tục."
                    )
                result = bootstrap_production_admin(
                    session,
                    environment=args.environment,
                    expected_database=args.expected_database,
                    expected_host=args.expected_host,
                    school_name=school_name,
                    admin_email=email,
                    confirm_production_bootstrap=True,
                )
            elif args.command == "correct-staging-admin-email":
                if not args.confirm_staging_admin_email_correction:
                    raise ValueError(
                        "Hãy xác nhận việc sửa email lời mời staging trước khi tiếp tục."
                    )
                expected_email = os.environ.get("STAGING_BOOTSTRAP_EXPECTED_ADMIN_EMAIL")
                email = os.environ.get("STAGING_BOOTSTRAP_ADMIN_EMAIL")
                school_name = os.environ.get("STAGING_BOOTSTRAP_SCHOOL_NAME")
                if not expected_email or not email or not school_name:
                    raise ValueError(
                        "Cần cấu hình email Admin hiện tại, email mới và tên trường staging trước khi tiếp tục."
                    )
                result = correct_staging_admin_email(
                    session,
                    environment=args.environment,
                    expected_database=args.expected_database,
                    expected_host=args.expected_host,
                    school_name=school_name,
                    expected_email=expected_email,
                    new_email=email,
                    confirm_staging_admin_email_correction=True,
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
        print(
            "Tệp đối chiếu chưa đúng định dạng. Hãy kiểm tra mã người dùng, mã trường và nội dung JSON.",
            file=sys.stderr,
        )
    except (ValueError, RuntimeError) as exc:
        detail = str(exc).lower()
        if "manifest" in detail or "mapping" in detail or "school" in detail:
            message = "Chưa thể đối chiếu tài khoản với trường. Hãy kiểm tra tệp và kế hoạch đã duyệt."
        elif "database" in detail or "migration" in detail or "host" in detail:
            message = "Cơ sở dữ liệu chưa đúng trạng thái hoặc không khớp máy chủ đã xác nhận. Hãy kiểm tra runbook."
        elif "email" in detail or "invitation" in detail or "admin" in detail:
            message = "Chưa thể hoàn tất lời mời Admin. Hãy kiểm tra cấu hình tài khoản và trạng thái lời mời."
        else:
            message = "Không thể hoàn tất thao tác bảo trì. Hãy kiểm tra đầu vào và runbook."
        print(message, file=sys.stderr)
    except (SQLAlchemyError, OSError, AppError):
        # Do not serialize SQL parameters, paths/URLs or driver exceptions.
        print(
            "Không thể hoàn tất thao tác bảo trì. Hãy kiểm tra phiên bản cơ sở dữ liệu, kết nối và tệp đầu vào.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

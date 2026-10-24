"""Disposable PostgreSQL + Document acceptance; never reads the repository .env."""

import argparse
import json
import secrets
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--core",
        action="store_true",
        help="Also test Core.Notification intake on isolated PostgreSQL",
    )
    parser.add_argument(
        "--full-core", action="store_true", help="Run the complete Core test suite as well"
    )
    args = parser.parse_args()
    if args.full_core:
        args.core = True
    root = Path(__file__).resolve().parents[1]
    directory = Path(tempfile.mkdtemp(prefix="lumi-document-tests-")).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if directory.parent != temp_root or not directory.name.startswith("lumi-document-tests-"):
        raise RuntimeError("Unexpected fixture path")
    suffix = uuid.uuid4().hex[:12]
    project = "lumi_doc_test_" + suffix
    admin_password, password = secrets.token_hex(24), secrets.token_hex(24)
    database = "lumi_doc_test_" + suffix
    admin_url = f"postgresql://fixture_admin:{admin_password}@db:5432/{database}"
    url = f"postgresql+psycopg://document_runtime:{password}@db:5432/{database}"
    image = "lumi-document-test:" + suffix
    core_image, core_test_image = (
        "lumi-core-document-test:" + suffix,
        "lumi-core-document-pytest:" + suffix,
    )
    environment = {
        "DATABASE_URL": url,
        "INTERNAL_SERVICE_SECRET": secrets.token_hex(32),
        "DOCUMENT_EVENTS_SERVICE_SECRET": secrets.token_hex(32),
        "DOCUMENT_INTERNAL_SERVICE_SECRET": secrets.token_hex(32),
        "DOCUMENT_EVENT_READER_SECRET": secrets.token_hex(32),
        "DOCUMENT_TEST_MODE": "synthetic",
        "STORAGE_ROOT": "/data/documents",
    }
    base = {
        "image": image,
        "environment": environment,
        "volumes": ["files:/data/documents"],
        "depends_on": {"db": {"condition": "service_healthy"}},
    }
    compose = {
        "services": {
            "db": {
                "image": "postgres:16-alpine",
                "environment": {
                    "POSTGRES_USER": "fixture_admin",
                    "POSTGRES_PASSWORD": admin_password,
                    "POSTGRES_DB": database,
                },
                "healthcheck": {
                    "test": ["CMD-SHELL", f"pg_isready -U fixture_admin -d {database}"],
                    "interval": "1s",
                    "timeout": "3s",
                    "retries": 30,
                },
                "volumes": ["pg:/var/lib/postgresql/data"],
            },
            "bootstrap": {
                **base,
                "environment": {**environment, "DOCUMENT_ADMIN_DATABASE_URL": admin_url},
                "command": ["python", "-m", "app.bootstrap_db"],
            },
            "migrate": {**base, "command": ["python", "-m", "alembic", "upgrade", "head"]},
            "test": {**base},
        },
        "volumes": {"pg": {}, "files": {}},
    }
    if args.core:
        compose["services"]["core-test"] = {
            "image": core_test_image,
            "environment": {
                "DATABASE_URL": admin_url.replace("postgresql:", "postgresql+psycopg:"),
                "TEST_DATABASE_URL": admin_url.replace("postgresql:", "postgresql+psycopg:"),
            },
            "command": [
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *(
                    ["tests", "-W", "error"]
                    if args.full_core
                    else [
                        "tests/notification",
                        "tests/identity/test_http_security.py",
                        "tests/identity/test_email_origin.py",
                    ]
                ),
            ],
        }
    config = directory / "compose.json"
    config.write_text(json.dumps(compose), encoding="utf-8")
    (directory / "empty.env").write_text("", encoding="utf-8")
    command = [
        "docker",
        "compose",
        "--env-file",
        str(directory / "empty.env"),
        "-f",
        str(config),
        "-p",
        project,
    ]
    log = Path(tempfile.gettempdir()) / f"lumi-document-tests-{suffix}.log"
    print("Private test log:", log, flush=True)
    result = 1
    with log.open("w", encoding="utf-8") as output:

        def run(args, timeout=600):
            completed = subprocess.run(
                args,
                cwd=root,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            output.flush()
            if completed.returncode:
                raise RuntimeError("Fixture command failed; inspect the private test log")

        try:
            run(["docker", "build", "--target", "test", "-t", image, "."])
            if args.core:
                core_root = str(root.parent / "core")
                run(["docker", "build", "-t", core_image, core_root])
                run(
                    [
                        "docker",
                        "build",
                        "-f",
                        str(root.parent / "core" / "Dockerfile.test"),
                        "--build-arg",
                        "CORE_TEST_BASE=" + core_image,
                        "-t",
                        core_test_image,
                        core_root,
                    ]
                )
            run(command + ["up", "-d", "--wait", "db"], timeout=90)
            run(command + ["run", "--rm", "--no-deps", "bootstrap"])
            run(command + ["run", "--rm", "--no-deps", "migrate"])
            run(
                command
                + ["run", "--rm", "--no-deps", "migrate", "python", "-m", "alembic", "check"]
            )
            run(command + ["run", "--rm", "--no-deps", "test"])
            if args.core:
                run(command + ["run", "--rm", "--no-deps", "core-test"])
            result = 0
        except (RuntimeError, subprocess.TimeoutExpired):
            print("Document acceptance failed; private log:", log)
        finally:
            cleanup = subprocess.run(
                command + ["down", "--volumes", "--remove-orphans"],
                cwd=root,
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=90,
                check=False,
            )
            if cleanup.returncode:
                result = 1
                print("Fixture cleanup needs attention:", project)
            # Verified direct child of the explicitly named temporary directory.
            shutil.rmtree(directory)
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-45:]))
    raise SystemExit(result)


if __name__ == "__main__":
    main()

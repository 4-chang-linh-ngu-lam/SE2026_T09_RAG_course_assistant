from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_built_package_works_for_consumer_outside_core(tmp_path: Path):
    package_root = Path(__file__).resolve().parents[1]
    wheelhouse = tmp_path / "wheels"
    target = tmp_path / "consumer-site"
    consumer_dir = tmp_path / "independent-consumer"
    wheelhouse.mkdir()
    target.mkdir()
    consumer_dir.mkdir()

    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheelhouse),
            str(package_root),
        ],
        cwd=consumer_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheelhouse.glob("lumi_service_auth-*.whl"))
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--target",
            str(target),
            str(wheel),
        ],
        cwd=consumer_dir,
        check=True,
        capture_output=True,
        text=True,
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    consumer = r"""
import importlib.util
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from lumi_service_auth import ServiceAuthConfig, issue_service_jwt, verify_service_jwt

assert "app" not in sys.modules
assert importlib.util.find_spec("lumi_service_auth").origin.startswith(sys.prefix) is False
private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
private_path = Path("consumer-private.pem")
public_path = Path("consumer-public.pem")
private_path.write_bytes(private.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
))
public_path.write_bytes(private.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
))
issuer = "https://consumer.example.invalid"
trusted = {"consumer-key-1": {
    "issuer": issuer,
    "subject": "document",
    "public_key_file": str(public_path.resolve()),
    "audiences": ["core"],
    "scopes": ["core:check_access"],
}}
config = ServiceAuthConfig(
    service_identity="document",
    issuer=issuer,
    key_id="consumer-key-1",
    private_key_file=str(private_path.resolve()),
    trusted_keys_json=json.dumps(trusted),
    expected_audience="core",
    issued_audiences=("core",),
    issued_scopes=("core:check_access",),
)
token = issue_service_jwt(config, audience="core", scopes={"core:check_access"})
principal = verify_service_jwt(
    token, config, required_scopes={"core:check_access"}
)
assert principal.service_id == "document"
assert principal.scopes == {"core:check_access"}
print("external-consumer-ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", consumer],
        cwd=consumer_dir,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "external-consumer-ok"

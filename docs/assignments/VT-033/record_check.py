"""Record reproducible local checks without storing credentials.

Run from services/core: python ../../docs/assignments/VT-033/record_check.py LABEL -- COMMAND ...
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit


def main():
    label, *command = sys.argv[1:]
    if command and command[0] == "--":
        command.pop(0)
    root = Path(__file__).resolve().parents[3]
    core = root / "services/core"
    if Path.cwd().resolve() != core or not command:
        raise SystemExit("Run from services/core and provide a command")
    evidence = Path(__file__).with_name("evidence")
    evidence.mkdir(exist_ok=True)
    source_hash = hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted((core / "app").rglob("*.py")))
    ).hexdigest()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    started = datetime.now(UTC).isoformat()
    result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
    output = result.stdout + result.stderr
    for name in ("DATABASE_URL", "TEST_DATABASE_URL", "SECRET_KEY", "INTERNAL_SERVICE_SECRET"):
        secret = os.environ.get(name)
        if secret:
            output = output.replace(secret, "<redacted>")
            if "DATABASE_URL" in name:
                password = urlsplit(secret).password
                if password:
                    output = output.replace(password, "<redacted>")
    metadata = {
        "started_at_utc": started,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "sha": sha,
        "branch": subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(),
        "cwd": str(core),
        "command": command,
        "exit_code": result.returncode,
        "application_sha256": source_hash,
        "test_database_configured": bool(os.environ.get("TEST_DATABASE_URL")),
        "log": f"{label}.log",
    }
    (evidence / f"{label}.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    output = re.sub(
        r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted-test-jwt>", output
    )
    output = "\n".join(line.rstrip() for line in output.splitlines()) + "\n"
    (evidence / f"{label}.log").write_text(output, encoding="utf-8")
    print(output[-6000:])
    print(json.dumps(metadata, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())

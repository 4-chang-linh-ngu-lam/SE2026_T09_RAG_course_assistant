"""Run one authorization mutation in a detached, local-only worktree.

Run from services/core after committing the correct implementation, with the
dedicated TEST_DATABASE_URL set. No mutated source is committed or pushed.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[3]
    core = root / "services/core"
    worktree = core / ".venv/vt033-mutation"
    evidence = Path(__file__).with_name("evidence")
    relative = Path("services/core/app/modules/notification/repository.py")
    if worktree.exists():
        raise SystemExit("Refusing to overwrite an existing mutation worktree")
    if not os.environ.get("TEST_DATABASE_URL"):
        raise SystemExit("Dedicated TEST_DATABASE_URL is required")
    if subprocess.check_output(["git", "diff", "HEAD", "--", "services/core/app"], cwd=root):
        raise SystemExit("Commit the correct production source before mutation")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    original_main = (root / relative).read_bytes()
    subprocess.run(["git", "worktree", "add", "--detach", str(worktree), sha], cwd=root, check=True)
    source = worktree / relative
    original = source.read_bytes()
    assert original == original_main
    guard = b".where(Notification.id == notification_id, Notification.recipient_id == user_id)"
    replacement = b".where(Notification.id == notification_id)"
    assert original.count(guard) == 1
    command = [
        sys.executable, "-m", "pytest",
        "tests/notification/test_vt033_postgres.py::test_cross_recipient_mark_read_preserves_business_state",
        "-q", "-W", "error", "-p", "no:cacheprovider", "--tb=short",
    ]
    results = {}

    def run(label):
        start = datetime.now(UTC).isoformat()
        result = subprocess.run(
            command, cwd=worktree / "services/core", capture_output=True,
            encoding="utf-8", errors="replace", check=False,
        )
        output = result.stdout + result.stderr
        for key in ("DATABASE_URL", "TEST_DATABASE_URL", "SECRET_KEY"):
            value = os.environ.get(key)
            if value:
                output = output.replace(value, "<redacted>")
        output = re.sub(
            r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted-test-jwt>", output
        )
        output = "\n".join(line.rstrip() for line in output.splitlines()) + "\n"
        (evidence / f"{label}.log").write_text(output, encoding="utf-8")
        results[label] = {
            "started_at_utc": start, "finished_at_utc": datetime.now(UTC).isoformat(),
            "command": command, "sha": sha, "cwd": str(worktree / "services/core"),
            "exit_code": result.returncode,
        }
        print(f"{label}: exit {result.returncode}", flush=True)
        return result.returncode, output

    try:
        code, output = run("03-before")
        assert code == 0 and "3 passed" in output
        source.write_bytes(original.replace(guard, replacement))
        diff = subprocess.check_output(
            ["git", "diff", "--", str(relative)], cwd=worktree, text=True
        )
        (evidence / "03-mutation.diff").write_text(diff, encoding="utf-8")
        code, output = run("03-killed")
        assert code == 1 and "3 failed" in output
        assert "cross-recipient mark-read changed persisted read_at" in output
        results["verdict"] = "KILLED by persisted business state assertion, all 3 defaults"
    finally:
        # Always restore exact bytes, including on a failed test or a survived mutation.
        source.write_bytes(original)
        restored = hashlib.sha256(source.read_bytes()).hexdigest()
        results["original_source_sha256"] = hashlib.sha256(original).hexdigest()
        results["restored_source_sha256"] = restored
        results["main_source_unchanged"] = (root / relative).read_bytes() == original_main
        code, output = run("04-restored")
        results["restored_passed"] = code == 0 and "3 passed" in output
        results["worktree_diff_after_restore"] = subprocess.check_output(
            ["git", "diff", "--", str(relative)], cwd=worktree, text=True
        )
        (evidence / "03-mutation.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        status = subprocess.check_output(["git", "status", "--porcelain"], cwd=worktree, text=True)
        if not status:
            subprocess.run(["git", "worktree", "remove", str(worktree)], cwd=root, check=True)
        else:
            print("Restored worktree retained for inspection; no files deleted", flush=True)
    assert restored == hashlib.sha256(original).hexdigest()
    assert results["restored_passed"] and results["main_source_unchanged"]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

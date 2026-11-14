"""Run the required mutant in a detached worktree; submission branch stays clean."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[4]
    evidence = root / "docs/assignments/VT-034/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    target = "services/core/app/modules/notification/worker.py"
    original_bytes = (root / target).read_bytes()
    with tempfile.TemporaryDirectory(prefix="vt034_mutant_") as temp:
        worktree = Path(temp) / "tree"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), "HEAD"], cwd=root, check=True
        )
        try:
            path = worktree / target
            text = path.read_text()
            assert text.count("batch_size > 1000") == 1
            path.write_text(text.replace("batch_size > 1000", "batch_size >= 1000"))
            patch = subprocess.check_output(["git", "diff", "--", target], cwd=worktree, text=True)
            (evidence / "mutation.patch").write_text(patch)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Codex",
                    "-c",
                    "user.email=codex@openai.com",
                    "commit",
                    "-am",
                    "test(vt034): TEMPORARY boundary mutant > to >=",
                ],
                cwd=worktree,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=worktree, text=True
            ).strip()
            command = [
                sys.executable,
                "-m",
                "pytest",
                "tests/vt034/test_contract.py::test_tc06_batch_accepts_inclusive_boundary",
                "-q",
                "--tb=short",
            ]
            result = subprocess.run(
                command,
                check=False,
                cwd=worktree / "services/core",
                env={**os.environ, "PYTHONPATH": "."},
                text=True,
                capture_output=True,
            )
            output = result.stdout + result.stderr
            (evidence / "mutation.log").write_text(output)
            killed = (
                result.returncode == 1
                and "1 failed, 1 passed" in output
                and "test_tc06_batch_accepts_inclusive_boundary[1000]" in output
                and "ValueError" in output
            )
            summary = {
                "mutant_commit": sha,
                "operator": "> -> >=",
                "boundary": 1000,
                "exit_code": result.returncode,
                "killed": killed,
                "expected_failure": "test_tc06_batch_accepts_inclusive_boundary[1000]",
                "temporary_detached_commit": True,
                "mutation_in_submission": False,
            }
            (evidence / "mutation.json").write_text(json.dumps(summary, indent=2))
            print(json.dumps(summary, indent=2))
            assert killed, (
                "Mutant survived or failed for an unexpected reason; inspect mutation.log"
            )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)], cwd=root, check=True
            )
    assert (root / target).read_bytes() == original_bytes


if __name__ == "__main__":
    main()

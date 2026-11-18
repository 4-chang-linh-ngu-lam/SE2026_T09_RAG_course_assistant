"""One heavy-model lease by default; advisory OS locks release after crashes."""

import math
import re
import subprocess
import time
from pathlib import Path


def recommended_concurrency(
    available_ram, p95_job_ram, cpu_cores, *, safety_margin=0.25
):
    if (
        available_ram <= 0
        or p95_job_ram <= 0
        or cpu_cores < 1
        or not 0 < safety_margin < 1
    ):
        raise ValueError("measured positive resource inputs required")
    return max(
        0, min(cpu_cores, math.floor(available_ram * (1 - safety_margin) / p95_job_ram))
    )


class FileLease:
    def __init__(self, path, deadline):
        self.path = Path(path)
        self.deadline = deadline
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.handle.tell() == 0:
            self.handle.write(b"0")
        self.handle.flush()
        self.handle.seek(0)
        while True:
            try:
                if __import__("os").name == "nt":
                    import msvcrt

                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.monotonic() >= self.deadline:
                    self.handle.close()
                    raise TimeoutError("heavy-model resource lease deadline")
                time.sleep(0.1)

    def __exit__(self, *args):
        self.handle.close()


HeavyModelLease = FileLease


def cleanup_attempt_containers(token):
    """Remove only this attempt's labeled containers; tolerate absent daemon."""
    if not isinstance(token, str) or not re.fullmatch("[0-9a-f]{32}", token):
        return False
    try:
        found = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "label=deepdoc.job=" + token],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if found.returncode:
            return False
        identifiers = [
            s for s in found.stdout.split() if re.fullmatch("[0-9a-f]{12,64}", s)
        ]
        if not identifiers:
            return True
        return (
            subprocess.run(
                ["docker", "rm", "-f", *identifiers],
                capture_output=True,
                timeout=30,
                check=False,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False

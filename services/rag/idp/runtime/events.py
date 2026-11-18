"""Content-free structured events; metrics aggregate recorded observations only."""

import json
import os
import time
from pathlib import Path


class Events:
    def __init__(self, path, job_id, source_sha256):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.job_id = job_id
        self.source_sha256 = source_sha256

    def __call__(self, **fields):
        allowed = {
            "stage",
            "page",
            "cache",
            "duration",
            "error_code",
            "retryable",
            "backend",
            "review",
            "rss_bytes",
            "cpu_seconds",
            "status",
            "cache_stats",
        }
        if set(fields) - allowed:
            raise ValueError("unknown event fields")
        value = {
            "schema": "deepdoc-event:1",
            "job_id": self.job_id,
            "source_sha256": self.source_sha256,
            "time": time.time(),
            **fields,
        }
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(
                fd,
                (
                    json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n"
                ).encode(),
            )
        finally:
            os.close(fd)


def aggregate(paths):
    rows = [
        json.loads(line)
        for path in paths
        for line in Path(path).read_text().splitlines()
        if line
    ]
    durations = sorted(
        r["duration"] for r in rows if "duration" in r and r["stage"] == "job"
    )

    def percentile(p):
        if not durations:
            return None
        import math

        return durations[max(0, math.ceil(p * len(durations)) - 1)]

    counts = {}
    for row in rows:
        code = row.get("error_code")
        if code:
            counts[code] = counts.get(code, 0) + 1
    hits = sum(r.get("cache") == "hit" for r in rows)
    miss = sum(r.get("cache") == "miss" for r in rows)
    stages = {}
    for row in rows:
        if "duration" in row:
            stages.setdefault(row["stage"], []).append(row["duration"])
    by_stage = {}
    import math

    for stage, values in stages.items():
        values.sort()
        by_stage[stage] = {
            "count": len(values),
            "p50_seconds": values[max(0, math.ceil(len(values) * 0.5) - 1)],
            "p95_seconds": values[max(0, math.ceil(len(values) * 0.95) - 1)],
        }
    return {
        "events": len(rows),
        "p50_seconds": percentile(0.5),
        "p95_seconds": percentile(0.95),
        "cache_hit_rate": hits / (hits + miss) if hits + miss else None,
        "error_counts": counts,
        "gpu_peak_bytes": None,
        "gpu_status": "NOT MEASURED",
        "peak_self_rss_bytes": max((r.get("rss_bytes") or 0 for r in rows), default=0),
        "by_stage": by_stage,
    }

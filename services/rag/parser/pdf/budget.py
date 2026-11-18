"""Atomic in-process run/lineage reservations; failures still consume work."""

from collections import Counter
from threading import Lock

from ..source_observation import DeepDocWorkLimits


class PdfWorkBudget:
    def __init__(self, limits: DeepDocWorkLimits):
        self.limits = limits
        self._lock = Lock()
        self._resources = Counter()
        self._lineages = Counter()
        self._total = 0

    def reserve(self, lineage_id: str, operation: str, resource: str):
        if operation not in {"VERIFY", "REROUTE", "DESCRIBE"} or resource not in {"CPU", "GPU", "REMOTE"}:
            raise ValueError("unsupported work budget operation/resource")
        with self._lock:
            key = (lineage_id, operation)
            if self._total >= self.limits.max_work:
                return None, "RUN_BUDGET_EXHAUSTED"
            if self._lineages[key] >= getattr(self.limits, operation.lower() + "_per_lineage"):
                return None, "LINEAGE_BUDGET_EXHAUSTED"
            if self._resources[resource] >= getattr(self.limits, resource.lower()):
                return None, "RESOURCE_BUDGET_EXHAUSTED"
            self._total += 1
            self._resources[resource] += 1
            self._lineages[key] += 1
            return self._lineages[key], None

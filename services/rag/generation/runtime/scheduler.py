"""Priority admission to the single llama.cpp slot (architecture §6.1).

Work is admitted one model call at a time. A background quiz job therefore
yields between calls: an interactive tutor turn waiting at P0 is admitted before
the next P2 call, but no call is ever cut in half.
"""
from __future__ import annotations

import heapq
import itertools
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

P0_INTERACTIVE = 0   # tutor turn
P1_TEACHER = 1       # teacher regenerates one item while reviewing
P2_BACKGROUND = 2    # quiz jobs, fact extraction for new documents
PRIORITIES = (P0_INTERACTIVE, P1_TEACHER, P2_BACKGROUND)


class SchedulerBusy(RuntimeError):
    """The slot was not available within the caller's wait budget."""

    code = "generator_busy"


@dataclass(frozen=True)
class Lease:
    priority: int
    waited_seconds: float


class SlotScheduler:
    def __init__(self, slots: int = 1, *, clock=time.monotonic):
        if type(slots) is not int or slots < 1:
            raise ValueError("slots must be a positive integer")
        self._slots = slots
        self._busy = 0
        self._queue: list[tuple[int, int]] = []
        self._cond = threading.Condition()
        self._seq = itertools.count()
        self._clock = clock
        self._waits: dict[int, list[float]] = {p: [] for p in PRIORITIES}

    @contextmanager
    def slot(self, priority: int = P0_INTERACTIVE, timeout: float | None = None):
        if priority not in PRIORITIES:
            raise ValueError("invalid priority")
        ticket = (priority, next(self._seq))
        started = self._clock()
        deadline = None if timeout is None else started + timeout
        with self._cond:
            heapq.heappush(self._queue, ticket)
            while not (self._busy < self._slots and self._queue[0] == ticket):
                remaining = None if deadline is None else deadline - self._clock()
                if remaining is not None and remaining <= 0:
                    self._queue.remove(ticket)
                    heapq.heapify(self._queue)
                    self._cond.notify_all()
                    raise SchedulerBusy("generator_busy")
                self._cond.wait(remaining)
            heapq.heappop(self._queue)
            self._busy += 1
            waited = self._clock() - started
            samples = self._waits[priority]
            samples.append(waited)
            del samples[:-1000]
            self._cond.notify_all()
        try:
            yield Lease(priority, waited)
        finally:
            with self._cond:
                self._busy -= 1
                self._cond.notify_all()

    def snapshot(self) -> dict:
        """Queue depth per priority and p95 admission wait (the P0 SLI)."""
        with self._cond:
            depth = {p: sum(1 for q, _ in self._queue if q == p) for p in PRIORITIES}
            p95 = {}
            for p, samples in self._waits.items():
                ordered = sorted(samples)
                p95[p] = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))] if ordered else None
            return {"busy": self._busy, "slots": self._slots, "waiting": depth, "wait_p95_seconds": p95}

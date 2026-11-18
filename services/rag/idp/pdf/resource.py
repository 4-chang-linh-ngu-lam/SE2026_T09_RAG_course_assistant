"""Shared synchronous job budget; failed/reserved calls still consume resources."""

from dataclasses import dataclass, field
from threading import Lock
from time import monotonic


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class ResourceLedger:
    deadline: float
    max_calls: int = 20
    max_calls_per_page: int = 10
    _page_calls: dict = field(default_factory=dict, init=False, repr=False)
    max_pixels: int = 40_000_000
    max_regions: int = 1000
    calls: int = field(default=0, init=False)
    pixels: int = field(default=0, init=False)
    regions: int = field(default=0, init=False)
    resource_limits: dict = field(
        default_factory=lambda: {"CPU": 20, "GPU": 0, "REMOTE": 0}
    )
    _resource_calls: dict = field(default_factory=dict, init=False, repr=False)
    _items: dict = field(default_factory=dict, init=False, repr=False)
    _renders: set = field(default_factory=set, init=False, repr=False)
    _lock: object = field(default_factory=Lock, init=False, repr=False)

    def __post_init__(self):
        import math

        if not math.isfinite(self.deadline):
            raise ValueError("finite deadline required")
        for value in (
            self.max_calls,
            self.max_calls_per_page,
            self.max_pixels,
            self.max_regions,
            *self.resource_limits.values(),
        ):
            if type(value) is not int or value < 0:
                raise ValueError("nonnegative integer resource limits required")
        self.resource_limits = dict(self.resource_limits)

    def reserve(self, key, *, pixels=0, regions=0, resource="CPU", page=None):
        with self._lock:
            if page is not None and (type(page) is not int or page < 1):
                raise ValueError("invalid budget page")
            if (
                page is not None
                and self._page_calls.get(page, 0) >= self.max_calls_per_page
            ):
                raise BudgetExceeded("page budget exhausted")
            if resource not in self.resource_limits:
                raise BudgetExceeded("unsupported resource")
            if self._resource_calls.get(resource, 0) >= self.resource_limits[resource]:
                raise BudgetExceeded("resource budget exhausted")
            if key in self._items:
                raise BudgetExceeded("duplicate work identity")
            if min(pixels, regions) < 0:
                raise ValueError("negative resource reservation")
            if monotonic() >= self.deadline:
                raise BudgetExceeded("deadline exceeded")
            if (
                self.calls + 1 > self.max_calls
                or self.pixels + pixels > self.max_pixels
                or self.regions + regions > self.max_regions
            ):
                raise BudgetExceeded("shared budget exhausted")
            self._resource_calls[resource] = self._resource_calls.get(resource, 0) + 1
            if page is not None:
                self._page_calls[page] = self._page_calls.get(page, 0) + 1
            self.calls += 1
            self.pixels += pixels
            self.regions += regions
            self._items[key] = "reserved"

    def settle(self, key, success):
        with self._lock:
            if self._items.get(key) != "reserved":
                raise BudgetExceeded("work is not reserved")
            self._items[key] = "success" if success else "failed"

    @property
    def resource_calls(self):
        with self._lock:
            return dict(self._resource_calls)

    def reserve_render(self, key, pixels):
        """Charge allocated render pixels before rendering, without an OCR call.

        This opt-in operation lets a service share the same pixel budget across
        blank confirmation, page rendering and cropped acquisition. Failures keep
        their cost, just like OCR reservations.
        """
        with self._lock:
            if type(pixels) is not int or pixels <= 0:
                raise ValueError("positive integer render pixels required")
            if key in self._renders:
                raise BudgetExceeded("duplicate render reservation")
            if monotonic() >= self.deadline or self.pixels + pixels > self.max_pixels:
                raise BudgetExceeded("render budget/deadline exhausted")
            self._renders.add(key)
            self.pixels += pixels

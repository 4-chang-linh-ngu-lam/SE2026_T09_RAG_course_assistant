"""PDF display points (top left) to image pixels; A @ B applies B first."""

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Affine:
    a: float = 1
    b: float = 0
    c: float = 0
    d: float = 1
    e: float = 0
    f: float = 0

    def __post_init__(self):
        if (
            not all(
                math.isfinite(v)
                for v in (self.a, self.b, self.c, self.d, self.e, self.f)
            )
            or abs(self.a * self.d - self.b * self.c) < 1e-12
        ):
            raise ValueError("affine must be finite and invertible")

    def apply(self, x: float, y: float) -> tuple[float, float]:
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("nonfinite point")
        return self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f

    def inverse(self):
        det = self.a * self.d - self.b * self.c
        return Affine(
            self.d / det,
            -self.b / det,
            -self.c / det,
            self.a / det,
            (self.c * self.f - self.d * self.e) / det,
            (self.b * self.e - self.a * self.f) / det,
        )

    def __matmul__(self, other):
        return Affine(
            self.a * other.a + self.c * other.b,
            self.b * other.a + self.d * other.b,
            self.a * other.c + self.c * other.d,
            self.b * other.c + self.d * other.d,
            self.a * other.e + self.c * other.f + self.e,
            self.b * other.e + self.d * other.f + self.f,
        )


def corners(box):
    x0, y0, x1, y1 = box
    if not all(math.isfinite(v) for v in box) or x1 <= x0 or y1 <= y0:
        raise ValueError("invalid box")
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


def bounds(points):
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )

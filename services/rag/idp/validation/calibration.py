"""Confidence semantics, empirical calibration metrics (ECE/Brier), and calibrators."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

CONFIDENCE_SCHEMA_VERSION = "idp-confidence-1"
UNCALIBRATED_NOTE = (
    "Heuristic OCR/model confidence score; not a calibrated probability of ground-truth accuracy."
)
CALIBRATED_NOTE = "Calibrated accuracy probability backed by empirical validation."

SCORE_KIND_BY_SOURCE: dict[str, str] = {
    "pymupdf": "native_deterministic",
    "pandoc": "native_deterministic",
    "text": "native_deterministic",
    "markdown": "native_deterministic",
    "html": "native_deterministic",
    "csv": "native_deterministic",
    "openpyxl": "native_deterministic",
    "python-pptx": "native_deterministic",
    "email": "native_deterministic",
    "pdf_text": "native_deterministic",
    "tesseract": "tesseract_word_heuristic",
    "tesseract_ocr": "tesseract_word_heuristic",
    "tesseract_fast": "tesseract_word_heuristic",
    "tesseract_fallback": "tesseract_word_heuristic",
    "paddleocr_vl_gguf": "vlm_min_token_prob",
    "paddleocr_vl_primary": "vlm_min_token_prob",
    "opencv_grid_tesseract": "table_grid_ocr_heuristic",
    "structured_region": "unscored_region",
    "ocr_region_recovery": "unscored_region",
    "layout_figure": "layout_detector_score",
}

NATIVE_SCORE_SOURCES = frozenset(
    k for k, v in SCORE_KIND_BY_SOURCE.items() if v == "native_deterministic"
)


def _valid_prob(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    val = float(value)
    if not math.isfinite(val) or not 0.0 <= val <= 1.0:
        return None
    return val


def infer_score_kind(source: str | None, *, raw_score: float | None = None) -> str:
    src = (source or "").strip()
    if src in SCORE_KIND_BY_SOURCE:
        return SCORE_KIND_BY_SOURCE[src]
    if raw_score is None:
        return "none"
    return "uncalibrated_heuristic"


def build_confidence_meta(
    raw_score: float | None,
    *,
    source: str | None = None,
    score_kind: str | None = None,
    verification_tier: str | None = None,
    calibrator: Any | None = None,
) -> dict[str, Any]:
    """Attach explicit calibration provenance so heuristic confidence is never mistaken for accuracy."""
    score = _valid_prob(raw_score)
    kind = score_kind or infer_score_kind(source, raw_score=score)
    calibrator_verified = bool(calibrator is not None and getattr(calibrator, "verified", False))
    calibrated_prob: float | None = None
    calibrator_id: str | None = None

    if score is not None and calibrator_verified:
        predicted = _valid_prob(calibrator.predict(score))
        if predicted is not None:
            calibrated_prob = round(predicted, 4)
            calibrator_id = getattr(calibrator, "calibrator_id", None)

    is_calibrated = calibrated_prob is not None and calibrator_verified
    meta: dict[str, Any] = {
        "version": CONFIDENCE_SCHEMA_VERSION,
        "raw_score": round(score, 4) if score is not None else None,
        "score_kind": kind,
        "is_calibrated": is_calibrated,
        "calibrated_probability": calibrated_prob,
        "calibrator_id": calibrator_id,
        "note": CALIBRATED_NOTE if is_calibrated else UNCALIBRATED_NOTE,
    }
    if verification_tier is not None:
        meta["verification_tier"] = verification_tier
    return meta


def _validate_pairs(
    scores: Sequence[float],
    labels: Sequence[bool | int | float],
) -> tuple[list[float], list[float]]:
    if not scores or len(scores) != len(labels):
        raise ValueError("scores and labels must be non-empty sequences of equal length")
    clean_scores: list[float] = []
    clean_labels: list[float] = []
    for s, y in zip(scores, labels):
        val = _valid_prob(s)
        if val is None:
            raise ValueError(f"invalid probability score: {s!r}")
        if isinstance(y, bool):
            lbl = 1.0 if y else 0.0
        elif isinstance(y, (int, float)) and math.isfinite(float(y)) and y in (0, 1):
            lbl = float(y)
        else:
            raise ValueError(f"labels must be binary (bool or 0/1), got {y!r}")
        clean_scores.append(val)
        clean_labels.append(lbl)
    return clean_scores, clean_labels


def expected_calibration_error(
    scores: Sequence[float],
    labels: Sequence[bool | int],
    *,
    n_bins: int = 10,
) -> dict[str, Any]:
    """Compute ECE, MCE, Brier score, reliability bins, and selective accuracy curve."""
    if type(n_bins) is not int or not 1 <= n_bins <= 100:
        raise ValueError("n_bins must be an integer in [1, 100]")
    xs, ys = _validate_pairs(scores, labels)
    n = len(xs)

    buckets: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for x, y in zip(xs, ys):
        idx = min(n_bins - 1, int(x * n_bins))
        buckets[idx].append((x, y))

    bins: list[dict[str, Any]] = []
    ece = 0.0
    mce = 0.0
    for i, items in enumerate(buckets):
        lower = round(i / n_bins, 4)
        upper = round((i + 1) / n_bins, 4)
        if not items:
            bins.append({
                "bin_index": i,
                "lower": lower,
                "upper": upper,
                "count": 0,
                "mean_confidence": None,
                "empirical_accuracy": None,
                "abs_gap": None,
            })
            continue
        mean_conf = sum(x for x, _ in items) / len(items)
        emp_acc = sum(y for _, y in items) / len(items)
        gap = abs(mean_conf - emp_acc)
        ece += (len(items) / n) * gap
        mce = max(mce, gap)
        bins.append({
            "bin_index": i,
            "lower": lower,
            "upper": upper,
            "count": len(items),
            "mean_confidence": round(mean_conf, 6),
            "empirical_accuracy": round(emp_acc, 6),
            "abs_gap": round(gap, 6),
        })

    brier = sum((x - y) ** 2 for x, y in zip(xs, ys)) / n
    mean_conf_all = sum(xs) / n
    emp_acc_all = sum(ys) / n

    selective_curve = []
    for threshold in (0.5, 0.6, 0.7, 0.8, 0.9):
        kept = [y for x, y in zip(xs, ys) if x >= threshold]
        selective_curve.append({
            "threshold": threshold,
            "count": len(kept),
            "coverage": round(len(kept) / n, 6),
            "empirical_accuracy": round(sum(kept) / len(kept), 6) if kept else None,
        })

    return {
        "sample_count": n,
        "n_bins": n_bins,
        "ece": round(ece, 6),
        "mce": round(mce, 6),
        "brier_score": round(brier, 6),
        "mean_confidence": round(mean_conf_all, 6),
        "empirical_accuracy": round(emp_acc_all, 6),
        "overconfidence_gap": round(mean_conf_all - emp_acc_all, 6),
        "bins": bins,
        "selective_curve": selective_curve,
    }


def _logit(p: float) -> float:
    clamped = min(1.0 - 1e-6, max(1e-6, float(p)))
    return math.log(clamped / (1.0 - clamped))


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = math.exp(-min(z, 60.0))
        return 1.0 / (1.0 + ez)
    ez = math.exp(max(z, -60.0))
    return ez / (1.0 + ez)


class PlattCalibrator:
    """Logistic (Platt) probability calibrator fitted on logit-transformed heuristic scores."""

    method = "platt"

    def __init__(
        self,
        a: float = 1.0,
        b: float = 0.0,
        *,
        calibrator_id: str = "platt-1",
        verified: bool = False,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        self.a = float(a)
        self.b = float(b)
        self.calibrator_id = calibrator_id
        self.verified = bool(verified)
        self.metrics = dict(metrics or {})

    def predict(self, score: float) -> float:
        val = _valid_prob(score)
        if val is None:
            raise ValueError(f"invalid score: {score!r}")
        return round(_sigmoid(self.a * _logit(val) + self.b), 6)

    @classmethod
    def fit(
        cls,
        scores: Sequence[float],
        labels: Sequence[bool | int],
        *,
        calibrator_id: str = "platt-1",
        min_samples: int = 30,
        max_verified_ece: float = 0.05,
        n_bins: int = 10,
        l2: float = 1e-2,
        max_iter: int = 200,
    ) -> "PlattCalibrator":
        xs_raw, ys = _validate_pairs(scores, labels)
        xs = [_logit(x) for x in xs_raw]
        n = float(len(xs))
        a, b = 1.0, 0.0

        def loss_fn(ca: float, cb: float) -> float:
            total = 0.0
            for x, y in zip(xs, ys):
                p = min(1.0 - 1e-12, max(1e-12, _sigmoid(ca * x + cb)))
                total -= y * math.log(p) + (1.0 - y) * math.log(1.0 - p)
            return total / n + 0.5 * l2 * (ca * ca + cb * cb)

        for _ in range(max_iter):
            g_a = l2 * a
            g_b = l2 * b
            h_aa = l2
            h_ab = 0.0
            h_bb = l2
            for x, y in zip(xs, ys):
                p = _sigmoid(a * x + b)
                diff = p - y
                w = max(1e-8, p * (1.0 - p))
                g_a += (diff * x) / n
                g_b += diff / n
                h_aa += (w * x * x) / n
                h_ab += (w * x) / n
                h_bb += w / n
            det = h_aa * h_bb - h_ab * h_ab
            if abs(det) < 1e-12:
                break
            step_a = -(h_bb * g_a - h_ab * g_b) / det
            step_b = -(-h_ab * g_a + h_aa * g_b) / det
            if abs(step_a) < 1e-7 and abs(step_b) < 1e-7:
                break
            cur_loss = loss_fn(a, b)
            alpha = 1.0
            while alpha >= 1e-4:
                na, nb = a + alpha * step_a, b + alpha * step_b
                if loss_fn(na, nb) <= cur_loss + 1e-12:
                    a, b = na, nb
                    break
                alpha *= 0.5

        inst = cls(a=a, b=b, calibrator_id=calibrator_id, verified=False)
        pre_metrics = expected_calibration_error(xs_raw, ys, n_bins=n_bins)
        calibrated_scores = [inst.predict(s) for s in xs_raw]
        post_metrics = expected_calibration_error(calibrated_scores, ys, n_bins=n_bins)
        verified = len(xs_raw) >= min_samples and post_metrics["ece"] <= max_verified_ece
        return cls(
            a=a,
            b=b,
            calibrator_id=calibrator_id,
            verified=verified,
            metrics={"pre_fit": pre_metrics, "post_fit": post_metrics},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "calibrator_id": self.calibrator_id,
            "a": round(self.a, 8),
            "b": round(self.b, 8),
            "verified": self.verified,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlattCalibrator":
        return cls(
            a=float(data["a"]),
            b=float(data["b"]),
            calibrator_id=str(data.get("calibrator_id") or "platt-1"),
            verified=bool(data.get("verified", False)),
            metrics=data.get("metrics") or {},
        )


class IsotonicCalibrator:
    """Monotonic isotonic regression (PAVA) probability calibrator."""

    method = "isotonic"

    def __init__(
        self,
        thresholds: Sequence[float] = (0.0, 1.0),
        values: Sequence[float] = (0.0, 1.0),
        *,
        calibrator_id: str = "isotonic-1",
        verified: bool = False,
        metrics: dict[str, Any] | None = None,
    ) -> None:
        if len(thresholds) != len(values) or not thresholds:
            raise ValueError("thresholds and values must be non-empty and equal length")
        self.thresholds = [float(t) for t in thresholds]
        self.values = [float(v) for v in values]
        self.calibrator_id = calibrator_id
        self.verified = bool(verified)
        self.metrics = dict(metrics or {})

    def predict(self, score: float) -> float:
        val = _valid_prob(score)
        if val is None:
            raise ValueError(f"invalid score: {score!r}")
        if val <= self.thresholds[0]:
            return round(self.values[0], 6)
        if val >= self.thresholds[-1]:
            return round(self.values[-1], 6)
        for i in range(len(self.thresholds) - 1):
            lo, hi = self.thresholds[i], self.thresholds[i + 1]
            if lo <= val <= hi:
                if hi == lo:
                    return round(self.values[i + 1], 6)
                frac = (val - lo) / (hi - lo)
                interp = self.values[i] + frac * (self.values[i + 1] - self.values[i])
                return round(min(1.0, max(0.0, interp)), 6)
        return round(self.values[-1], 6)

    @classmethod
    def fit(
        cls,
        scores: Sequence[float],
        labels: Sequence[bool | int],
        *,
        calibrator_id: str = "isotonic-1",
        min_samples: int = 30,
        max_verified_ece: float = 0.05,
        n_bins: int = 10,
    ) -> "IsotonicCalibrator":
        xs, ys = _validate_pairs(scores, labels)
        grouped: dict[float, list[float]] = {}
        for x, y in zip(xs, ys):
            grouped.setdefault(x, []).append(y)

        # Pool Adjacent Violators Algorithm (PAVA) blocks: [sum_y, count, min_x, max_x]
        blocks: list[list[float]] = []
        for x in sorted(grouped):
            vals = grouped[x]
            blocks.append([sum(vals), float(len(vals)), x, x])
            while len(blocks) >= 2:
                prev_mean = blocks[-2][0] / blocks[-2][1]
                curr_mean = blocks[-1][0] / blocks[-1][1]
                if prev_mean <= curr_mean:
                    break
                last = blocks.pop()
                blocks[-1][0] += last[0]
                blocks[-1][1] += last[1]
                blocks[-1][3] = last[3]

        thresholds = [0.5 * (b[2] + b[3]) for b in blocks]
        values = [min(1.0, max(0.0, b[0] / b[1])) for b in blocks]
        inst = cls(thresholds=thresholds, values=values, calibrator_id=calibrator_id, verified=False)
        pre_metrics = expected_calibration_error(xs, ys, n_bins=n_bins)
        calibrated_scores = [inst.predict(s) for s in xs]
        post_metrics = expected_calibration_error(calibrated_scores, ys, n_bins=n_bins)
        verified = len(xs) >= min_samples and post_metrics["ece"] <= max_verified_ece
        return cls(
            thresholds=thresholds,
            values=values,
            calibrator_id=calibrator_id,
            verified=verified,
            metrics={"pre_fit": pre_metrics, "post_fit": post_metrics},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "calibrator_id": self.calibrator_id,
            "thresholds": [round(t, 6) for t in self.thresholds],
            "values": [round(v, 6) for v in self.values],
            "verified": self.verified,
            "metrics": self.metrics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IsotonicCalibrator":
        return cls(
            thresholds=list(data["thresholds"]),
            values=list(data["values"]),
            calibrator_id=str(data.get("calibrator_id") or "isotonic-1"),
            verified=bool(data.get("verified", False)),
            metrics=data.get("metrics") or {},
        )


def calibrator_from_dict(data: dict[str, Any]) -> PlattCalibrator | IsotonicCalibrator:
    method = str(data.get("method") or "").strip().lower()
    if method == "platt":
        return PlattCalibrator.from_dict(data)
    if method == "isotonic":
        return IsotonicCalibrator.from_dict(data)
    raise ValueError(f"unsupported calibration method: {method!r}")


class CalibrationRegistry:
    """Lookup table mapping (source, score_kind, profile) to empirically verified calibrators."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], PlattCalibrator | IsotonicCalibrator] = {}

    def register(
        self,
        calibrator: PlattCalibrator | IsotonicCalibrator,
        *,
        source: str = "*",
        score_kind: str = "*",
        profile: str = "*",
    ) -> None:
        self._entries[(source or "*", score_kind or "*", profile or "*")] = calibrator

    def get(
        self,
        *,
        source: str | None = None,
        score_kind: str | None = None,
        profile: str | None = None,
        require_verified: bool = True,
    ) -> PlattCalibrator | IsotonicCalibrator | None:
        src = source or "*"
        kind = score_kind or infer_score_kind(source, raw_score=0.0)
        prof = profile or "*"
        candidates = (
            (src, kind, prof),
            (src, kind, "*"),
            ("*", kind, prof),
            ("*", kind, "*"),
            (src, "*", prof),
            (src, "*", "*"),
            ("*", "*", "*"),
        )
        for key in candidates:
            cal = self._entries.get(key)
            if cal is None:
                continue
            if require_verified and not cal.verified:
                continue
            return cal
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONFIDENCE_SCHEMA_VERSION,
            "calibrators": [
                {
                    "source": src,
                    "score_kind": kind,
                    "profile": prof,
                    **cal.to_dict(),
                }
                for (src, kind, prof), cal in sorted(self._entries.items())
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CalibrationRegistry":
        reg = cls()
        for item in data.get("calibrators") or []:
            cal = calibrator_from_dict(item)
            reg.register(
                cal,
                source=str(item.get("source") or "*"),
                score_kind=str(item.get("score_kind") or "*"),
                profile=str(item.get("profile") or "*"),
            )
        return reg

    @classmethod
    def from_json_file(cls, path: str | Path) -> "CalibrationRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("calibration registry JSON must be an object")
        return cls.from_dict(payload)

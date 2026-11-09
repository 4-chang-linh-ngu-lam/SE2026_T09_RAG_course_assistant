import json
from pathlib import Path

import cv2
import numpy as np

PREPROCESS_VERSION = "idp-preprocess-3"
DESKEW_SEARCH_LIMIT = 4.0


def _skew_angle(gray: np.ndarray) -> float:
    """Return the corrective OpenCV rotation, not the observed ink tilt.

    Candidates are actually applied before scoring row alignment. Negating the
    winning angle would therefore rotate a tilted source farther from upright.
    """
    h, w = gray.shape
    scale = min(1.0, 700.0 / max(h, w))
    small = cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))))
    if not np.any(small < 190):
        return 0.0
    best_angle, best_score = 0.0, -1.0
    steps = int(DESKEW_SEARCH_LIMIT * 2)
    for angle in [x * 0.5 for x in range(-steps, steps + 1)]:
        matrix = cv2.getRotationMatrix2D((small.shape[1] / 2, small.shape[0] / 2), angle, 1.0)
        rotated = cv2.warpAffine(
            small, matrix, (small.shape[1], small.shape[0]),
            flags=cv2.INTER_LINEAR, borderValue=255,
        )
        binary = (rotated < 190).astype(np.uint8)
        row_sums = binary.sum(axis=1).astype(np.float32)
        score = float(np.var(row_sums))
        if score > best_score or (score == best_score and abs(angle) < abs(best_angle)):
            best_angle, best_score = angle, score
    return round(float(best_angle), 1)


def analyze_page(image_path: str | Path) -> dict:
    image = cv2.imread(str(image_path))
    if image is None:
        return {"error": "cannot_read_image"}
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    ink = gray < 245
    ys, xs = np.where(ink)
    if len(xs):
        x1, x2 = int(xs.min()), int(xs.max())
        y1, y2 = int(ys.min()), int(ys.max())
    else:
        x1 = y1 = 0
        x2, y2 = w - 1, h - 1
    margins = {
        "left": x1, "top": y1,
        "right": w - 1 - x2, "bottom": h - 1 - y2,
    }
    skew = _skew_angle(gray)
    contrast = float(np.std(gray))
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    ink_ratio = float((gray < 128).mean())
    return {
        "preprocess_version": PREPROCESS_VERSION,
        "skew_angle_convention": "opencv_corrective_rotation_degrees",
        "width": w,
        "height": h,
        "skew_angle": skew,
        "skew_estimate_saturated": abs(skew) >= DESKEW_SEARCH_LIMIT,
        "deskew_supported": abs(skew) < DESKEW_SEARCH_LIMIT,
        "needs_deskew": abs(skew) >= 1.0,
        "contrast_std": round(contrast, 2),
        "low_contrast": contrast < 25,
        "laplacian_variance": round(blur, 2),
        "blurry": blur < 100,
        "ink_ratio": round(ink_ratio, 5),
        "visible_ink_ratio": round(float(ink.mean()), 6),
        "faint_content_only": bool(len(xs) and ink_ratio < 0.003),
        # A few dark pixels is not evidence of a blank page. Faint diagrams,
        # pencil text and watermark-only pages remain reviewable content.
        "blank": not bool(len(xs)),
        "ink_bbox": [x1, y1, x2, y2],
        "margins": margins,
        "large_margin": any(
            margins[k] > (w if k in {"left", "right"} else h) * 0.05
            for k in margins
        ),
    }


def write_preprocess_metadata(result: dict, out_path: str | Path) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def preprocess_image(
    image_path: str | Path,
    out_path: str | Path,
    analysis: dict,
) -> str:
    """Apply only corrections that were actually detected.

    Deskew is geometry-preserving (marker bboxes are produced on the returned
    image). Contrast is applied on the LAB luminance channel, not by thresholding
    text, so colored textbook boxes and figures remain usable.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    if analysis.get("needs_deskew"):
        angle = float(analysis.get("skew_angle", 0.0))
        h, w = image.shape[:2]
        # A maximum at the search boundary is not a located corrective peak.
        # Preserve this unresolved geometry rather than applying a guessed
        # rotation to curved/out-of-range pages. needs_deskew stays a risk flag.
        if abs(angle) < DESKEW_SEARCH_LIMIT:
            matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
            image = cv2.warpAffine(
                image, matrix, (w, h),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(255, 255, 255),
            )
    if analysis.get("low_contrast"):
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        l_channel = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l_channel)
        image = cv2.cvtColor(
            cv2.merge([l_channel, a_channel, b_channel]), cv2.COLOR_LAB2BGR
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), image)
    return str(out_path)

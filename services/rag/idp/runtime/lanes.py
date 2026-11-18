"""Profiles configure one service, never independent parsing pipelines."""

from dataclasses import replace

from idp.pdf.service import AUTO_LANGUAGE, DeepDocConfig, resolve_engine

PROFILES = ("FAST_PREVIEW", "QUALITY", "HYBRID")


def configuration(
    profile="HYBRID",
    *,
    canonical_version=1,
    limits=None,
    language=AUTO_LANGUAGE,
    engine=None,
):
    if profile not in PROFILES:
        raise ValueError("unsupported execution profile")
    limits = limits or {}
    admission_keys = {"max_source_bytes", "max_pages", "max_total_render_pixels"}
    allowed = {
        "timeout_seconds",
        "ocr_timeout_seconds",
        "max_calls",
        "max_calls_per_page",
        "max_total_pixels",
        "max_pixels",
        "max_regions",
        "dpi",
        "max_gpu_calls",
        "paddle_device",
        "formula_regions",
        "formula_max_pixels",
        "formula_max_regions",
        "formula_model",
        "ocr_backend",
    }
    if set(limits) - (allowed | admission_keys):
        raise ValueError("unknown resource limit")
    cfg = DeepDocConfig(
        engine=resolve_engine(engine, canonical_version),
        canonical_version=canonical_version,
        language=language,
        ocr_backend="marker" if profile == "QUALITY" else "tesseract",
        dpi=144 if profile == "FAST_PREVIEW" else 216,
        max_pixels=1_000_000 if profile == "FAST_PREVIEW" else 4_000_000,
        timeout_seconds=1200,
        ocr_timeout_seconds=300 if profile == "QUALITY" else 45,
    )
    return replace(
        cfg,
        admission=replace(
            cfg.admission, **{k: v for k, v in limits.items() if k in admission_keys}
        ),
        **{k: v for k, v in limits.items() if k in allowed},
    )

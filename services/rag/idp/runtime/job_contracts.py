"""Compatible normalization into the existing queue's v1 request representation."""

from dataclasses import asdict
from pathlib import Path

from idp.orchestration.worker import KNOWN_JOB_FIELDS, sha256_file
from idp.orchestration.worker import JobRequest as LegacyJobRequest
from idp.pdf.render import digest

from idp.pdf.service import AUTO_LANGUAGE, resolve_engine

from .lanes import configuration

OPTIONS = "deepdoc_runtime"


class JobRequest:
    @classmethod
    def from_dict(cls, data, input_roots):
        extra = {
            "input_path",
            "processing_mode",
            "execution_profile",
            "requested_canonical_version",
            "resource_limits",
            "language",
            "pdf_engine",
        }
        if not isinstance(data, dict) or set(data) - (KNOWN_JOB_FIELDS | extra):
            raise ValueError("unknown job fields")
        value = dict(data)
        if "input_path" in value:
            raw = value.pop("input_path")
            if (
                value.get("pdf_path")
                and Path(value["pdf_path"]).resolve() != Path(raw).resolve()
            ):
                raise ValueError("input aliases disagree")
            value["pdf_path"] = raw
        path = Path(value.get("pdf_path", "")).expanduser().resolve()
        if not any(path.is_relative_to(Path(root).resolve()) for root in input_roots):
            raise ValueError("input outside allowed roots")
        if not path.is_file():
            raise ValueError("input does not exist")
        profile = value.pop("execution_profile", value.pop("processing_mode", "HYBRID"))
        version = value.pop("requested_canonical_version", 1)
        opts = {
            "profile": profile,
            "canonical_version": version,
            "limits": value.pop("resource_limits", {}),
            "language": value.pop("language", AUTO_LANGUAGE),
            "engine": resolve_engine(value.pop("pdf_engine", None), version),
        }
        cfg = configuration(**opts)
        if path.stat().st_size > cfg.admission.max_source_bytes:
            raise ValueError("input exceeds configured source byte limit")
        if value.get("pages") is None:
            if path.suffix.lower() == ".pdf":
                from idp.pdf.native.preflight import PdfSource

                with PdfSource(path.read_bytes(), policy=cfg.admission) as source:
                    pages = list(source.geometry)
            else:
                pages = [1]
            value["pages"] = pages
        metadata = dict(value.get("metadata", {}))
        if OPTIONS in metadata:
            raise ValueError("reserved runtime metadata")
        metadata[OPTIONS] = opts
        value["metadata"] = metadata
        if "job_id" not in value:
            value["job_id"] = (
                "job-"
                + digest(
                    {
                        "source_sha256": sha256_file(path),
                        "pages": value["pages"],
                        "options": opts,
                    }
                )[:24]
            )
        return LegacyJobRequest.from_dict(value, [Path(root) for root in input_roots])


def serialize(job):
    value = asdict(job)
    for key in ("pdf_path", "image_dir", "marker_dir", "gold_path"):
        if value[key] is not None:
            value[key] = str(value[key])
    value["schema_version"] = 1
    return value

"""Local Vietnamese extractive QA reader for the opt-in ``vi_mrc`` policy.

The reader is deliberately separate from the text generator adapter.  It loads
only caller-supplied local artifacts, never downloads a checkpoint, and returns
source-bound spans so the normal answer contract can attach citations.  The
default pipeline remains unchanged; this adapter is the non-commercial
``nguyenvulebinh/vi-mrc-large`` experiment path.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
from collections.abc import Mapping, Sequence


VI_MRC_READER_VERSION = "idp-vi-mrc-large-reader-1"
VI_MRC_ANSWER_VERSION = "idp-vi-mrc-large-answer-1"


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _validate_provenance(value: Mapping) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(value.get(key), str) or not value[key]
        for key in ("repo", "revision", "variant")
    ):
        raise ValueError("vi-mrc artifact repo, revision and variant must be declared")
    return {key: value[key] for key in ("repo", "revision", "variant")}


def _validate_manifest(model_path: Path, manifest: Mapping | None) -> str | None:
    if manifest is None:
        return None
    if not isinstance(manifest, Mapping) or not manifest:
        raise ValueError("vi-mrc model manifest must be a nonempty mapping")
    root = model_path.resolve()
    normalized: dict[str, str] = {}
    for relative, expected in manifest.items():
        if not isinstance(relative, str) or not relative or not isinstance(expected, str):
            raise ValueError("vi-mrc model manifest entries must be path/SHA256 strings")
        file_path = (root / relative).resolve()
        if root not in file_path.parents or not file_path.is_file():
            raise ValueError("vi-mrc model manifest references a file outside the model directory")
        actual = _sha256(file_path)
        if actual != expected:
            raise ValueError(f"vi-mrc model checksum mismatch: {relative}")
        normalized[relative.replace("\\", "/")] = actual
    payload = json.dumps(dict(sorted(normalized.items())), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalise_answer(text: str) -> str:
    return " ".join(text.casefold().split())


def _map_candidate_span(item: Mapping, candidate: Mapping) -> list[dict]:
    """Map the selected reader offsets into immutable source coordinates."""
    text = item.get("text")
    record = item.get("record")
    start, end, answer = candidate.get("start"), candidate.get("end"), candidate.get("answer")
    if (
        not isinstance(text, str)
        or not isinstance(record, Mapping)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or not isinstance(answer, str)
        or not 0 <= start < end <= len(text)
        or text[start:end] != answer
    ):
        raise ValueError("vi-mrc candidate is not an exact evidence substring")
    spans = record.get("source_spans")
    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not isinstance(spans, list):
        raise ValueError("vi-mrc evidence has no source span mapping")
    mapped, covered = [], 0
    for span in spans:
        if not isinstance(span, Mapping):
            continue
        left, right = max(start, span.get("start", -1)), min(end, span.get("end", -1))
        if left >= right:
            continue
        source_start = span.get("source_start")
        if not isinstance(source_start, int):
            raise ValueError("vi-mrc source span mapping is invalid")
        mapped.append({"source_id": source_id, "start": source_start + left - span["start"],
                       "end": source_start + right - span["start"]})
        covered += sum(not char.isspace() for char in text[left:right])
    if not mapped or covered != sum(not char.isspace() for char in answer):
        raise ValueError("vi-mrc candidate lacks complete source mapping")
    return mapped


def answer_from_result(result: Mapping, evidence: Sequence[Mapping]) -> dict:
    """Turn a reader result into the normal source-bound answer contract."""
    if not isinstance(result, Mapping) or not isinstance(evidence, (list, tuple)):
        raise ValueError("invalid vi-mrc reader result")
    if result.get("status") == "insufficient_evidence":
        return {
            "version": VI_MRC_ANSWER_VERSION,
            "status": "insufficient_evidence",
            "claims": [],
            "answer": "",
            "citation_location_verified": True,
            "semantic_grounding_verified": False,
            "reader_trace": dict(result),
        }
    if result.get("status") != "answered" or not isinstance(result.get("candidate"), Mapping):
        raise ValueError("invalid vi-mrc answer status")
    candidate = result["candidate"]
    item = next((item for item in evidence if item.get("id") == candidate.get("source")), None)
    if item is None:
        raise ValueError("vi-mrc candidate references unknown evidence")
    answer = candidate.get("answer")
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 1600:
        raise ValueError("invalid vi-mrc candidate answer")
    mapped = _map_candidate_span(item, candidate)
    citation = {"id": item["id"], "source_spans": mapped, "citation_scope": "exact_span"}
    # The general answer contract allows an exact quote, but caps it at 512
    # characters. Keep the source-span mapping for longer legal answers.
    if 3 <= len(answer) <= 512:
        citation["quote"] = answer
    return {
        "version": VI_MRC_ANSWER_VERSION,
        "status": "answered",
        "claims": [{"text": answer, "evidence": [citation]}],
        "answer": f"{answer} [{item['id']}]",
        "citation_location_verified": True,
        "semantic_grounding_verified": False,
        "reader_trace": dict(result),
    }


class _TransformersCounter:
    """Small tokenizer counter used by callers that need a reader budget."""

    def __init__(self, tokenizer, identity: Mapping):
        self.tokenizer = tokenizer
        self.identity = dict(identity)

    def count(self, text: str) -> int:
        if not isinstance(text, str):
            raise ValueError("reader token counter expects text")
        encoded = self.tokenizer(text, add_special_tokens=True, truncation=False)
        ids = encoded.get("input_ids")
        if not isinstance(ids, list):
            raise ValueError("reader tokenizer returned invalid token IDs")
        return len(ids)


class ViMrcReader:
    """CPU/local extractive reader matching the winning ViQuAD configuration.

    The model and optional adapted QA head are loaded from local paths.  The
    reader does not perform retrieval, authorization, citation rewriting or
    fallback generation; ``RagPipeline`` owns those responsibilities.
    """

    def __init__(
        self,
        model_path,
        *,
        provenance,
        model_manifest: Mapping | None = None,
        qa_head_path=None,
        qa_head_sha256: str | None = None,
        device: str = "cpu",
        threads: int = 4,
        top_passages: int = 3,
        max_length: int = 384,
        stride: int = 128,
        max_answer_tokens: int = 64,
        null_margin_threshold: float = -2.0,
        top_spans_per_window: int = 8,
    ):
        if device not in {"cpu", "cuda"}:
            raise ValueError("vi-mrc device must be cpu or cuda")
        if type(threads) is not int or not 1 <= threads <= 32:
            raise ValueError("vi-mrc threads must be an integer in 1..32")
        limits = {
            "top_passages": (top_passages, 1, 20),
            "max_length": (max_length, 128, 4096),
            "stride": (stride, 0, max_length - 1),
            "max_answer_tokens": (max_answer_tokens, 1, 256),
            "top_spans_per_window": (top_spans_per_window, 1, 32),
        }
        for name, (value, low, high) in limits.items():
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"invalid vi-mrc {name}")
        if type(null_margin_threshold) not in (int, float) or not float("-inf") < null_margin_threshold < float("inf"):
            raise ValueError("invalid vi-mrc null margin threshold")
        if qa_head_path is None and qa_head_sha256 is not None:
            raise ValueError("qa_head_sha256 requires qa_head_path")

        # Optional dependencies are imported only when this opt-in reader is
        # constructed, so the existing local-LLM pipeline remains lightweight.
        try:
            import torch
            from transformers import AutoModelForQuestionAnswering, AutoTokenizer
        except ImportError as error:  # pragma: no cover - depends on deployment extras
            raise RuntimeError("vi-mrc reader requires torch and transformers") from error

        self.torch = torch
        self.device = device
        self.top_passages = top_passages
        self.max_length = max_length
        self.stride = stride
        self.max_answer_tokens = max_answer_tokens
        self.null_margin_threshold = float(null_margin_threshold)
        self.top_spans_per_window = top_spans_per_window
        self.provenance = _validate_provenance(provenance)
        self.model_path = Path(model_path).resolve(strict=True)
        if not self.model_path.is_dir():
            raise ValueError("vi-mrc model_path must be a directory")
        manifest_sha256 = _validate_manifest(self.model_path, model_manifest)

        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("vi-mrc cuda device requested but CUDA is unavailable")
        if device == "cpu":
            torch.set_num_threads(threads)
        model = AutoModelForQuestionAnswering.from_pretrained(
            self.model_path, local_files_only=True
        )
        tokenizer = AutoTokenizer.from_pretrained(
            self.model_path, local_files_only=True, use_fast=True
        )
        if not getattr(tokenizer, "is_fast", False):
            raise ValueError("vi-mrc requires a fast tokenizer for source offsets")
        model = model.to(device).eval()

        head_sha256 = None
        if qa_head_path is not None:
            head_path = Path(qa_head_path).resolve(strict=True)
            head_sha256 = _sha256(head_path)
            if qa_head_sha256 is not None and head_sha256 != qa_head_sha256:
                raise ValueError("vi-mrc adapted QA head checksum mismatch")
            state = torch.load(head_path, map_location="cpu", weights_only=True)
            model.qa_outputs.load_state_dict(state, strict=True)
            model.qa_outputs.to(device)
            model.eval()

        self.model = model
        self.tokenizer = tokenizer
        counter_identity = {
            "kind": "vi_mrc_fast_tokenizer",
            "unit": "tokens",
            "artifact_revision": self.provenance["revision"],
            "max_length": max_length,
        }
        self.counter = _TransformersCounter(tokenizer, counter_identity)
        self.identity = {
            "adapter": VI_MRC_READER_VERSION,
            "artifact_provenance": dict(self.provenance),
            "model_manifest_sha256": manifest_sha256,
            "qa_head_sha256": head_sha256,
            "device": device,
            "threads": threads if device == "cpu" else None,
            "top_passages": top_passages,
            "max_length": max_length,
            "stride": stride,
            "max_answer_tokens": max_answer_tokens,
            "null_margin_threshold": self.null_margin_threshold,
            "top_spans_per_window": top_spans_per_window,
            "counter": dict(counter_identity),
        }

    def _validate_evidence(self, evidence: Sequence[Mapping]) -> list[Mapping]:
        if not isinstance(evidence, (list, tuple)):
            raise ValueError("vi-mrc evidence must be a sequence")
        selected = list(evidence[: self.top_passages])
        if any(
            not isinstance(item, Mapping)
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or not isinstance(item.get("text"), str)
            or not item["text"].strip()
            for item in selected
        ):
            raise ValueError("vi-mrc evidence records must contain nonempty id/text")
        return selected

    def candidates(self, question: str, evidence: Sequence[Mapping]) -> list[dict]:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("vi-mrc question must be nonempty")
        selected = self._validate_evidence(evidence)
        if not selected:
            return []
        tokenizer = self.tokenizer
        batch = tokenizer(
            [question] * len(selected),
            [item["text"] for item in selected],
            max_length=self.max_length,
            stride=self.stride,
            truncation="only_second",
            padding=True,
            return_offsets_mapping=True,
            return_overflowing_tokens=True,
            return_tensors="pt",
        )
        offsets = batch.pop("offset_mapping")
        windows = batch.pop("overflow_to_sample_mapping")
        encoded = {key: value.to(self.device) for key, value in batch.items()}
        with self.torch.inference_mode():
            result = self.model(**encoded)
            start_logits, end_logits = result.start_logits, result.end_logits
        candidates: dict[tuple[str, str], dict] = {}
        for window_index, sample_index in enumerate(windows.tolist()):
            # ``sequence_ids`` is a BatchEncoding method, so this works for
            # XLM-R tokenizers that do not emit token_type_ids.
            sequence_ids = batch.sequence_ids(window_index)
            token_ids = [index for index, segment in enumerate(sequence_ids) if segment == 1]
            if not token_ids:
                continue
            sample = selected[sample_index]
            start_values = start_logits[window_index, token_ids]
            end_values = end_logits[window_index, token_ids]
            positions = self.torch.arange(len(token_ids), device=start_values.device)
            distance = positions[None, :] - positions[:, None]
            joint = start_values[:, None] + end_values[None, :]
            joint = joint.masked_fill(
                (distance < 0) | (distance >= self.max_answer_tokens), -self.torch.inf
            )
            finite = self.torch.isfinite(joint)
            if not finite.any():
                continue
            null = float(start_logits[window_index, 0] + end_logits[window_index, 0])
            values, flat_positions = joint.flatten().topk(
                min(self.top_spans_per_window, int(finite.sum().item()))
            )
            for value, flat_position in zip(values.tolist(), flat_positions.tolist()):
                start_position, end_position = divmod(flat_position, len(token_ids))
                start = int(offsets[window_index, token_ids[start_position], 0].item())
                end = int(offsets[window_index, token_ids[end_position], 1].item())
                if not 0 <= start < end <= len(sample["text"]):
                    continue
                answer = sample["text"][start:end]
                if not answer.strip():
                    continue
                candidate = {
                    "answer": answer,
                    "source": sample["id"],
                    "start": start,
                    "end": end,
                    "null_margin": float(value - null),
                    "passage_rank": sample_index + 1,
                    "window_index": window_index,
                }
                key = (sample["id"], _normalise_answer(answer))
                if key not in candidates or candidates[key]["null_margin"] < candidate["null_margin"]:
                    candidates[key] = candidate
        return sorted(candidates.values(), key=lambda item: (-item["null_margin"], item["source"], item["start"]))

    def answer(self, question: str, evidence: Sequence[Mapping]) -> dict:
        started = time.perf_counter()
        candidates = self.candidates(question, evidence)
        selected = candidates[0] if candidates else None
        if selected is not None and selected["null_margin"] >= self.null_margin_threshold:
            status = "answered"
            answer = selected["answer"]
        else:
            status = "insufficient_evidence"
            answer = ""
            selected = None
        return {
            "version": VI_MRC_ANSWER_VERSION,
            "status": status,
            "answer": answer,
            "candidate": selected,
            "candidates": candidates[: self.top_spans_per_window],
            "seconds": time.perf_counter() - started,
            "threshold": self.null_margin_threshold,
            "reader_identity": dict(self.identity),
        }

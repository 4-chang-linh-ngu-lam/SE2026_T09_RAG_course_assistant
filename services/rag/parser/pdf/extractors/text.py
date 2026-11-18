"""Native text alternatives and explicit, source-bound glyph selection."""

from __future__ import annotations

import importlib.metadata
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from html.parser import HTMLParser

from ...pdf_glyph_backend import PdfiumTextBackend
from ...pdf_glyph_inspector import GlyphTextBlock, PdfGlyphInspector, detect_text_anomalies
from ...pdf_glyph_repair import apply_verified_font_glyph_correction, apply_verified_glyph_correction, prepare_verified_glyph_corrections
from ...source_observation import (
    DeepDocBoundingBox,
    DeepDocCandidate,
    DeepDocContentOrigin,
    DeepDocDecision,
    DeepDocDecisionAction,
    DeepDocDiagnostic,
    DeepDocDiagnosticLevel,
    DeepDocEvidence,
    DeepDocExtractionSource,
    DeepDocFontEvidence,
    DeepDocGlyphFinding,
    DeepDocObservation,
    DeepDocObservationKind,
    DeepDocProducer,
    DeepDocSecondaryTextEvidence,
    DeepDocSourceLocation,
    DeepDocSourceSpan,
    DeepDocTextEdit,
    DeepDocTextExtractionReport,
)
from ..contracts import _fingerprint, _source_trace
from ..geometry import poppler_display_size
from ..preflight import PdfAdmissionError, PdfSource, run_bounded_process

SELECTION_POLICY = "native-text-selection:1"


@dataclass(frozen=True, slots=True)
class NativeTextResult:
    observations: tuple[DeepDocObservation, ...]
    blocks: tuple[GlyphTextBlock, ...]
    diagnostics: tuple[DeepDocDiagnostic, ...]
    report: DeepDocTextExtractionReport
    summary: dict
    corrections_sha256: str
    words: tuple[DeepDocSourceSpan, ...]
    lines: tuple[DeepDocSourceSpan, ...]


def extract_native_text(source: PdfSource, *, glyph_corrections=None) -> NativeTextResult:
    producer, blocks, word_geometry, line_geometry = _read_blocks(source)
    correction_index = prepare_verified_glyph_corrections(source.data, glyph_corrections)
    raw_findings = list(detect_text_anomalies(blocks))
    anomaly_count = len(raw_findings)
    suspicious = {finding["page"] for finding in raw_findings if finding.get("secondary_verification_recommended")}
    candidates = suspicious | {block.page for block in blocks if re.search(r"\b6\s*=", block.text)}
    inspector = PdfGlyphInspector()
    inspection = inspector.inspect(source.data, suspicious_pages=suspicious, pages_to_inspect=candidates, source=source)
    raw_findings[:0] = inspection.diagnostics
    secondary = {}
    secondary_producer = None
    if inspection.pages_to_verify:
        secondary_producer = DeepDocProducer("pypdfium2", _package_version("pypdfium2"))
        try:
            secondary = PdfiumTextBackend().extract_pages(source.data, inspection.pages_to_verify, source=source)
            for page in tuple(secondary):
                chars = secondary[page]
                if page not in inspection.pages_to_verify or any(char.page != page for char in chars) or [char.index for char in chars] != sorted({char.index for char in chars}):
                    secondary.pop(page)
                    raw_findings.append(
                        {"code": "PDF_SECONDARY_SOURCE_FRAME_CONFLICT", "status": "CONFLICT", "reason": "Secondary character identities do not match the requested source page/index frame"}
                    )
        except PdfAdmissionError:
            raise
        except Exception as exc:  # noqa: BLE001 - optional verification failures preserve native text.
            raw_findings.append({"code": "PDF_GLYPH_SECONDARY_BACKEND_FAILURE", "status": "SUSPECT", "reason": f"{type(exc).__name__}: {exc}"[:1000]})
    analysis = inspector.verify(inspection, secondary, blocks)
    raw_findings.extend(analysis.findings)
    fonts = tuple(sorted((_font_evidence(font, source.report.source_sha256) for font in inspection.font_resources), key=lambda font: font.id))
    assigned, assignment_findings = _assign_characters(blocks, secondary, source)
    raw_findings.extend(assignment_findings)
    proposals = defaultdict(list)
    for proposal in analysis.corrections:
        proposals[(proposal.page, proposal.block)].append(proposal)
    observations = []
    applied_manual = set()
    manual_count = recovered_count = 0
    for block in blocks:
        source.check_deadline()
        observation = DeepDocObservation(
            block.source_id,
            len(observations),
            DeepDocObservationKind.TEXT,
            block.text,
            DeepDocExtractionSource.NATIVE,
            "PARAGRAPH",
            locations=(DeepDocSourceLocation(block.page, block.page_width, block.page_height, DeepDocBoundingBox(*block.bbox)),),
            attributes={"text_extraction_source": "NATIVE", "ocr_used": False},
        )
        trace = _source_trace(observation, source.report.source_sha256, producer)
        evidence = list(trace.evidence)
        alternatives = list(trace.candidates)
        decisions = []
        secondary_chars = assigned.get(block.source_id, ())
        if secondary_chars:
            item, candidate = _secondary_candidate(trace, secondary_chars, block.page, secondary_producer)
            evidence.append(item)
            alternatives.append(candidate)
            decisions.append(_decision(candidate, "UNRESOLVED", "SECONDARY_BACKEND_IS_NOT_SOURCE_PROOF"))
        recovered = {}
        for proposal in sorted(proposals[(block.page, block.block)], key=lambda item: _fingerprint(asdict(item))):
            try:
                value = apply_verified_font_glyph_correction(block.text, pdf_sha256=source.report.source_sha256, page=block.page, block=block.block, correction=proposal)
                edits = tuple(DeepDocTextEdit(*span) for span in sorted(proposal.spans))
                font_ids = tuple(font.id for font in fonts if font.page == block.page and font.font_fingerprint in proposal.font_fingerprints)
                if not set(proposal.font_fingerprints).issubset({font.font_fingerprint for font in fonts if font.id in font_ids}):
                    raise ValueError("recovery font identities were not present in source inspection")
                for proof in proposal.evidence:
                    inspected = {(font.font_fingerprint, font.embedded_font_sha256) for font in fonts if font.id in font_ids}
                    if (proof.font_fingerprint, proof.embedded_font_sha256) not in inspected or any(
                        not any((fingerprint, digest) in inspected for digest in proof.equals_font_program_hashes) for fingerprint in proof.equals_font_fingerprints
                    ):
                        raise ValueError("recovery programs do not match inspected font hashes")
                item, candidate = _recovery_candidate(trace, value, edits, DeepDocProducer("font-glyph-recovery", "1"), glyph_proofs=proposal.evidence, font_evidence_ids=font_ids)
                # Validate each proposal before admitting it as an optional alternative.
                replace(
                    trace,
                    evidence=(*trace.evidence, item),
                    candidates=(*trace.candidates, candidate),
                    source_candidate_id=candidate.id,
                    decisions=(_decision(candidate, "ACCEPT", "VERIFIED_FONT_GLYPH_RECOVERY"),),
                )
                if candidate.id not in recovered:
                    recovered[candidate.id] = candidate
                    evidence.append(item)
                    alternatives.append(candidate)
            except ValueError as exc:
                raw_findings.append({"code": "PDF_FONT_GLYPH_PROPOSAL_REJECTED", "status": "CONFLICT", "page": block.page, "source_id": block.source_id, "reason": str(exc)[:1000]})
        selected = trace.candidates[0]
        value, review = apply_verified_glyph_correction(block.text, page=block.page, block=block.block, corrections=correction_index)
        if review is not None:
            edits = (DeepDocTextEdit(0, len(block.text), block.text, value),)
            item, selected = _recovery_candidate(trace, value, edits, DeepDocProducer("reviewed-native-correction", "1"), review=review)
            evidence.append(item)
            alternatives.append(selected)
            decisions.append(_decision(selected, "ACCEPT", "REVIEWED_BLOCK_OVERRIDE"))
            applied_manual.add((block.page, block.block))
            manual_count += 1
        elif len(recovered) == 1:
            selected = next(iter(recovered.values()))
            decisions.append(_decision(selected, "ACCEPT", "VERIFIED_FONT_GLYPH_RECOVERY"))
            recovered_count += 1
        for candidate in recovered.values():
            if candidate.id != selected.id:
                decisions.append(_decision(candidate, "UNRESOLVED", "REVIEWED_OVERRIDE_TAKES_PRECEDENCE" if review else "CONFLICTING_FONT_RECOVERY"))
        if len(recovered) > 1 and review is None:
            raw_findings.append(
                {
                    "code": "PDF_FONT_GLYPH_RECOVERY_CONFLICT",
                    "status": "CONFLICT",
                    "page": block.page,
                    "source_id": block.source_id,
                    "reason": "Multiple distinct source-bound glyph candidates target this block; raw text was selected",
                }
            )
        if selected.id != trace.raw_candidate_id:
            raw_findings.append(
                {
                    "code": "PDF_VERIFIED_GLYPH_CORRECTION" if review else "PDF_FONT_GLYPH_RECOVERED",
                    "status": "VERIFIED",
                    "page": block.page,
                    "source_id": block.source_id,
                    "candidate_id": selected.id,
                    "reason": "Selected an exact source-bound native text correction",
                }
            )
        updated = replace(trace, evidence=tuple(evidence), candidates=tuple(alternatives), decisions=tuple(decisions), source_candidate_id=selected.id)
        observations.append(
            replace(observation, text=selected.text, extraction=updated, extraction_source=DeepDocExtractionSource.DERIVED if selected.id != trace.raw_candidate_id else DeepDocExtractionSource.NATIVE)
        )
    unmatched = correction_index.keys() - applied_manual
    if unmatched:
        raise ValueError(f"glyph corrections did not match Poppler blocks: {sorted(unmatched)}")
    observed_pages = {block.page for block in blocks}
    for page in source.geometry.keys() - observed_pages:
        raw_findings.append({"code": "PDF_PAGE_WITHOUT_NATIVE_TEXT", "status": "SUSPECT", "page": page, "reason": f"PDF page {page} has no native text; OCR was not attempted", "structural": True})
    findings = _typed_findings(raw_findings, observations, fonts, blocks, len(source.geometry))
    report = DeepDocTextExtractionReport(
        source.report.source_sha256,
        producer,
        DeepDocProducer("pypdf-font-inspector", _package_version("pypdf") + "/glyph:1"),
        secondary_producer,
        fonts,
        findings,
        tuple(sorted(inspection.pages_to_verify)),
        tuple(sorted(secondary)),
    )
    diagnostics = tuple(
        DeepDocDiagnostic(
            item.code,
            item.reason,
            DeepDocDiagnosticLevel.INFO if item.status in {"CLEAN", "VERIFIED"} else DeepDocDiagnosticLevel.WARNING,
            item.code == "PDF_PAGE_WITHOUT_NATIVE_TEXT",
            metadata={"finding_id": item.id, "page": item.page, "status": item.status, "source_id": item.source_id},
        )
        for item in findings
    )
    unresolved = any(item.status in {"SUSPECT", "CONFLICT"} and item.code not in {"PDF_FONT_GLYPH_MAPPING_SUSPECT", "PDF_PAGE_WITHOUT_NATIVE_TEXT"} for item in findings)
    summary = {
        **inspection.summary(),
        "manual_glyph_correction_count": manual_count,
        "font_glyph_recovery_count": recovered_count,
        "text_anomaly_count": anomaly_count,
        "verification_finding_count": len(analysis.findings),
        "candidate_page_count": len(candidates),
        "secondary_backend_calls": int(bool(inspection.pages_to_verify)),
        "secondary_pages_extracted": len(secondary),
        "status": "SUSPECT" if unresolved else "VERIFIED" if recovered_count or manual_count else "CLEAN",
    }
    raw_ids = {item.source_id: item.extraction.raw_candidate_id for item in observations}
    words = tuple(DeepDocSourceSpan(raw_ids[key], start, end, text, location) for key, start, end, text, location in word_geometry)
    lines = tuple(DeepDocSourceSpan(raw_ids[key], start, end, text, location) for key, start, end, text, location in line_geometry)
    return NativeTextResult(tuple(observations), tuple(blocks), diagnostics, report, summary, _fingerprint([asdict(value) for _, value in sorted(correction_index.items())]), words, lines)


def _recovery_candidate(trace, text, edits, producer, *, glyph_proofs=(), font_evidence_ids=(), review=None):
    payload = {
        "region": trace.region.id,
        "parent": trace.raw_candidate_id,
        "producer": asdict(producer),
        "text": text,
        "edits": [asdict(edit) for edit in edits],
        "proofs": [asdict(proof) for proof in glyph_proofs],
        "review": asdict(review) if review else None,
        "fonts": font_evidence_ids,
    }
    evidence = DeepDocEvidence(
        "evidence:" + _fingerprint(payload),
        trace.region.id,
        DeepDocContentOrigin.SOURCE_TRANSCRIPTION,
        producer,
        _fingerprint({"raw_candidate": trace.raw_candidate_id}),
        trace.evidence[0].source_sha256,
        font_evidence_ids=font_evidence_ids,
        glyph_proofs=tuple(glyph_proofs),
        review=review,
    )
    candidate = DeepDocCandidate(
        "candidate:" + _fingerprint({**payload, "evidence": evidence.id}),
        trace.region.id,
        DeepDocContentOrigin.SOURCE_TRANSCRIPTION,
        producer,
        (trace.evidence[0].id, evidence.id),
        text,
        parent_candidate_id=trace.raw_candidate_id,
        edits=edits,
    )
    return evidence, candidate


def _secondary_candidate(trace, chars, page, producer):
    ranges = []
    for char in chars:
        if ranges and char.index == ranges[-1][1]:
            ranges[-1][1] += 1
        else:
            ranges.append([char.index, char.index + 1])
    char_sha = _fingerprint([asdict(char) for char in chars])
    secondary = DeepDocSecondaryTextEvidence(page, tuple(tuple(value) for value in ranges), char_sha)
    evidence = DeepDocEvidence(
        "evidence:" + _fingerprint({"region": trace.region.id, "producer": asdict(producer), "characters": char_sha}),
        trace.region.id,
        DeepDocContentOrigin.SOURCE_TRANSCRIPTION,
        producer,
        trace.evidence[0].input_sha256,
        trace.evidence[0].source_sha256,
        secondary_text=secondary,
    )
    candidate = DeepDocCandidate(
        "candidate:" + _fingerprint({"evidence": evidence.id, "text": "".join(char.text for char in chars)}),
        trace.region.id,
        DeepDocContentOrigin.SOURCE_TRANSCRIPTION,
        producer,
        (evidence.id,),
        "".join(char.text for char in chars),
    )
    return evidence, candidate


def _decision(candidate, action, reason):
    return DeepDocDecision(
        "decision:" + _fingerprint({"candidate": candidate.id, "action": action, "reason": reason, "policy": SELECTION_POLICY}),
        candidate.id,
        DeepDocDecisionAction(action),
        reason,
        SELECTION_POLICY,
        candidate.evidence_ids,
    )


def _assign_characters(blocks, secondary, source):
    by_page = defaultdict(list)
    for block in blocks:
        by_page[block.page].append(block)
    assigned = defaultdict(list)
    findings = []
    for page, chars in secondary.items():
        owners = []
        for index, char in enumerate(chars):
            if index % 256 == 0:
                source.check_deadline()
            choices = []
            if char.bbox is not None:
                x, y = (char.bbox[0] + char.bbox[2]) / 2, (char.bbox[1] + char.bbox[3]) / 2
                choices = [
                    block.source_id
                    for block in by_page[page]
                    if block.bbox and block.bbox[0] / block.page_width <= x <= block.bbox[2] / block.page_width and block.bbox[1] / block.page_height <= y <= block.bbox[3] / block.page_height
                ]
            owners.append(choices[0] if len(choices) == 1 else None)
        right = [None] * len(owners)
        nearest = None
        for index in range(len(owners) - 1, -1, -1):
            right[index] = nearest
            nearest = owners[index] or nearest
        previous = None
        unassigned = 0
        for index, char in enumerate(chars):
            owner = owners[index]
            if owner is None and char.bbox is None and char.text.isspace() and previous is not None and previous == right[index]:
                owner = previous
            if owner is not None:
                assigned[owner].append(char)
            elif not char.text.isspace():
                unassigned += 1
            previous = owners[index] or previous
        if unassigned:
            findings.append(
                {
                    "code": "PDF_SECONDARY_TEXT_UNASSIGNED",
                    "status": "SUSPECT",
                    "page": page,
                    "reason": f"{unassigned} secondary characters could not be uniquely assigned to a native block; no text was synthesized",
                }
            )
    return assigned, findings


def _font_evidence(font, source_sha):
    key = {"source": source_sha, "page": font.page, "scope": font.scope, "resource": font.resource_name, "fingerprint": font.font_fingerprint}
    return DeepDocFontEvidence(
        "font:" + _fingerprint(key),
        font.page,
        font.resource_name,
        font.scope,
        font.font_fingerprint,
        font.embedded_font_sha256,
        font.encoding_sha256,
        font.to_unicode_sha256,
        font.encoding_status,
        font.to_unicode_status,
        font.base_font,
    )


def _typed_findings(raw_findings, observations, fonts, blocks, page_count):
    by_id = {item.source_id: item for item in observations}
    by_key = {(block.page, block.block): block.source_id for block in blocks}
    records = {}
    for finding in raw_findings:
        page = finding.get("page")
        page = page if type(page) is int and 1 <= page <= page_count else None
        source_id = finding.get("source_id") or finding.get("observation_source_id") or by_key.get((page, finding.get("block")))
        box = finding.get("bbox")
        if source_id is None and page is not None and isinstance(box, (list, tuple)) and len(box) == 4:
            x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            matches = [
                block.source_id
                for block in blocks
                if block.page == page
                and block.bbox
                and block.bbox[0] / block.page_width <= x <= block.bbox[2] / block.page_width
                and block.bbox[1] / block.page_height <= y <= block.bbox[3] / block.page_height
            ]
            source_id = matches[0] if len(matches) == 1 else None
        if source_id not in by_id:
            source_id = None
        font_ids = tuple(font.id for font in fonts if font.page == page and finding.get("font_fingerprint") == font.font_fingerprint)
        candidate_ids = evidence_ids = ()
        raw_span = finding.get("character_span")
        if type(finding.get("character_index")) is int:
            raw_span = (finding["character_index"], finding["character_index"] + 1)
        if source_id is not None:
            trace = by_id[source_id].extraction
            candidate_ids = (
                (trace.raw_candidate_id,)
                if raw_span is not None
                else (finding["candidate_id"],)
                if finding.get("candidate_id") in {candidate.id for candidate in trace.candidates}
                else tuple(candidate.id for candidate in trace.candidates)
            )
            evidence_ids = tuple(sorted({key for candidate in trace.candidates if candidate.id in candidate_ids for key in candidate.evidence_ids}))
        scope = "REGION" if source_id else "FONT_RESOURCE" if font_ids else "PAGE" if page else "DOCUMENT"
        payload = {
            "code": str(finding.get("code") or "PDF_GLYPH_INSPECTION")[:128],
            "status": finding.get("status", "SUSPECT"),
            "scope": scope,
            "reason": str(finding.get("reason") or finding.get("code") or "PDF glyph finding").strip()[:4096],
            "page": page,
            "source_id": source_id,
            "candidate_ids": candidate_ids,
            "evidence_ids": evidence_ids,
            "font_evidence_ids": font_ids,
            "glyph_name": finding.get("glyph_name"),
            "character_code_hex": finding.get("character_code_hex"),
            "unicode_mapping": finding.get("unicode_mapping"),
        }
        payload.update(
            {
                key: finding.get(key)
                for key in ("raw_extracted_text", "secondary_text", "resource_scope", "operator_index", "string_index", "code_index", "cid", "cid_status", "glyph_id", "glyph_id_status")
            }
        )
        if payload["raw_extracted_text"] is None:
            payload["raw_extracted_text"] = finding.get("decoded_operand_text")
        payload.update(raw_character_span=tuple(raw_span) if raw_span is not None else None, unicode_codepoint=finding.get("unicode_codepoint"), location_resolution=finding.get("location_resolution"))
        if finding.get("location_resolution") == "character_bbox" and box is not None:
            payload["bbox_normalized"] = tuple(box)
        record = DeepDocGlyphFinding("finding:" + _fingerprint(payload), **payload)
        records[record.id] = record
    return tuple(records[key] for key in sorted(records))


def _package_version(package):
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _read_blocks(source):
    executable = os.environ.get("PDFTOTEXT_EXECUTABLE") or shutil.which("pdftotext")
    if not executable:
        raise RuntimeError("Plain Text canonical ingestion requires Poppler pdftotext; install poppler-utils or set PDFTOTEXT_EXECUTABLE")
    try:
        version = run_bounded_process([executable, "-v"], timeout=min(10, source.check_deadline()), output_limit=65536)
        match = re.search(r"pdftotext version\s+(\S+)", (version.stderr + version.stdout).decode("utf-8", errors="replace"))
        if match is None:
            raise RuntimeError("cannot determine the pdftotext version")
        result = run_bounded_process(
            [executable, "-bbox-layout", "-cropbox", "-enc", "UTF-8", "-", "-"], input=source.data, timeout=source.check_deadline(), output_limit=source.policy.max_subprocess_output_bytes
        )
    except subprocess.CalledProcessError as exc:
        raise ValueError("native PDF text extraction failed: " + (exc.stderr.decode("utf-8", errors="replace")[:1000] if exc.stderr else str(exc))) from exc
    except subprocess.TimeoutExpired as exc:
        raise PdfAdmissionError("PDF_SUBPROCESS_TIMEOUT", "Native PDF text extraction timed out") from exc
    except OSError as exc:
        raise RuntimeError(f"cannot run pdftotext: {exc}") from exc
    layout = _PdfLayoutParser()
    layout.feed(result.stdout.decode("utf-8"))
    layout.close()
    if len(layout.stack) != 1:
        raise ValueError("pdftotext returned incomplete layout markup")
    pages = layout.root.findall(".//page")
    if not pages:
        raise ValueError("pdftotext returned no PDF pages")
    if len(pages) != len(source.geometry):
        raise PdfAdmissionError("PDF_BACKEND_PAGE_MISMATCH", "Native text page count does not match admission")
    blocks = []
    words, line_spans = [], []
    for page, node in enumerate(pages, start=1):
        source.check_deadline()
        try:
            width, height = poppler_display_size(float(node.attrib["width"]), float(node.attrib["height"]), source.geometry[page])
        except ValueError as exc:
            raise PdfAdmissionError("PDF_BACKEND_GEOMETRY_MISMATCH", "Native text geometry does not match visible page frame", page=page) from exc
        for index, block in enumerate(node.findall(".//block")):
            lines = tuple(" ".join("".join(word.itertext()) for word in line.findall("word")) for line in block.findall("line"))
            text = "\n".join(lines)
            if not text.strip():
                continue
            box = tuple(float(block.attrib[key]) for key in ("xmin", "ymin", "xmax", "ymax"))
            line_boxes = tuple(
                tuple(float(line.attrib[key]) for key in ("xmin", "ymin", "xmax", "ymax")) if all(key in line.attrib for key in ("xmin", "ymin", "xmax", "ymax")) else None
                for line in block.findall("line")
            )
            blocks.append(GlyphTextBlock(page, index, f"pdf:text:{page}:{index}", text, width, height, lines, line_boxes, box))
            source_id = blocks[-1].source_id
            offset = 0
            for line, value, line_box in zip(block.findall("line"), lines, line_boxes, strict=True):
                if value and line_box is not None:
                    line_spans.append((source_id, offset, offset + len(value), value, DeepDocSourceLocation(page, width, height, DeepDocBoundingBox(*line_box))))
                cursor = offset
                for word in line.findall("word"):
                    value = "".join(word.itertext())
                    if value and all(key in word.attrib for key in ("xmin", "ymin", "xmax", "ymax")):
                        word_box = DeepDocBoundingBox(*(float(word.attrib[key]) for key in ("xmin", "ymin", "xmax", "ymax")))
                        words.append((source_id, cursor, cursor + len(value), value, DeepDocSourceLocation(page, width, height, word_box)))
                    cursor += len(value) + 1
                offset += len(" ".join("".join(word.itertext()) for word in line.findall("word"))) + 1
    return DeepDocProducer("poppler-pdftotext", match.group(1)), tuple(blocks), tuple(words), tuple(line_spans)


class _PdfLayoutParser(HTMLParser):
    """Preserve Poppler word text, including source control characters."""

    _tags = frozenset({"doc", "page", "flow", "block", "line", "word"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = ET.Element("layout")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        if tag in self._tags:
            element = ET.SubElement(self.stack[-1], tag, {key: value for key, value in attrs if value is not None})
            self.stack.append(element)

    def handle_endtag(self, tag):
        if tag in self._tags:
            if len(self.stack) == 1 or self.stack[-1].tag != tag:
                raise ValueError("pdftotext returned inconsistent layout markup")
            self.stack.pop()

    def handle_data(self, data):
        if self.stack[-1].tag == "word":
            self.stack[-1].text = (self.stack[-1].text or "") + data

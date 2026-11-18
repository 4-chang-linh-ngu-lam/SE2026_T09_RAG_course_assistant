"""Attribute glyph/font findings to the native text regions they can affect.

Until ``pdf-quality-gate:3`` every finding without a region was applied to
*every* region of its page. One unaligned TeX delimiter glyph or one font
resource whose ``negationslash`` code extracts as ``6`` therefore withheld a
whole page of correctly extracted prose (benchmark ``ban_chinh_sua_final``:
77 pages with substantial native text and no publishable block).

The narrowing here is conservative and purely textual/geometric:

* a region finding affects its region;
* a font-resource finding names the character it mis-extracts (the decoded
  operand text, the ToUnicode value, or the one-byte code itself). Only a
  native block whose *raw* text contains one of those strings can hold that
  glyph, so only those blocks are affected. When no block contains any of
  them the glyph could not be located and the finding stays page-wide;
* a code use the inspector itself VERIFIED (same page and content-stream
  position) is not suspect any more;
* a page finding with no character or region identity stays page-wide;
* findings that only report secondary-backend coverage outside every native
  block never change any native block's text and affect no region.

``None`` as a target means "cannot narrow": the caller keeps the previous
page-wide (or document-wide when the finding has no page) behaviour.
"""

from __future__ import annotations

SUSPECT_STATUSES = frozenset({"SUSPECT", "CONFLICT"})
# Secondary characters outside every native block: a completeness signal for
# that area, not evidence that any native block's text is wrong.
NON_GATING_CODES = frozenset(
    {"PDF_SECONDARY_TEXT_OUTSIDE_NATIVE_BLOCKS", "PDF_PAGE_WITHOUT_NATIVE_TEXT"}
)


def _code_use_key(finding):
    positions = (finding.operator_index, finding.string_index, finding.code_index)
    if finding.page is None or any(value is None for value in positions):
        return None
    return (finding.page, finding.resource_scope, *positions)


def _extracted_forms(finding):
    """Strings the mis-mapped glyph can appear as in native text."""
    forms = {finding.raw_extracted_text, finding.unicode_mapping}
    code = finding.character_code_hex
    if code and len(code) <= 2:
        try:
            forms.add(chr(int(code, 16)))
        except ValueError:
            pass
    return {form for form in forms if form}


def finding_targets(findings, texts_by_page):
    """Map finding id -> frozenset of affected source ids, or None.

    ``texts_by_page`` maps page -> iterable of ``(source_id, raw_text)`` for
    the native text regions on that page.
    """
    verified = {
        key
        for finding in findings
        if finding.status == "VERIFIED"
        for key in (_code_use_key(finding),)
        if key is not None
    }
    targets = {}
    for finding in findings:
        if finding.status not in SUSPECT_STATUSES or finding.code in NON_GATING_CODES:
            targets[finding.id] = frozenset()
            continue
        if finding.scope == "REGION" and finding.source_id:
            targets[finding.id] = frozenset({finding.source_id})
            continue
        key = _code_use_key(finding)
        if key is not None and key in verified:
            targets[finding.id] = frozenset()
            continue
        forms = _extracted_forms(finding)
        if finding.page is None or not forms:
            targets[finding.id] = None
            continue
        hits = frozenset(
            source_id
            for source_id, text in texts_by_page.get(finding.page, ())
            if any(form in (text or "") for form in forms)
        )
        targets[finding.id] = hits or None
    return targets

"""Recover TeX math glyphs that text extractors read as their byte code.

TeX math fonts (Computer Modern / Latin Modern ``cmsy``/``cmex``/``cmmi``,
``LMMathSymbols``, ``LMMathExtension`` ...) are usually embedded without a
ToUnicode map. Their ``/Encoding /Differences`` names every glyph
(``/prime``, ``/integraltext``, ``/parenleftbigg``), but these TeX names are
not in the glyph lists Poppler and PDFium use, so both fall back to the raw
byte: ``h′(t)`` becomes ``h0(t)``, ``∫`` becomes ``Z`` and a big parenthesis
becomes the control character ``\\x12`` (benchmark ``ban_chinh_sua_final``).

The font's own Differences entry is the source evidence: for a fixed font
code it names the glyph that is drawn. A correction is proposed only when

* the PDFium character's font resolves to exactly one encoding on the page,
  the Differences glyph of ``ord(text)`` is a known TeX name, and PDFium's
  text is that byte fallback (so the extractor did not already map it);
* its geometry selects exactly one Poppler word that contains the fallback
  character, and that word holds as many fallback characters as aligned
  TeX glyphs (ordered left to right).

Anything else is reported as a region finding on the blocks that may hold
the misread glyph, which keeps those blocks out of publication instead of
publishing ``0`` for a prime.
"""

from __future__ import annotations

from collections import defaultdict

from idp.evidence.contracts import DeepDocGlyphNameProof
from idp.pdf.native.glyph.repair import VerifiedFontGlyphCorrection

METHOD = "font_differences_tex_glyph_name"

_SIZES = ("", "big", "Big", "bigg", "Bigg", "text", "display")


def _sized(base, value):
    return {base + size: value for size in _SIZES}


# TeX glyph names (Computer Modern / Latin Modern math encodings) that are
# missing from the Adobe Glyph List extractors use. Multi-piece extension
# parts (``parenlefttp``/``bt``/``ex``, ``braceex``, ``radicalvertex``) are
# deliberately absent: one printed delimiter is drawn from several of them.
TEX_GLYPH_UNICODE = {
    # cmsy / LMMathSymbols
    "asteriskmath": "∗",
    "diamondmath": "⋄",
    "minusplus": "∓",
    "circleplus": "⊕",
    "circleminus": "⊖",
    "circlemultiply": "⊗",
    "circledivide": "⊘",
    "circledot": "⊙",
    "circlecopyrt": "◯",
    "openbullet": "◦",
    "equivasymptotic": "≍",
    "equivalence": "≡",
    "reflexsubset": "⊆",
    "reflexsuperset": "⊇",
    "precedesequal": "⪯",
    "followsequal": "⪰",
    "similar": "∼",
    "approxequal": "≈",
    "propersubset": "⊂",
    "propersuperset": "⊃",
    "lessmuch": "≪",
    "greatermuch": "≫",
    "precedes": "≺",
    "follows": "≻",
    "arrownortheast": "↗",
    "arrowsoutheast": "↘",
    "similarequal": "≃",
    "arrownorthwest": "↖",
    "arrowsouthwest": "↙",
    "prime": "′",
    "infinity": "∞",
    "element": "∈",
    "owner": "∋",
    "triangle": "△",
    "triangleinv": "▽",
    "mapsto": "↦",
    "universal": "∀",
    "existential": "∃",
    "emptyset": "∅",
    "Rfractur": "ℜ",
    "Ifractur": "ℑ",
    "latticetop": "⊤",
    "perpendicular": "⊥",
    "aleph": "ℵ",
    "union": "∪",
    "intersection": "∩",
    "unionmulti": "⊎",
    "logicaland": "∧",
    "logicalor": "∨",
    "turnstileleft": "⊢",
    "turnstileright": "⊣",
    "floorleft": "⌊",
    "floorright": "⌋",
    "ceilingleft": "⌈",
    "ceilingright": "⌉",
    "angbracketleft": "⟨",
    "angbracketright": "⟩",
    "bar": "|",
    "bardbl": "‖",
    "arrowbothv": "↕",
    "arrowdblbothv": "⇕",
    "wreathproduct": "≀",
    "radical": "√",
    "coproduct": "∐",
    "nabla": "∇",
    "unionsq": "⊔",
    "intersectionsq": "⊓",
    "subsetsqequal": "⊑",
    "supersetsqequal": "⊒",
    "arrowdblleft": "⇐",
    "arrowdblright": "⇒",
    "arrowdblup": "⇑",
    "arrowdbldown": "⇓",
    "arrowdblboth": "⇔",
    "arrowboth": "↔",
    "proportional": "∝",
    # cmmi / LMMathItalic variants
    "epsilon1": "ϵ",
    "theta1": "ϑ",
    "pi1": "ϖ",
    "rho1": "ϱ",
    "sigma1": "ς",
    "phi1": "φ",
    "star": "⋆",
    "triangleright": "▷",
    "triangleleft": "◁",
    "dotlessj": "ȷ",
    "flat": "♭",
    "natural": "♮",
    "sharp": "♯",
    # cmex / LMMathExtension: sized delimiters and operators
    **_sized("parenleft", "("),
    **_sized("parenright", ")"),
    **_sized("bracketleft", "["),
    **_sized("bracketright", "]"),
    **_sized("braceleft", "{"),
    **_sized("braceright", "}"),
    **_sized("floorleft", "⌊"),
    **_sized("floorright", "⌋"),
    **_sized("ceilingleft", "⌈"),
    **_sized("ceilingright", "⌉"),
    **_sized("angbracketleft", "⟨"),
    **_sized("angbracketright", "⟩"),
    **_sized("slash", "/"),
    **_sized("backslash", "\\"),
    **_sized("radical", "√"),
    **_sized("integral", "∫"),
    **_sized("contintegral", "∮"),
    **_sized("summation", "∑"),
    **_sized("product", "∏"),
    **_sized("coproduct", "∐"),
    **_sized("union", "⋃"),
    **_sized("intersection", "⋂"),
    **_sized("unionmulti", "⨄"),
    **_sized("unionsq", "⨆"),
    **_sized("logicaland", "⋀"),
    **_sized("logicalor", "⋁"),
    **_sized("circleplus", "⨁"),
    **_sized("circlemultiply", "⨂"),
    **_sized("circledot", "⨀"),
    "vextendsingle": "|",
    "vextenddouble": "‖",
}
# The plain AGL-name forms of a few sized entries above (``integral``,
# ``union``...) are mapped by extractors already; only fallbacks are edited.


def tex_glyph(name):
    """Unicode for a TeX glyph name, or None for names outside the table."""
    if not name:
        return None
    return TEX_GLYPH_UNICODE.get(name.lstrip("/"))


def tex_font_pages(reader):
    """Pages whose fonts name a TeX glyph in their Differences (font scan only)."""
    from idp.pdf.native.glyph.inspector import _encoding_differences

    found = set()
    seen = {}
    for number, page in enumerate(reader.pages, start=1):
        try:
            fonts = page.get("/Resources").get_object().get("/Font").get_object()
        except AttributeError:
            continue
        for reference in fonts.values():
            key = (reference.idnum, reference.generation) if hasattr(reference, "idnum") else None
            if key is not None and key in seen:
                hit = seen[key]
            else:
                font = reference.get_object()
                encoding = font.get("/Encoding") if hasattr(font, "get") else None
                encoding = encoding.get_object() if hasattr(encoding, "get_object") else encoding
                hit = any(tex_glyph(name) for _, name in _encoding_differences(encoding))
                if key is not None:
                    seen[key] = hit
            if hit:
                found.add(number)
                break
    return found


def _font_for_char(page_fonts, font_name, code):
    """The single Differences glyph name PDFium's font name selects, or None."""
    from idp.pdf.native.glyph.inspector import normalized_font_name

    name = normalized_font_name(font_name)
    matches = [font for font in page_fonts if font.normalized_base_font == name]
    glyphs = {font.difference_map.get(code) for font in matches}
    if len(glyphs) != 1:
        return None, None
    glyph = next(iter(glyphs))
    if not tex_glyph(glyph):
        return None, None
    fingerprints = {font.font_fingerprint for font in matches}
    if len(fingerprints) != 1:
        return None, None
    return matches[0], glyph


def _inside(box, x, y, tolerance=0.002):
    return box[0] - tolerance <= x <= box[2] + tolerance and box[1] - tolerance <= y <= box[3] + tolerance


def _intersects(a, b):
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def propose_tex_glyph_corrections(pdf_sha256, fonts, pages_chars, blocks, words):
    """Return ``(corrections, findings)`` for TeX glyphs read as byte codes.

    ``fonts``: inspected ``PdfFontMetadata``; ``pages_chars``: page -> PDFium
    characters; ``blocks``: Poppler ``GlyphTextBlock``; ``words``: Poppler
    word spans ``(source_id, start, end, text, location)``.
    """
    fonts_by_page = defaultdict(list)
    for font in fonts:
        fonts_by_page[font.page].append(font)
    block_by_id = {block.source_id: block for block in blocks}
    words_by_page = defaultdict(list)
    for source_id, start, end, text, location in words:
        if location.bbox is None:
            continue
        b = location.bbox
        box = (b.x0 / location.page_width, b.y0 / location.page_height, b.x1 / location.page_width, b.y1 / location.page_height)
        words_by_page[location.page].append((source_id, start, end, text, box))
    blocks_by_page = defaultdict(list)
    for block in blocks:
        if block.bbox:
            box = (block.bbox[0] / block.page_width, block.bbox[1] / block.page_height, block.bbox[2] / block.page_width, block.bbox[3] / block.page_height)
            blocks_by_page[block.page].append((block.source_id, box))
    corrections, findings = [], []
    for page in sorted(pages_chars):
        assigned = defaultdict(list)  # word key -> [(char, font, glyph)]
        unresolved = defaultdict(list)  # source_id -> [glyph]
        for char in pages_chars[page]:
            if len(char.text) != 1 or char.bbox is None:
                continue
            code = ord(char.text)
            if code > 0xFF:
                continue
            font, glyph = _font_for_char(fonts_by_page[page], char.font_name, code)
            if font is None:
                continue
            x, y = (char.bbox[0] + char.bbox[2]) / 2, (char.bbox[1] + char.bbox[3]) / 2
            candidates = [w for w in words_by_page[page] if char.text in w[3] and _inside(w[4], x, y)]
            if not candidates:
                candidates = [w for w in words_by_page[page] if char.text in w[3] and _intersects(w[4], char.bbox)]
            if len(candidates) == 1:
                word = candidates[0]
                assigned[word[:3]].append((char, font, glyph, word))
                continue
            owners = {w[0] for w in candidates} or {
                source_id for source_id, box in blocks_by_page[page] if _intersects(box, char.bbox)
            }
            for source_id in owners:
                unresolved[source_id].append(glyph)
        by_block = defaultdict(lambda: {"spans": [], "evidence": [], "fingerprints": set()})
        for (source_id, start, _end), items in assigned.items():
            word_text, word_box = items[0][3][3], items[0][3][4]
            ok = True
            planned = []
            # Exact path: PDFium characters inside the word, left to right,
            # spell the Poppler word, so every TeX glyph has its own index.
            inside = sorted(
                (
                    c
                    for c in pages_chars[page]
                    if c.bbox is not None
                    and not c.text.isspace()
                    and _inside(word_box, (c.bbox[0] + c.bbox[2]) / 2, (c.bbox[1] + c.bbox[3]) / 2)
                ),
                key=lambda c: ((c.bbox[0] + c.bbox[2]) / 2, c.index),
            )
            if "".join(c.text for c in inside) == word_text:
                index = {id(c): i for i, c in enumerate(inside)}
                if all(id(item[0]) in index for item in items):
                    planned = [(index[id(item[0])], item) for item in items]
                    items = []
            for fallback in {item[0].text for item in items}:
                group = sorted((item for item in items if item[0].text == fallback), key=lambda item: item[0].bbox[0])
                positions = [index for index, value in enumerate(word_text) if value == fallback]
                if len(positions) != len(group):
                    ok = False
                    break
                planned.extend(zip(positions, group))
            if not ok:
                unresolved[source_id].extend(item[2] for item in items)
                continue
            target = by_block[source_id]
            for position, (char, font, glyph, _word) in planned:
                replacement = tex_glyph(glyph)
                target["spans"].append((start + position, start + position + 1, char.text, replacement))
                target["fingerprints"].add(font.font_fingerprint)
                target["evidence"].append(
                    DeepDocGlyphNameProof(
                        page=page,
                        font_fingerprint=font.font_fingerprint,
                        base_font=font.normalized_base_font or "",
                        glyph_name=glyph if glyph.startswith("/") else "/" + glyph,
                        character_code_hex=f"{ord(char.text):02X}",
                        extracted_text=char.text,
                        replacement=replacement,
                        glyph_bbox_normalized=tuple(char.bbox),
                    )
                )
        for source_id, item in sorted(by_block.items()):
            if source_id in unresolved:
                continue
            block = block_by_id[source_id]
            order = sorted(range(len(item["spans"])), key=lambda i: item["spans"][i][0])
            corrections.append(
                VerifiedFontGlyphCorrection(
                    pdf_sha256=pdf_sha256,
                    page=page,
                    block=block.block,
                    original_text=block.text,
                    spans=tuple(item["spans"][i] for i in order),
                    font_fingerprints=tuple(sorted(item["fingerprints"])),
                    evidence=tuple(item["evidence"][i] for i in order),
                    method=METHOD,
                )
            )
            findings.append(
                {
                    "code": "PDF_TEX_GLYPH_NAME_RECOVERED",
                    "status": "VERIFIED",
                    "page": page,
                    "source_id": source_id,
                    "reason": f"{len(item['spans'])} TeX glyphs read as their byte code were mapped by the font's Differences glyph names",
                }
            )
        for source_id, glyphs in sorted(unresolved.items()):
            findings.append(
                {
                    "code": "PDF_TEX_GLYPH_NAME_UNRESOLVED",
                    "status": "SUSPECT",
                    "page": page,
                    "source_id": source_id,
                    "glyph_name": sorted(glyphs)[0],
                    "reason": f"{len(glyphs)} TeX glyphs ({', '.join(sorted(set(glyphs))[:5])}) are extracted as byte codes and could not be located exactly in this block",
                }
            )
    return corrections, findings

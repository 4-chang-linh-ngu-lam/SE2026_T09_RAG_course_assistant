"""Level 0 native DOCX backend using Pandoc AST (OMML -> LaTeX, tables, media)."""

from __future__ import annotations

import html
import json
import re
import zipfile
from pathlib import Path

from idp.backends.native.pdf import make_block, make_page


def _pandoc_json_file(path: Path, assets: Path):
    try:
        import pypandoc
    except ImportError as exc:
        raise RuntimeError(
            "DOCX requires pypandoc/pandoc (`pip install pypandoc_binary` or system pandoc)."
        ) from exc
    assets.mkdir(parents=True, exist_ok=True)
    raw = pypandoc.convert_file(
        str(path),
        "json",
        format="docx",
        extra_args=[f"--extract-media={assets}"],
    )
    return json.loads(raw)


def pandoc_json_text(text: str):
    try:
        import pypandoc
    except ImportError:
        return None
    try:
        return json.loads(
            pypandoc.convert_text(
                text,
                "json",
                format="markdown+pipe_tables+tex_math_dollars",
            )
        )
    except Exception:
        return None


def _asset_path(assets: Path, target: str) -> Path | None:
    if not target:
        return None
    candidate = Path(target)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    candidates = [
        assets / target,
        assets / candidate.name,
        assets / "media" / candidate.name,
    ]
    if target.startswith("/c/"):
        candidates.append(Path("C:/" + target[3:]))
    for p in candidates:
        if p.exists():
            return p
    return None


def _inlines_text(inlines) -> str:
    out = []
    for node in inlines or []:
        t = node.get("t")
        c = node.get("c")
        if t == "Str":
            out.append(str(c))
        elif t == "Space":
            out.append(" ")
        elif t in {"SoftBreak", "LineBreak"}:
            out.append("\n" if t == "LineBreak" else " ")
        elif t in {"Emph", "Strong", "Strikeout", "Superscript", "Subscript", "SmallCaps", "Quoted"}:
            out.append(_inlines_text(c[1] if t == "Quoted" else c))
        elif t == "Code":
            out.append(str(c[1]) if isinstance(c, list) and len(c) > 1 else str(c))
        elif t == "Math":
            out.append("$" + str(c[1]) + "$")
        elif t in {"Link", "Image"}:
            out.append(_inlines_text(c[1]))
        elif t == "Note":
            out.append(_blocks_text(c))
    return "".join(out)


def _inlines_md(inlines, assets: Path, latex: list, images: list) -> str:
    out = []
    for node in inlines or []:
        t = node.get("t")
        c = node.get("c")
        if t == "Str":
            out.append(str(c))
        elif t == "Space":
            out.append(" ")
        elif t == "SoftBreak":
            out.append(" ")
        elif t == "LineBreak":
            out.append("\n")
        elif t == "Emph":
            out.append("*" + _inlines_md(c, assets, latex, images) + "*")
        elif t == "Strong":
            out.append("**" + _inlines_md(c, assets, latex, images) + "**")
        elif t == "Strikeout":
            out.append("~~" + _inlines_md(c, assets, latex, images) + "~~")
        elif t == "Superscript":
            out.append("^" + _inlines_md(c, assets, latex, images) + "^")
        elif t == "Subscript":
            out.append("~" + _inlines_md(c, assets, latex, images) + "~")
        elif t == "Code":
            out.append("`" + str(c[1]) + "`")
        elif t == "Math":
            tex = str(c[1])
            latex.append(tex)
            out.append(("$$" + tex + "$$") if c[0].get("t") == "DisplayMath" else ("$" + tex + "$"))
        elif t == "Link":
            out.append("[" + _inlines_md(c[1], assets, latex, images) + "](" + str(c[2][0]) + ")")
        elif t == "Image":
            target = str(c[2][0])
            asset = _asset_path(assets, target)
            if asset:
                images.append((str(asset), _inlines_text(c[1])))
            out.append("![" + _inlines_text(c[1]) + "](" + target + ")")
        elif t == "Quoted":
            out.append("“" + _inlines_md(c[1], assets, latex, images) + "”")
        elif t == "Note":
            out.append(_blocks_md(c, assets, latex, images))
    return "".join(out)


def _blocks_text(blocks) -> str:
    out = []
    for b in blocks or []:
        t = b.get("t")
        c = b.get("c")
        if t in {"Para", "Plain"}:
            out.append(_inlines_text(c))
        elif t == "Header":
            out.append(_inlines_text(c[2]))
        elif t == "CodeBlock":
            out.append(str(c[1]))
        elif t == "BlockQuote":
            out.append(_blocks_text(c))
        elif t == "Table":
            out.append(_table_text(c))
        elif t in {"BulletList", "OrderedList"}:
            items = c[1] if t == "OrderedList" else c
            out.append("\n".join(_blocks_text(x) for x in items))
        elif t == "Figure":
            out.append(_blocks_text(c[1]) + "\n" + _blocks_text(c[2]))
    return "\n".join(x for x in out if x.strip())


def _blocks_md(blocks, assets: Path, latex: list, images: list) -> str:
    out = []
    for b in blocks or []:
        t = b.get("t")
        c = b.get("c")
        if t in {"Para", "Plain"}:
            out.append(_inlines_md(c, assets, latex, images))
        elif t == "Header":
            out.append("#" * min(6, int(c[0])) + " " + _inlines_md(c[2], assets, latex, images))
        elif t == "CodeBlock":
            out.append("```\n" + str(c[1]) + "\n```")
        elif t == "BlockQuote":
            out.append("> " + _blocks_md(c, assets, latex, images).replace("\n", "\n> "))
        elif t == "Table":
            out.append(_table_html(c, assets, latex, images))
        elif t in {"BulletList", "OrderedList"}:
            items = c[1] if t == "OrderedList" else c
            for idx, item in enumerate(items, 1):
                prefix = f"{idx}. " if t == "OrderedList" else "- "
                out.append(prefix + _blocks_md(item, assets, latex, images).replace("\n", "\n  "))
        elif t == "Figure":
            cap = _blocks_md(c[1], assets, latex, images)
            body = _blocks_md(c[2], assets, latex, images)
            out.append((cap + "\n" + body).strip())
    return "\n\n".join(x for x in out if x.strip())


def _table_text(tbl) -> str:
    _, caption, _, head, bodies, foot = tbl
    rows = []
    if head and head[1]:
        rows.extend(head[1])
    for body in bodies or []:
        rows.extend(body[3])
    if foot and foot[1]:
        rows.extend(foot[1])
    text_rows = []
    for row in rows:
        cells = [_blocks_text(cell[4]) for cell in row[1]]
        text_rows.append(" | ".join(cells))
    cap = _blocks_text(caption[1]) if caption and len(caption) > 1 else ""
    return (cap + "\n" + "\n".join(text_rows)).strip()


def _table_html(tbl, assets: Path, latex: list, images: list) -> str:
    _, caption, _colspecs, head, bodies, foot = tbl
    rows = []
    if head and head[1]:
        rows.append(("head", head[1]))
    for body in bodies or []:
        if body[2]:
            rows.append(("head", body[2]))
        rows.append(("body", body[3]))
    if foot and foot[1]:
        rows.append(("body", foot[1]))

    out = ["<table>"]
    cap = _blocks_text(caption[1]) if caption and len(caption) > 1 else ""
    if cap:
        out.append(f"<caption>{html.escape(cap)}</caption>")
    for section, section_rows in rows:
        if section == "head":
            out.append("<thead>")
        elif section == "body" and (not out or out[-1] != "<tbody>"):
            out.append("<tbody>")
        for row in section_rows:
            out.append("<tr>")
            for cell in row[1]:
                _, align, rowspan, colspan, cell_blocks = cell
                tag = "th" if section == "head" else "td"
                attrs = []
                if align and align.get("t") == "AlignCenter":
                    attrs.append('style="text-align:center"')
                if align and align.get("t") == "AlignRight":
                    attrs.append('style="text-align:right"')
                if int(rowspan) > 1:
                    attrs.append(f'rowspan="{int(rowspan)}"')
                if int(colspan) > 1:
                    attrs.append(f'colspan="{int(colspan)}"')
                _blocks_md(cell_blocks, assets, latex, images)
                plain_cell = _blocks_text(cell_blocks)
                cell_html = html.escape(plain_cell).replace("\n", "<br/>")
                attr_str = f" {' '.join(attrs)}" if attrs else ""
                out.append(f"<{tag}{attr_str}>{cell_html}</{tag}>")
            out.append("</tr>")
        out.append("</thead>" if section == "head" else "</tbody>")
    out.append("</table>")
    return "".join(out)


def _is_strong_para(inlines) -> bool:
    meaningful = [
        x for x in (inlines or [])
        if x.get("t") not in {"Space", "SoftBreak", "LineBreak"}
    ]
    return bool(meaningful) and all(x.get("t") == "Strong" for x in meaningful)


def ast_to_blocks(ast_blocks, assets: Path) -> list[dict]:
    blocks: list[dict] = []
    section_stack: list[tuple[int, str]] = []
    section_path: list[str] = []

    def add(block_type, text="", markdown=None, latex=None, images=None, flags=None, bbox=None):
        block = make_block(
            f"b{len(blocks):04d}",
            block_type,
            bbox,
            text,
            markdown if markdown is not None else text,
            latex=latex or [],
            asset_paths=images or [],
            section_path=list(section_path),
            review_flags=flags or [],
        )
        block["order"] = len(blocks)
        blocks.append(block)

    def walk(nodes):
        for node in nodes or []:
            t = node.get("t")
            c = node.get("c")
            if t == "Header":
                level = int(c[0])
                text = _inlines_text(c[2])
                tex, imgs = [], []
                md = _inlines_md(c[2], assets, tex, imgs)
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                section_stack.append((level, text))
                section_path[:] = [x[1] for x in section_stack]
                add("SectionHeader", text, "#" * min(6, level) + " " + md, latex=tex, images=[x[0] for x in imgs])
            elif t in {"Para", "Plain"}:
                tex, imgs = [], []
                md = _inlines_md(c, assets, tex, imgs)
                text = _inlines_text(c)
                cap_heading = text.strip().isupper() and len(text.strip()) <= 90
                if (_is_strong_para(c) and len(text.strip()) <= 180) or cap_heading:
                    level = 2
                    while section_stack and section_stack[-1][0] >= level:
                        section_stack.pop()
                    section_stack.append((level, text.strip()))
                    section_path[:] = [x[1] for x in section_stack]
                    add("SectionHeader", text.strip(), "## " + md.strip(), latex=tex, images=[x[0] for x in imgs])
                    continue
                if text.strip():
                    add("Text", text, md, latex=tex, images=[x[0] for x in imgs])
                for asset, alt in imgs:
                    flags = []
                    if not alt.strip():
                        flags.append({
                            "block_id": f"b{len(blocks):04d}",
                            "code": "FIGURE_CAPTION_REVIEW",
                            "severity": "warning",
                        })
                    add("Picture", alt, f"![{alt}]({Path(asset).as_posix()})", images=[asset], flags=flags)
            elif t == "Table":
                tex, imgs = [], []
                table_html = _table_html(c, assets, tex, imgs)
                table_text = _table_text(c)
                merged = "rowspan=" in table_html or "colspan=" in table_html
                flags = [{
                    "block_id": f"b{len(blocks):04d}",
                    "code": "TABLE_MERGED_CELLS",
                    "severity": "warning",
                }] if merged else []
                add("Table", table_text, table_html, latex=tex, images=[x[0] for x in imgs], flags=flags)
            elif t in {"BulletList", "OrderedList"}:
                items = c[1] if t == "OrderedList" else c
                text = "\n".join(_blocks_text(item) for item in items)
                tex, imgs = [], []
                md = _blocks_md([node], assets, tex, imgs)
                if text.strip():
                    add("Text", text, md, latex=tex, images=[x[0] for x in imgs])
            elif t == "Figure":
                cap = _blocks_text(c[1])
                tex, imgs = [], []
                _blocks_md(c[2], assets, tex, imgs)
                if imgs:
                    for asset, alt in imgs:
                        add(
                            "Picture",
                            cap or alt,
                            f"![{cap or alt}]({Path(asset).as_posix()})",
                            images=[asset],
                            flags=[] if cap else [{
                                "block_id": f"b{len(blocks):04d}",
                                "code": "FIGURE_CAPTION_REVIEW",
                                "severity": "warning",
                            }],
                        )
                elif cap.strip():
                    add("Text", cap, cap)
            elif t == "Div":
                walk(c[1])
            elif t == "BlockQuote":
                text = _blocks_text(c)
                tex, imgs = [], []
                md = _blocks_md(c, assets, tex, imgs)
                if text.strip():
                    add("Text", text, "> " + md, latex=tex, images=[x[0] for x in imgs])
            elif t == "CodeBlock":
                text = str(c[1])
                add("Text", text, "```\n" + text + "\n```")

    walk(ast_blocks)
    return blocks


def docx_source_audit(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        xml = z.read("word/document.xml").decode("utf-8", "replace")
        app = z.read("docProps/app.xml").decode("utf-8", "replace") if "docProps/app.xml" in names else ""
    media = [n for n in names if n.startswith("word/media/")]
    equations = len(re.findall(r"<m:oMath(?:>|\s)", xml))
    tables = xml.count("<w:tbl>")
    textboxes = xml.count("<w:txbxContent")
    charts = sum(1 for n in names if n.startswith("word/charts/")) + xml.count("<c:chart")
    ole = xml.count("<o:OLEObject")
    smartart = sum(1 for n in names if n.startswith("word/diagrams/"))
    comments = "word/comments.xml" in names
    tracked = xml.count("<w:ins ") + xml.count("<w:del ")
    headers = [n for n in names if n.startswith("word/header")]
    footers = [n for n in names if n.startswith("word/footer")]
    m = re.search(r"<Pages>(\d+)</Pages>", app)
    unsupported = []
    for part_name, count in (
        ("textboxes", textboxes),
        ("charts", charts),
        ("ole_objects", ole),
        ("smartart", smartart),
        ("comments", 1 if comments else 0),
        ("tracked_changes", tracked),
    ):
        if count:
            unsupported.append({"part": part_name, "count": count})
    return {
        "tables": tables,
        "equations": equations,
        "media": len(media),
        "textboxes": textboxes,
        "charts": charts,
        "ole_objects": ole,
        "smartart": smartart,
        "comments": comments,
        "tracked_changes": tracked,
        "headers": len(headers),
        "footers": len(footers),
        "declared_pages": int(m.group(1)) if m else None,
        "unsupported_parts": unsupported,
    }


def extract_docx_pages(path: Path, assets: Path) -> tuple[list[dict], dict]:
    ast = _pandoc_json_file(path, assets)
    blocks = ast_to_blocks(ast.get("blocks", []), assets)
    return [make_page(1, blocks, None, page_number=1)], docx_source_audit(path)

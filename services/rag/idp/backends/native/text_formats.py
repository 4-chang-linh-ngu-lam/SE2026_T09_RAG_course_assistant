"""Level 0 native text, Markdown, HTML, and Email extraction backends."""

from __future__ import annotations

import email
import html
import re
from email import policy
from html.parser import HTMLParser
from pathlib import Path

from idp.backends.native.docx import ast_to_blocks, pandoc_json_text
from idp.backends.native.pdf import make_block, make_page
from idp.input.validation import InputError
from idp.processing.formula import normalize_text
from idp.processing.table import rows_to_html


def decode_txt(path: Path) -> tuple[str, str | None]:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16"), "utf-16"
    for enc in ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def _strip_html(value: str) -> str:
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _copy_asset(assets: Path, source_dir: Path, src: str, prefix: str) -> str | None:
    if not src or src.startswith(("http://", "https://", "data:")):
        return None
    path = Path(src)
    source_root = source_dir.resolve()
    if path.is_absolute():
        return None
    path = (source_root / path).resolve()
    if not path.is_relative_to(source_root):
        return None
    if not path.exists() or not path.is_file():
        return None
    suffix = path.suffix.lower() or ".bin"
    target = assets / f"{prefix}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(path.read_bytes())
    return str(target)


def _md_plain(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def txt_pages(path: Path, assets: Path) -> list[dict]:
    text, _ = decode_txt(path)
    ast = pandoc_json_text(text)
    if ast is not None:
        blocks = ast_to_blocks(ast.get("blocks", []), assets)
        return [make_page(1, blocks, None, page_number=1)]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    blocks = []
    for idx, p in enumerate(paragraphs):
        bid = f"p0001_b{idx:03d}"
        is_heading = len(p) <= 90 and (p.isupper() or p.endswith(":"))
        btype = "SectionHeader" if is_heading else "Text"
        md = f"# {p}" if btype == "SectionHeader" else p
        blocks.append(make_block(bid, btype, None, p, md))
    return [make_page(1, blocks, None, page_number=1)]


def md_pages(path: Path, assets: Path, profile: str) -> list[dict]:
    text, _ = decode_txt(path)
    lines = text.splitlines()
    blocks: list[dict] = []
    section_path: list[str] = []

    def add(btype: str, plain: str, md: str, **kwargs) -> None:
        blocks.append(
            make_block(
                f"p0001_b{len(blocks):03d}",
                btype,
                None,
                normalize_text(plain, profile)[0],
                md,
                **kwargs,
            )
        )

    idx = 0
    while idx < len(lines):
        stripped = lines[idx].strip()
        if stripped.startswith("```"):
            idx += 1
            code = []
            while idx < len(lines) and not lines[idx].strip().startswith("```"):
                code.append(lines[idx])
                idx += 1
            idx += 1
            body = "\n".join(code)
            add("Text", body, "```\n" + body + "\n```")
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = _md_plain(heading.group(2))
            section_path[:] = section_path[: level - 1]
            section_path.append(title)
            blocks.append(
                make_block(
                    f"p0001_b{len(blocks):03d}",
                    "SectionHeader",
                    None,
                    normalize_text(title, profile)[0],
                    stripped,
                    section_path=list(section_path),
                )
            )
            idx += 1
            continue
        if stripped.startswith("|") and idx + 1 < len(lines):
            rows = []
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                cells = [_md_plain(c) for c in lines[idx].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                idx += 1
            if rows:
                table_html = rows_to_html(rows)
                table_text = " ".join(" ".join(row) for row in rows)
                block = make_block(
                    f"p0001_b{len(blocks):03d}",
                    "Table",
                    None,
                    table_text,
                    table_html,
                    section_path=list(section_path),
                )
                block["table_html"] = table_html
                blocks.append(block)
            continue
        image = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
        if image:
            alt, src = image.group(1), image.group(2).strip()
            local = _copy_asset(assets, path.parent, src, f"md_{len(blocks):03d}")
            flags = [] if local else [{"code": "IMAGE_REMOTE_OR_MISSING", "severity": "warning"}]
            add("Picture", alt, stripped, asset_paths=[local] if local else [], review_flags=flags, section_path=list(section_path))
            idx += 1
            continue
        if stripped:
            paragraphs = [stripped]
            idx += 1
            while (
                idx < len(lines)
                and lines[idx].strip()
                and not lines[idx].strip().startswith(("#", "|", "```", "!["))
            ):
                paragraphs.append(lines[idx].strip())
                idx += 1
            body = " ".join(paragraphs)
            add("Text", _md_plain(body), body, section_path=list(section_path))
            continue
        idx += 1
    return [make_page(1, blocks, None, page_number=1)]


class _HtmlCollector(HTMLParser):
    HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

    def __init__(self, assets: Path, source_dir: Path, profile: str):
        super().__init__(convert_charrefs=True)
        self.assets = assets
        self.source_dir = source_dir
        self.profile = profile
        self.blocks: list[dict] = []
        self.section_path: list[str] = []
        self.current: dict | None = None
        self.skip = 0
        self.table_rows: list[list[str]] = []
        self.table_row: list[str] | None = None
        self.table_cell: list[str] | None = None
        self.loose_text: list[str] = []

    def _flush_loose(self):
        if not self.loose_text:
            return
        text = normalize_text(" ".join(self.loose_text), self.profile)[0]
        self.loose_text = []
        if not text.strip():
            return
        self.blocks.append(
            make_block(f"p0001_b{len(self.blocks):03d}", "Text", None, text, text, section_path=list(self.section_path))
        )

    def _add(self, btype: str, text: str, md: str | None = None, **kwargs):
        self._flush_loose()
        text = normalize_text(text, self.profile)[0]
        if not text.strip() and btype not in {"Picture"}:
            return
        self.blocks.append(
            make_block(f"p0001_b{len(self.blocks):03d}", btype, None, text, md if md is not None else text, **kwargs)
        )

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_map = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
            return
        if self.skip:
            return
        if tag == "table":
            self.table_rows = []
            self.table_row = None
            self.table_cell = None
            return
        if self.table_rows is not None and tag == "tr":
            self.table_row = []
            return
        if self.table_row is not None and tag in {"td", "th"}:
            self.table_cell = []
            return
        if tag == "img":
            src = attr_map.get("src", "")
            alt = attr_map.get("alt", "")
            local = _copy_asset(self.assets, self.source_dir, src, f"html_{len(self.blocks):03d}")
            self._add(
                "Picture",
                alt,
                f"![{alt}]({src})",
                asset_paths=[local] if local else [],
                review_flags=[] if local else [{"code": "IMAGE_REMOTE_OR_MISSING", "severity": "warning"}],
            )
            return
        if self.current is not None or self.table_cell is not None:
            return
        if tag in self.HEADINGS:
            self.current = {"type": "SectionHeader", "level": self.HEADINGS[tag], "parts": []}
        elif tag in {"p", "li", "pre", "blockquote", "figcaption"}:
            self.current = {"type": "Text", "tag": tag, "parts": []}

    def handle_data(self, data):
        if self.skip:
            return
        if self.table_cell is not None:
            self.table_cell.append(data)
            return
        if self.current is not None:
            self.current["parts"].append(data)
        elif data.strip():
            self.loose_text.append(data.strip())

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "table":
            if self.table_rows:
                table_html = rows_to_html(self.table_rows)
                text = " ".join(" ".join(r) for r in self.table_rows)
                block = make_block(
                    f"p0001_b{len(self.blocks):03d}", "Table", None, text, table_html, section_path=list(self.section_path)
                )
                block["table_html"] = table_html
                self.blocks.append(block)
            self.table_rows = []
            return
        if tag == "tr" and self.table_row is not None:
            if self.table_row:
                self.table_rows.append(self.table_row)
            self.table_row = None
            return
        if tag in {"td", "th"} and self.table_cell is not None:
            if self.table_row is not None:
                self.table_row.append(" ".join(self.table_cell).strip())
            self.table_cell = None
            return
        if self.current is None:
            return
        if tag in self.HEADINGS or tag in {"p", "li", "pre", "blockquote", "figcaption"}:
            body = " ".join(" ".join(self.current["parts"]).split())
            if self.current["type"] == "SectionHeader":
                level = self.current["level"]
                self.section_path[:] = self.section_path[: level - 1]
                self.section_path.append(body)
                self._add("SectionHeader", body, "#" * level + " " + body, section_path=list(self.section_path))
            else:
                self._add("Text", body, section_path=list(self.section_path))
            self.current = None


def html_pages(path: Path, assets: Path, profile: str) -> list[dict]:
    raw, _ = decode_txt(path)
    parser = _HtmlCollector(assets, path.parent, profile)
    parser.feed(raw)
    parser.close()
    parser._flush_loose()
    return [make_page(1, parser.blocks, None, page_number=1)]


def email_pages(path: Path, assets: Path, profile: str) -> list[dict]:
    del assets, profile
    message = email.parser.BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    subject = str(message.get("Subject") or "").strip()
    blocks = []
    if subject:
        blocks.append(make_block("p0001_b000", "SectionHeader", None, subject, f"# {subject}", section_path=[subject]))
    headers = [f"{name}: {message.get(name)}" for name in ("From", "To", "Cc", "Date") if message.get(name)]
    if headers:
        blocks.append(make_block(f"p0001_b{len(blocks):03d}", "Text", None, "\n".join(headers), "\n".join(headers)))
    body_text = ""
    attachments = []
    if message.is_multipart():
        for part in message.walk():
            disposition = part.get_content_disposition()
            filename = part.get_filename()
            if disposition == "attachment" or filename:
                attachments.append(filename or part.get_content_type())
                continue
            if part.get_content_type() == "text/plain" and not body_text:
                try:
                    body_text = part.get_content()
                except Exception:
                    body_text = part.get_payload(decode=True).decode("utf-8", "replace")
            elif part.get_content_type() == "text/html" and not body_text:
                try:
                    body_text = _strip_html(part.get_content())
                except Exception:
                    body_text = ""
    else:
        try:
            body_text = message.get_content()
        except Exception:
            body_text = message.get_payload(decode=True).decode("utf-8", "replace")
        if message.get_content_type() == "text/html":
            body_text = _strip_html(body_text)
    if body_text.strip():
        blocks.append(make_block(
            f"p0001_b{len(blocks):03d}", "Text", None, body_text.strip(), body_text.strip(),
            review_flags=[{"code": "EMAIL_BODY", "severity": "info"}],
        ))
    for filename in attachments:
        blocks.append(make_block(
            f"p0001_b{len(blocks):03d}", "Text", None,
            f"[Attachment: {filename}]", f"[Attachment: {filename}]",
            review_flags=[{"code": "ATTACHMENT_NOT_INGESTED", "severity": "warning"}],
        ))
    if not blocks:
        raise InputError("EMPTY_DOCUMENT", "email has no readable body")
    return [make_page(1, blocks, None, page_number=1)]

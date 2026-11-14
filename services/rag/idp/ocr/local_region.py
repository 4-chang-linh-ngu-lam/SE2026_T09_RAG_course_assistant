"""CommandRegionReader adapter for a separately managed local llama.cpp VLM.

No server/model startup, downloads, external network, correction dictionaries,
or automatic trust. The caller supplies the immutable runner/model revision.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import os
import sys
from pathlib import Path
import urllib.parse
import urllib.request

from PIL import Image

LOCAL_REGION_VERSION = "idp-local-region-3"
ERROR_CODES = {"ORIGIN", "LIMITS", "KIND", "PROFILE", "TABLE_FORMAT", "VISUAL_FORMAT", "IMAGE_BYTES", "IMAGE_PIXELS", "IMAGE_FORMAT", "RESPONSE_BYTES", "INCOMPLETE", "UNREADABLE"}


class LocalRegionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code

TEXT_PROMPT = ('Transcribe only the exact visible text in the image. Preserve Vietnamese accents, letter case, digits, '
               'punctuation, mathematical symbols, units and superscripts as Unicode text. Preserve line breaks. '
               'Do not explain, solve, infer missing values, or add formatting. If unreadable, output <unreadable>.')
PROMPTS = {
    "Text": TEXT_PROMPT,
    "Table": ('Transcribe the visible table as a single HTML <table> only. Preserve every row, column, merged cell, '
              'Vietnamese accent, digit, punctuation, mathematical symbol, unit and superscript as Unicode. '
              'Use <td> for cells unless a header is explicit in the image. Preserve all punctuation and empty cells. '
              'Do not solve, complete missing values, explain or add code fences. Use <unreadable> for unreadable text.'),
    "Equation": ('Transcribe the visible mathematical expression as LaTeX only, without dollar delimiters, '
                 'explanation or code fences. Preserve all signs, indices, exponents and units. Do not solve '
                 'or complete the expression. If unreadable, output <unreadable>.'),
}
VISUAL_PROMPT = ('Describe the visible figure faithfully for text retrieval. Include visible labels, relationships '
                 'and arrow directions. For charts include axes, units, series and readable values. Preserve '
                 'Vietnamese names, digits and symbols. Distinguish explicit labels from estimates; state when '
                 'a value or relation is unreadable. Do not solve exercises or infer missing facts. Return description only.')
# Task prefixes documented by PaddleOCR-VL. These are model instructions, not
# subject-specific corrections. Figure description needs a separate reader.
PADDLE_PROMPTS = {"Text": "OCR:", "Table": "Table Recognition:", "Equation": "Formula Recognition:"}
VISUAL_FACT_PROMPT = (
    'Extract concise visible evidence into the supplied JSON schema. Copy visible labels literally, including '
    'Vietnamese accents, digits and units, into labels. Relations use zero-based indexes into labels; distinguish '
    'an arrow from an undirected line or group. Include only explicit connections. In observations describe '
    'visible image content, axes, series and legible values briefly. Summary must be brief, not an explanation. '
    'Do not answer exercises, estimate unreadable values, add world knowledge or assert that your reading is correct. '
    'Set unreadable=true if necessary source details cannot be read or cannot fit the schema. Return JSON only.')
VISUAL_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["summary", "labels", "relations", "observations", "unreadable"],
    "properties": {
        "summary": {"type": "string", "maxLength": 160},
        "labels": {"type": "array", "maxItems": 16, "items": {"type": "string", "minLength": 1, "maxLength": 120}},
        "relations": {"type": "array", "maxItems": 16, "items": {"type": "object", "additionalProperties": False,
            "required": ["from", "to", "kind"], "properties": {
                "from": {"type": "integer", "minimum": 0}, "to": {"type": "integer", "minimum": 0},
                "kind": {"type": "string", "enum": ["line", "arrow", "group"]}}}},
        "observations": {"type": "array", "maxItems": 8, "items": {"type": "string", "minLength": 1, "maxLength": 160}},
        "unreadable": {"type": "boolean"}}}


def _visual_facts(text):
    try:
        value = json.loads(text)
        if not isinstance(value, dict) or set(value) != set(VISUAL_SCHEMA["required"]):
            raise ValueError("invalid visual fields")
        if type(value["unreadable"]) is not bool:
            raise ValueError("invalid unreadable marker")
        if value["unreadable"]:
            raise LocalRegionError("UNREADABLE", "visual evidence is incomplete")
        if not isinstance(value["summary"], str) or len(value["summary"]) > 160:
            raise ValueError("invalid visual summary")
        for key, count, length in (("labels", 16, 120), ("observations", 8, 160)):
            if not isinstance(value[key], list) or len(value[key]) > count or any(
                    not isinstance(s, str) or not s.strip() or len(s) > length for s in value[key]):
                raise ValueError("invalid visual text list")
        if not isinstance(value["relations"], list) or len(value["relations"]) > 16:
            raise ValueError("invalid visual relation list")
        for relation in value["relations"]:
            if (not isinstance(relation, dict) or set(relation) != {"from", "to", "kind"}
                    or any(type(relation[k]) is not int or not 0 <= relation[k] < len(value["labels"]) for k in ("from", "to"))
                    or relation["kind"] not in {"line", "arrow", "group"}):
                raise ValueError("visual relation has no source label")
    except LocalRegionError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise LocalRegionError("VISUAL_FORMAT", "invalid structured visual evidence") from exc
    parts = [value["summary"].strip()]
    parts += [f"Label {i}: {s}" for i, s in enumerate(value["labels"])]
    parts += [f"{r['kind']}: {value['labels'][r['from']]} | {value['labels'][r['to']]}" for r in value["relations"]]
    parts += value["observations"]
    description = "\n".join(p for p in parts if p)
    if not description:
        raise LocalRegionError("UNREADABLE", "visual evidence is empty")
    return {"description": description, "visual_facts": value}


def _prompt(kind, profile):
    if profile in {"generic", "qwen"}:
        if profile == "qwen" and kind not in PROMPTS:
            return VISUAL_FACT_PROMPT
        return PROMPTS.get(kind, VISUAL_PROMPT)
    if profile != "paddleocr":
        raise LocalRegionError("PROFILE", "unsupported local region prompt profile")
    if kind not in PADDLE_PROMPTS:
        raise LocalRegionError("KIND", "PaddleOCR profile does not provide figure descriptions")
    return PADDLE_PROMPTS[kind]


def _unwrap_latex(text):
    # Remove one outer presentation delimiter only. Never repair source signs,
    # accents, braces or units, including outputs that look linguistically wrong.
    stripped = text.strip()
    if stripped.startswith("$$") != stripped.endswith("$$"):
        return text
    for left, right in ((r"\[", r"\]"), (r"\(", r"\)"), ("$$", "$$"), ("$", "$")):
        if len(stripped) >= len(left) + len(right) and stripped.startswith(left) and stripped.endswith(right):
            inner = stripped[len(left):-len(right)]
            if left in inner or right in inner:
                return text
            return inner.strip()
    return text


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise LocalRegionError("ORIGIN", "local region reader does not follow redirects")


def read_region(image_path, kind, *, base_url="http://127.0.0.1:8081", timeout=8, max_tokens=1024, model=None, prompt_profile="generic"):
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise LocalRegionError("ORIGIN", "local region URL must be a loopback HTTP server origin")
    if not math.isfinite(timeout) or timeout <= 0 or type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
        raise LocalRegionError("LIMITS", "invalid local region limits")
    if kind not in {"Text", "Table", "Equation", "Picture", "Diagram", "Chart", "PictureGroup"}:
        raise LocalRegionError("KIND", "unsupported local region kind")
    prompt = _prompt(kind, prompt_profile)
    path = Path(image_path)
    if path.stat().st_size > 10_000_000:
        raise LocalRegionError("IMAGE_BYTES", "local region image byte limit")
    with Image.open(path) as image:
        if image.width * image.height > 2_000_000:
            raise LocalRegionError("IMAGE_PIXELS", "local region image pixel limit")
        mime = Image.MIME.get(image.format)
        if mime not in {"image/png", "image/jpeg", "image/webp"}:
            raise LocalRegionError("IMAGE_FORMAT", "unsupported local region image format")
    image_url = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]
    if prompt_profile in {"paddleocr", "qwen"}:
        # Match PaddleX's doc_vlm request: image first, native task prefix last.
        # Some multimodal templates preserve this order in the model context.
        content.reverse()
    payload = {"messages": [{"role": "user", "content": content}],
               "temperature": 0, "max_tokens": max_tokens, "stream": False}
    if prompt_profile == "qwen" and kind not in PROMPTS:
        payload["response_format"] = {"type": "json_object", "schema": VISUAL_SCHEMA}
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    if model:
        payload["model"] = model
    request = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions",
                                     data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    # Disable ambient proxies and redirects so source images stay on loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise LocalRegionError("RESPONSE_BYTES", "local region response byte limit")
    result = json.loads(raw)
    choice = result["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise LocalRegionError("INCOMPLETE", "local region output incomplete or finish reason unavailable")
    text = choice["message"]["content"]
    if (not isinstance(text, str) or not text.strip() or len(text) > 32768
            or any(marker in text.lower() for marker in ("<unreadable>", "[unreadable]"))):
        raise LocalRegionError("UNREADABLE", "local region reading empty, unreadable or oversized")
    if kind == "Equation" and prompt_profile == "paddleocr":
        text = _unwrap_latex(text)
        if not text.strip():
            raise LocalRegionError("UNREADABLE", "local region formula empty after outer delimiters")
    if kind == "Table" and prompt_profile == "paddleocr":
        from idp.structured.otsl import otsl_to_html
        from idp.structured.structure import parse_table_html
        try:
            if text.lstrip().startswith(("<fcel>", "<ecel>")):
                text = otsl_to_html(text)
            table = parse_table_html(text)
            if not table["rectangular"]:
                raise ValueError("incomplete table topology")
        except ValueError as exc:
            raise LocalRegionError("TABLE_FORMAT", "local region table format is incomplete or unsupported") from exc
    if prompt_profile == "qwen" and kind not in PROMPTS:
        return _visual_facts(text)
    key = {"Text": "text", "Table": "table_html", "Equation": "latex"}.get(kind, "description")
    return {key: text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8081")
    parser.add_argument("--model")
    parser.add_argument("--prompt-profile", choices=("generic", "paddleocr", "qwen"), default="generic")
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument("--max-tokens", type=int, default=1024)
    args = parser.parse_args()
    try:
        value = read_region(os.environ["IDP_REGION_IMAGE"], os.environ["IDP_REGION_KIND"],
                            base_url=args.url, timeout=args.timeout, max_tokens=args.max_tokens, model=args.model,
                            prompt_profile=args.prompt_profile)
    except LocalRegionError as exc:
        print(json.dumps({"code": "LOCAL_REGION_REJECTED", "reason": exc.code}), file=sys.stderr)
        return 2
    output = os.environ.get("IDP_REGION_OUTPUT")
    if output:
        Path(output).write_text(json.dumps(value, ensure_ascii=False), "utf-8")
    else:
        print(json.dumps(value, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

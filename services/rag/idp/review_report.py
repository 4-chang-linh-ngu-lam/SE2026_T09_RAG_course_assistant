import html
import json
from pathlib import Path


def _relative(path: str | None, out_dir: Path) -> str:
    if not path:
        return ""
    p = Path(path)
    try:
        return p.resolve().relative_to(out_dir.resolve()).as_posix()
    except Exception:
        return p.as_posix()


def write_review_html(out_dir: str | Path, review_items: list[dict]) -> Path:
    out_dir = Path(out_dir)
    rows = []
    for item in review_items:
        crop = _relative(item.get("block_crop_path"), out_dir)
        image = f'<img src="{html.escape(crop)}" loading="lazy">' if crop else ""
        marker = html.escape(str(item.get("marker_text", "")))
        candidate = html.escape(str(item.get("tesseract_text", "")))
        rows.append(
            "<tr>"
            f"<td>{item.get('page')}</td>"
            f"<td>{html.escape(str(item.get('block_id')))}</td>"
            f"<td>{html.escape(str(item.get('code')))}</td>"
            f"<td>{html.escape(str(item.get('severity', '')))}</td>"
            f"<td>{image}</td>"
            f"<td>{marker}</td>"
            f"<td>{candidate}</td>"
            "</tr>"
        )
    document = f"""<!doctype html>
<html lang="vi"><meta charset="utf-8">
<title>IDP review queue</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 6px; vertical-align: top; font-size: 13px; }}
img {{ max-width: 260px; max-height: 180px; }}
</style>
<h1>IDP review queue ({len(review_items)} items)</h1>
<table>
<thead><tr><th>Page</th><th>Block</th><th>Code</th><th>Severity</th><th>Crop</th><th>Marker</th><th>Tesseract candidate</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</html>"""
    path = out_dir / "review.html"
    path.write_text(document, encoding="utf-8")
    return path

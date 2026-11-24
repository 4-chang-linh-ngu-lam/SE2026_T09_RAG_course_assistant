"""Text-layer encoding checks shared by the digital parser and math rebuild.

One implementation, so a finding removed after a glyph rebuild can never
disagree with the digital audit that requires TEXT_ENCODING_REVIEW on every
block whose text still fails these checks.
"""

from __future__ import annotations

import re

# "· · ·" is an ellipsis; "y(·)" / "u_{1}(·)" is the argument placeholder of a
# function (applied directly after an identifier or a subscript brace).
_DOT_ELLIPSIS = re.compile(r"·(?:[ \t]+·){2}(?![ \t]+·)")
_ARGUMENT_PLACEHOLDER = re.compile(r"(?<=[^\W\d_]|[}′'])\(·\)")


def encoding_issues(text: str) -> list[str]:
    issues = []
    if "�" in text:
        issues.append("replacement_char")
    if re.search(r"\(cid:\d+\)", text):
        issues.append("cid_text")
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\n\t\r")
    if controls:
        issues.append("control_chars")
    letters = sum(1 for ch in text if ch.isalpha())
    remaining = _ARGUMENT_PLACEHOLDER.sub("", _DOT_ELLIPSIS.sub("", text))
    middle_dots = remaining.count("·")
    if middle_dots >= 3 and middle_dots / max(1, letters) > 0.02:
        issues.append("middle_dot_substitution")
    return issues

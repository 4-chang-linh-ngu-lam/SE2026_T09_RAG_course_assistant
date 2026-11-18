"""Deterministic syntax checks for model-generated LaTeX.

Formula recognizers can return LaTeX with unbalanced groups or a decoder loop
("{}^{n}{}^{n}{}^{n}..."). These checks only flag output that cannot be
trusted structurally; passing them says nothing about whether the formula
matches the page. Nothing here rewrites the model output.
"""

import re

VERSION = "latex-check:1"
TOKEN = re.compile(r"\\[A-Za-z]+|\\.|[^\s]")
# A token n-gram repeated this many times back to back is a decoding loop.
# Single-token runs need more repeats: "000" or "\quad\quad" are legitimate.
MIN_REPEATS = 4
MIN_SINGLE_REPEATS = 16
MAX_NGRAM = 8
MAX_TOKENS = 4096


def repetition(tokens):
    for n in range(1, MAX_NGRAM + 1):
        need = MIN_SINGLE_REPEATS if n == 1 else MIN_REPEATS
        for i in range(len(tokens) - n * need + 1):
            unit = tokens[i : i + n]
            # "0 0" repeated is the single-token case; judge it with its own,
            # higher threshold so long numbers are not loops.
            if any(
                n % p == 0 and unit == unit[:p] * (n // p) for p in range(1, n)
            ):
                continue
            if all(tokens[i + k * n : i + (k + 1) * n] == unit for k in range(1, need)):
                return True
    return False


def check_latex(latex):
    """Return ``{"version", "status", "reasons"}``; status is review or syntax_ok."""
    reasons = []
    tokens = TOKEN.findall(latex or "")
    if not tokens:
        reasons.append("empty")
    if len(tokens) > MAX_TOKENS:
        reasons.append("too_long")
    depth = 0
    for token in tokens:
        depth += token == "{"
        depth -= token == "}"
        if depth < 0:
            break
    if depth != 0:
        reasons.append("unbalanced_braces")
    if tokens.count(r"\left") != tokens.count(r"\right"):
        reasons.append("unbalanced_left_right")
    begins = re.findall(r"\\begin\s*\{([^{}]*)\}", latex or "")
    ends = re.findall(r"\\end\s*\{([^{}]*)\}", latex or "")
    if sorted(begins) != sorted(ends):
        reasons.append("unbalanced_environment")
    for command in (r"\frac", r"\dfrac", r"\tfrac", r"\cfrac"):
        for index, token in enumerate(tokens):
            if token == command and (
                index + 1 >= len(tokens) or tokens[index + 1] != "{"
            ):
                reasons.append("frac_without_group")
                break
    if len(tokens) <= MAX_TOKENS and repetition(tokens):
        reasons.append("repetition")
    reasons = sorted(set(reasons))
    return {
        "version": VERSION,
        "status": "review" if reasons else "syntax_ok",
        "reasons": reasons,
    }

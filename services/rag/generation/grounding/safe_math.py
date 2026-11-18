"""Bounded arithmetic evaluator for model-written expressions (§5.6).

Never ``eval``/``sympy.parse_expr`` a model string. This walks a Python AST and
accepts only numeric literals, + - * / // % **, unary signs, the constants
``pi``/``e`` and a whitelist of math functions, with size and magnitude limits.
"""
from __future__ import annotations

import ast
import math
import re

MAX_EXPRESSION_CHARS = 200
MAX_NODES = 64
MAX_ABS = 1e15
MAX_EXPONENT = 64

_FUNCTIONS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
              "asin": math.asin, "acos": math.acos, "atan": math.atan, "log": math.log,
              "log10": math.log10, "log2": math.log2, "exp": math.exp, "abs": abs,
              "floor": math.floor, "ceil": math.ceil, "radians": math.radians,
              "degrees": math.degrees, "round": round}
_CONSTANTS = {"pi": math.pi, "e": math.e}
_BINARY = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


class MathError(ValueError):
    code = "invalid_expression"


def normalise_expression(text: str) -> str:
    text = (text.replace("×", "*").replace("·", "*").replace("÷", "/").replace("−", "-")
            .replace("^", "**").replace("√", "sqrt").replace("π", "pi"))
    return _DECIMAL_COMMA.sub(".", text)


def parse_number(text) -> float:
    """Parse a numeric answer written either way ("3,5" or "3.5"; "1 000")."""
    if isinstance(text, bool):
        raise MathError("not a number")
    if isinstance(text, (int, float)):
        value = float(text)
    else:
        raw = str(text).strip().replace("−", "-").replace(" ", "").replace(" ", "")
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", raw):      # 1.000.000,5
            raw = raw.replace(".", "").replace(",", ".")
        elif re.fullmatch(r"-?\d+,\d+", raw):                      # 3,5
            raw = raw.replace(",", ".")
        elif re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", raw):    # 1,000,000.5
            raw = raw.replace(",", "")
        if not re.fullmatch(r"-?\d+(\.\d+)?([eE]-?\d+)?", raw):
            raise MathError("not a number")
        value = float(raw)
    if not math.isfinite(value):
        raise MathError("not finite")
    return value


def evaluate(expression: str) -> float:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > MAX_EXPRESSION_CHARS:
        raise MathError("expression length")
    try:
        tree = ast.parse(normalise_expression(expression), mode="eval")
    except SyntaxError:
        raise MathError("syntax") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise MathError("expression too large")
    return _check(_eval(tree.body))


def _check(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MathError("non-numeric")
    value = float(value)
    if not math.isfinite(value) or abs(value) > MAX_ABS:
        raise MathError("out of range")
    return value


def _eval(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _check(node.value)
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, _BINARY):
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > MAX_EXPONENT or abs(left) > MAX_ABS):
            raise MathError("exponent too large")
        try:
            result = {ast.Add: lambda: left + right, ast.Sub: lambda: left - right,
                      ast.Mult: lambda: left * right, ast.Div: lambda: left / right,
                      ast.FloorDiv: lambda: left // right, ast.Mod: lambda: left % right,
                      ast.Pow: lambda: left ** right}[type(node.op)]()
        except (ZeroDivisionError, OverflowError, ValueError):
            raise MathError("arithmetic error") from None
        if isinstance(result, complex):
            raise MathError("complex result")
        return _check(result)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS
            and not node.keywords and 1 <= len(node.args) <= 2):
        args = [_eval(a) for a in node.args]
        if len(args) == 2 and node.func.id not in {"log", "round"}:
            raise MathError("arity")
        try:
            return _check(_FUNCTIONS[node.func.id](*([args[0], int(args[1])] if node.func.id == "round" and len(args) == 2 else args)))
        except (ValueError, OverflowError):
            raise MathError("domain error") from None
    raise MathError(f"forbidden syntax: {type(node).__name__}")


def close(a: float, b: float, tolerance: float = 0.0) -> bool:
    """Absolute tolerance when given, else a tight relative comparison."""
    if tolerance > 0:
        return abs(a - b) <= tolerance + 1e-12
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)

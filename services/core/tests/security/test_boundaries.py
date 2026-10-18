"""Static architecture guard complements HTTP authorization/real DB tests."""

import ast
import re
from pathlib import Path


def violations(source, owner):
    result = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        imports = []
        if isinstance(node, ast.ImportFrom) and node.module:
            imports = [node.module]
            if node.module == "app.modules":
                imports = [f"app.modules.{alias.name}" for alias in node.names]
            elif re.fullmatch(r"app\.modules\.\w+", node.module):
                imports = [f"{node.module}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            imports = [alias.name for alias in node.names]
        for module in imports:
            parts = module.split(".")
            if (
                len(parts) > 2
                and parts[:2] == ["app", "modules"]
                and parts[2] != owner
                and parts[-1] != "public"
            ):
                result.append((node.lineno, module))
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.search(
                r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+[\"']?(?:document|learning|ai|learner_intelligence)[\"']?\s*\.",
                node.value,
                re.IGNORECASE,
            )
        ):
            result.append((node.lineno, "cross-service SQL"))
    return result


def test_domain_modules_only_import_other_modules_public_boundaries():
    root = Path(__file__).resolve().parents[2] / "app" / "modules"
    failures = []
    for path in root.rglob("*.py"):
        owner = path.relative_to(root).parts[0]
        failures.extend(
            (str(path.relative_to(root)), line, reason)
            for line, reason in violations(path.read_text(encoding="utf-8"), owner)
        )
    assert failures == []


def test_boundary_guard_detects_forbidden_imports_and_cross_service_sql():
    source = """
from app.modules.identity.models import User
from app.modules.identity import repository
import app.modules.identity.service
query = "SELECT id FROM learning.submissions"
"""
    assert len(violations(source, "classroom")) == 4
    assert violations("from app.modules.identity import public as identity", "classroom") == []
    assert (
        violations(
            "from app.modules.social.feed.public import get_visible_post_ref", "notification"
        )
        == []
    )

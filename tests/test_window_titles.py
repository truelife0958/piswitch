"""Native window chrome must stay ASCII under WSLg.

Tk widget text renders through the configured CJK font, but WSLg forwards native
window titles through a separate path that displays Chinese code points as numbered
tofu boxes on affected systems.
"""
from __future__ import annotations

import ast
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
GUI_FILES = (
    "piswitch.py",
    "config_dialogs.py",
    "dialogs.py",
    "remote_dialog.py",
    "ui/form_guard.py",
    "ui/model_ops.py",
    "ui/network.py",
    "ui/provider_crud.py",
)


def _title_expression(call: ast.Call):
    if not isinstance(call.func, ast.Attribute):
        return None
    owner = call.func.value
    if call.func.attr == "title" and call.args:
        return call.args[0]
    if isinstance(owner, ast.Name) and owner.id in {"messagebox", "simpledialog"}:
        return call.args[0] if call.args else None
    if isinstance(owner, ast.Name) and owner.id == "filedialog":
        return next((item.value for item in call.keywords if item.arg == "title"), None)
    return None


def _is_ascii_title(expression: ast.AST) -> bool:
    if (
        isinstance(expression, ast.Attribute)
        and isinstance(expression.value, ast.Name)
        and expression.value.id == "theme"
        and expression.attr == "WINDOW_TITLE"
    ):
        return True
    strings = [
        node.value
        for node in ast.walk(expression)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    return bool(strings) and all(value.isascii() for value in strings)


def test_native_window_titles_are_ascii():
    failures = []
    for relative_path in GUI_FILES:
        path = REPO / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            expression = _title_expression(node)
            if expression is not None and not _is_ascii_title(expression):
                failures.append(f"{relative_path}:{node.lineno}")
    assert failures == [], f"non-ASCII native window titles: {', '.join(failures)}"

from __future__ import annotations

import ast
import re

from src.utils.ast_helpers import top_name

PYWIN32_MODULES = {
    "win32api",
    "win32gui",
    "win32com",
    "win32process",
    "win32service",
    "win32clipboard",
    "pythoncom",
}
URL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")


def _classify_top_module(top: str) -> str | None:
    if top == "subprocess":
        return "subprocess"
    if top == "webbrowser":
        return "webbrowser"
    if top in PYWIN32_MODULES:
        return "pywin32"
    if top == "pywinauto":
        return "pywinauto"
    return None


def _full_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _full_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _is_protocol_literal(value: str) -> bool:
    if WINDOWS_DRIVE_RE.match(value):
        return False
    return bool(URL_SCHEME_RE.match(value))


def detect_high_risk_apis(code: str) -> list[str]:
    """Detect shortcut or high-risk desktop APIs with one shared rule set."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    labels: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                label = _classify_top_module(top_name(alias.name))
                if label:
                    labels.add(label)

        elif isinstance(node, ast.ImportFrom):
            label = _classify_top_module(top_name(node.module))
            if label:
                labels.add(label)

        elif isinstance(node, ast.Call):
            name = _full_name(node.func)
            top = top_name(name)
            label = _classify_top_module(top)
            if label:
                labels.add(label)
            if name == "os.startfile":
                labels.add("os.startfile")

        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _is_protocol_literal(node.value):
                labels.add("win32_protocol_url")

    return sorted(labels)

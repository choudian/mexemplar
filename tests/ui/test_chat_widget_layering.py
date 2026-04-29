import ast
from pathlib import Path

import pytest

_CHAT_WIDGET_PATH = Path(__file__).resolve().parent.parent.parent / "src" / "ui" / "widgets" / "chat_widget.py"


def _parse_imports():
    source = _CHAT_WIDGET_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                names.append((node.module, alias.name if alias.asname is None else alias.asname))
    return names


_imports = _parse_imports()
_MODULES = [m for m, _ in _imports]
_NAMES = [n for _, n in _imports]


def test_chat_widget_imports_chat_service():
    assert "src.business.services" in _MODULES, (
        "ChatWidget 必须通过业务层 ChatService 访问数据，" f"当前 imports: {_MODULES}"
    )


def test_chat_widget_does_not_import_repositories():
    forbidden = {"MessageRepository", "SessionRepository"}
    found = forbidden & set(_NAMES)
    assert not found, f"ChatWidget 不应直接导入 Repository: {found}"
    forbidden_modules = {"src.data.repos", "src.data.repositories"}
    found_mods = forbidden_modules & set(_MODULES)
    assert not found_mods, f"ChatWidget 不应导入数据层模块: {found_mods}"

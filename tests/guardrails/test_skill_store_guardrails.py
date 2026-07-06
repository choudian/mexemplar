"""技能商店架构守卫（029 T012/CC-170/D6）。

安装/预览路径零执行是硬边界：skill_store 模块任何文件不得 import 执行层、
subprocess 或调用 exec 类工具。外部导入方法论渲染必须附来源警示框架。
"""

from __future__ import annotations

import re
from pathlib import Path

_SKILL_STORE_DIR = Path(__file__).resolve().parents[2] / "src" / "business" / "skill_store"

_FORBIDDEN_PATTERNS = (
    re.compile(r"\bimport\s+subprocess\b"),
    re.compile(r"\bfrom\s+subprocess\b"),
    re.compile(r"\bfrom\s+src\.execution\b"),
    re.compile(r"\bimport\s+src\.execution\b"),
    re.compile(r"\bos\.system\b"),
    re.compile(r"\bos\.exec"),
    re.compile(r"\bPopen\b"),
    re.compile(r"(?<![\w.])eval\("),
    re.compile(r"(?<![\w.])exec\("),
)


def test_skill_store_module_has_zero_execution_surface() -> None:
    """CC-170：skill_store 全模块源码不得出现任何执行入口符号。"""
    py_files = sorted(_SKILL_STORE_DIR.glob("*.py"))
    assert py_files, "skill_store 模块不存在？守卫路径失效"
    for path in py_files:
        source = path.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN_PATTERNS:
            assert not pattern.search(source), f"{path.name} 命中禁止符号 {pattern.pattern}"


def test_install_service_never_imports_bridge_or_trial() -> None:
    """安装编排不得触碰实施桥/试跑机制——安装是纯数据落地。"""
    source = (_SKILL_STORE_DIR / "install_service.py").read_text(encoding="utf-8")
    for forbidden in ("proposal_bridge", "trial_runner", "tool_trial", "TaskCollaboration"):
        assert forbidden not in source, f"install_service 不得引用 {forbidden}"


def test_external_import_render_carries_warning_frame() -> None:
    """D6：external_import 方法论渲染必须附来源警示头（advisory 软防御）。"""
    from src.business.agents.tools.skill_methodology_tools import (
        _EXTERNAL_IMPORT_WARNING,
        _render_skill_md,
    )

    assert "不可无条件信任" in _EXTERNAL_IMPORT_WARNING

    class _Skill:
        name = "n"
        description = "d"
        trigger_conditions = "[]"
        required_tools = "[]"
        body_markdown = "body"
        origin = "external_import"

    rendered = _render_skill_md(_Skill())
    assert rendered.startswith("> ⚠️")
    assert "不可无条件信任" in rendered

    class _Internal(_Skill):
        origin = "assistant_tool_call"

    assert not _render_skill_md(_Internal()).startswith("> ⚠️")


def test_external_skill_files_confined_to_managed_root(tmp_path, monkeypatch) -> None:
    """CC-174：写盘只能落在 external_skills 受管根内。"""
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path))
    from src.business.skill_store.file_store import (
        SkillFile,
        external_skills_root,
        write_install_dir,
    )

    final_dir = write_install_dir(
        "esi_guard", [SkillFile(path="SKILL.md", content="x")]
    )
    root = external_skills_root().resolve()
    assert final_dir.resolve().is_relative_to(root)

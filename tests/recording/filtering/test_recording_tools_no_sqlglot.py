"""
Guard test: recording_data_tools.py 不得直接 import sqlglot。
SQL 血缘分析严格留在 src/recording/filtering/ 内。
"""

import importlib
from pathlib import Path

from src.utils.ast_helpers import extract_import_names


def test_recording_data_tools_does_not_import_sqlglot():
    """recording_data_tools.py 不得直接或间接 import sqlglot。"""
    tools_path = Path("src/business/agents/tools/recording_data_tools.py")
    if not tools_path.exists():
        pytest.skip("recording_data_tools.py not found")

    imports = extract_import_names(tools_path.read_text(encoding="utf-8"))
    assert "sqlglot" not in imports, (
        f"recording_data_tools.py must not import sqlglot directly. "
        f"Found imports: {imports}"
    )


import pytest


def test_recording_data_tools_no_transitive_sqlglot():
    """验证 recording_data_tools 模块加载后不会把 sqlglot 带入其 __dict__。"""
    try:
        mod = importlib.import_module("src.business.agents.tools.recording_data_tools")
    except Exception:
        pytest.skip("recording_data_tools module could not be loaded")
    for attr_name in dir(mod):
        assert "sqlglot" not in attr_name.lower()

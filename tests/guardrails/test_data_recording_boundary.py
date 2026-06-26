"""分层门卫:src/data/ 不得反向 import src/recording(Constitution Principle I)。

锁住 P0 2.1/2.2 的分层修复成果(FilterDecision / RecordingMode / queue_paths 已下沉,
data 层不再为它们反向依赖 recording 层),防止后续重构(如 1.4 或其他)再引入新越权。

过渡例外:``recording_recovery.py`` 尚有 2 处 recording import
(DuckDBRecordingPersister / persist_filtered_network_requests),2.3 把 recovery
搬到 recording 层后清零,届时删本文件的 RECOVERY 例外断言。
"""

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = _REPO_ROOT / "src" / "data"
RECORDING_PREFIX = "src.recording"

# 过渡例外(2.3 搬家后清零)
RECOVERY_FILE = "recording_recovery.py"
ALLOWED_RECOVERY_IMPORTS = 2  # DuckDBRecordingPersister + persist_filtered_network_requests


def _recording_imports_in(text: str) -> list[str]:
    tree = ast.parse(text)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(
            RECORDING_PREFIX
        ):
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(RECORDING_PREFIX):
                    modules.append(alias.name)
    return modules


def test_data_layer_does_not_import_recording() -> None:
    """src/data/ 除 recording_recovery 过渡例外外,不得反向 import src/recording。"""
    non_recovery_violations: list[tuple[str, list[str]]] = []
    recovery_count = 0
    for py in DATA_DIR.rglob("*.py"):
        rel = py.relative_to(DATA_DIR).name
        modules = _recording_imports_in(py.read_text(encoding="utf-8"))
        if not modules:
            continue
        if rel == RECOVERY_FILE:
            recovery_count += len(modules)
        else:
            non_recovery_violations.append((rel, modules))

    assert not non_recovery_violations, (
        "src/data/ 反向 import src/recording(非 recording_recovery),违反分层:\n"
        + "\n".join(f"{f}: {m}" for f, m in non_recovery_violations)
    )
    assert recovery_count <= ALLOWED_RECOVERY_IMPORTS, (
        f"recording_recovery.py 的 recording import 增至 {recovery_count} 处,"
        f"应 <= {ALLOWED_RECOVERY_IMPORTS}(2.3 搬家后清零)"
    )

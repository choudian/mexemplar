"""分层门卫:src/data/ 不得反向 import src/recording(Constitution Principle I)。

锁住 P0 2.1/2.2/2.3 的分层修复成果(FilterDecision / RecordingMode / queue_paths 已下沉,
recording_recovery 已搬到 src/recording/recovery/),data 层对 recording 层零反向依赖,
防止后续重构(如 1.4 或其他)再引入新越权。
"""

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = _REPO_ROOT / "src" / "data"
RECORDING_PREFIX = "src.recording"


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
    """src/data/ 不得反向 import src/recording,违反 Constitution Principle I 分层。"""
    violations: list[tuple[str, list[str]]] = []
    for py in DATA_DIR.rglob("*.py"):
        modules = _recording_imports_in(py.read_text(encoding="utf-8"))
        if not modules:
            continue
        rel = py.relative_to(DATA_DIR).name
        violations.append((rel, modules))

    assert not violations, (
        "src/data/ 反向 import src/recording,违反分层:\n"
        + "\n".join(f"{f}: {m}" for f, m in violations)
    )

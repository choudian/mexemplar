from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RETIREMENT_TEXT = "Legacy PyQt launch is no longer supported"


def test_legacy_src_main_exits_with_explicit_unsupported_message() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--gui"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 2
    assert RETIREMENT_TEXT in result.stderr


def test_legacy_launch_files_do_not_import_pyqt_or_src_ui() -> None:
    for relative_path in ["src/main.py", "mexemplar_gui.py"]:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "PyQt6" not in content
        assert "src.ui" not in content
        assert "main_window" not in content


def test_batch_launchers_fail_closed_instead_of_starting_pyqt() -> None:
    for relative_path in ["start.bat", "mexemplar_gui.bat"]:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert RETIREMENT_TEXT in content
        assert "src.main --gui" not in content
        assert "mexemplar_gui.py" not in content


def test_retired_pyqt_source_and_tests_have_no_maintained_files() -> None:
    retired_roots = ["src/ui", "tests/ui", "tests/e2e"]
    leftovers = []

    for relative_root in retired_roots:
        root = ROOT / relative_root
        if not root.exists():
            continue
        leftovers.extend(
            path.relative_to(ROOT).as_posix()
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )

    assert leftovers == []


def test_python_dependencies_do_not_include_pyqt_runtime() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    assert "pyqt6" not in pyproject

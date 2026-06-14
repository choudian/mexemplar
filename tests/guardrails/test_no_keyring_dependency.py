from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_and_build_metadata_have_no_keyring_dependency() -> None:
    scanned = [
        ROOT / "src",
        ROOT / "pyproject.toml",
        ROOT / "build_exe.spec",
        ROOT / "build_executable.py",
    ]
    violations = []
    for entry in scanned:
        paths = entry.rglob("*") if entry.is_dir() else [entry]
        for path in paths:
            if not path.is_file() or path.suffix not in {".py", ".toml", ".spec"}:
                continue
            if "keyring" in path.read_text(encoding="utf-8").lower():
                violations.append(str(path.relative_to(ROOT)))

    assert violations == []

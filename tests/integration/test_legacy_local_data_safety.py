from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_retired_legacy_launcher_does_not_mutate_local_data(tmp_path) -> None:
    data_dir = tmp_path / "legacy-data"
    data_dir.mkdir()
    sentinel = data_dir / "mexemplar.db"
    sentinel.write_text("existing legacy data", encoding="utf-8")
    before = _digest(sentinel)

    env = os.environ.copy()
    env["EXEMPLAR_DATA_DIR"] = str(data_dir)
    result = subprocess.run(
        [sys.executable, "-m", "src.main", "--gui"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 2
    assert "Legacy PyQt launch is no longer supported" in result.stderr
    assert _digest(sentinel) == before
    assert sorted(path.name for path in data_dir.iterdir()) == ["mexemplar.db"]

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def _powershell_int_assignment(script: str, name: str) -> int:
    match = re.search(rf"^\s*\${re.escape(name)}\s*=\s*(\d+)\s*$", script, re.MULTILINE)
    assert match is not None, f"Missing ${name} assignment"
    return int(match.group(1))


def _vite_dev_port(config: str) -> int:
    match = re.search(r"\bport\s*:\s*(\d+)\s*,", config)
    assert match is not None, "Missing Vite server.port"
    return int(match.group(1))


def test_dev_script_frontend_port_matches_vite_and_tauri_dev_url() -> None:
    dev_script = (ROOT / "dev.ps1").read_text(encoding="utf-8")
    vite_config = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
    tauri_config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    script_port = _powershell_int_assignment(dev_script, "FrontendPort")
    vite_port = _vite_dev_port(vite_config)
    tauri_dev_port = urlparse(tauri_config["build"]["devUrl"]).port

    assert script_port == vite_port == tauri_dev_port

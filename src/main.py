"""Retired legacy PyQt launcher.

The maintained desktop entrypoint is the Tauri shell with the Python sidecar
at `python -m src.desktop_api`.
"""

from __future__ import annotations

import argparse
import sys

RETIREMENT_MESSAGE = (
    "Legacy PyQt launch is no longer supported. "
    "Use `cd frontend && npm run tauri dev` for development or `build_tauri.bat` for packaging."
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mexemplar legacy launcher")
    parser.add_argument("--version", action="version", version="Mexemplar 0.1.0")
    parser.add_argument("--gui", action="store_true", help="Retired legacy GUI flag")
    parser.parse_args()
    print(RETIREMENT_MESSAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

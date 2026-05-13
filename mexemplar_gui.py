#!/usr/bin/env python3
"""Retired compatibility launcher for the old PyQt GUI."""

from __future__ import annotations

import sys

from src.main import main


if __name__ == "__main__":
    raise SystemExit(main())

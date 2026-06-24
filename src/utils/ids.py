"""ID generation helpers.

Centralizes entity ID generation so all repositories share one algorithm and
entropy budget (two UUID4 hex values concatenated and truncated to 50 chars),
avoiding per-repo drift such as single-UUID generators with half the entropy.
"""

from __future__ import annotations

from uuid import uuid4


def new_id() -> str:
    """生成 50 字符的唯一 ID（两个 UUID4 hex 拼接后截取）。"""
    return (uuid4().hex + uuid4().hex)[:50]

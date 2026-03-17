"""
Agent 事件 — 从统一事件系统导入

所有 Agent 相关事件统一在 src/utils/events.py 中定义。
此模块仅作兼容性 re-export，新代码直接从 src.utils.events 导入。
"""

from src.utils.events import emit, connect

__all__ = ["emit", "connect"]

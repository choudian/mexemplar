"""
Agent 编排器兼容入口。

公开 import 路径保持为:
    from src.business.orchestration.agent_orchestrator import AgentOrchestrator
"""

from .agent import AgentOrchestrator

__all__ = ["AgentOrchestrator"]

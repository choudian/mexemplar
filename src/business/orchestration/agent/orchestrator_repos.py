"""Orchestrator DI bundle —— AgentOrchestrator 依赖的 SQLite Repository 收口为可注入 bundle。

8 个 repo 统一从 src.data.repos 导入。RecordingRepository 是 DuckDB 异类句柄
（无 close()、不继承 BaseRepository），不进 bundle，由 Orchestrator 单独按 Optional 注入。
"""

from dataclasses import dataclass

from src.data.repos import (
    AssistantProfileRepository,
    AssistantTaskRepository,
    BrainRepository,
    MessageRepository,
    SessionRepository,
    TeachingFailureRepository,
    ToolRepository,
    WorkflowTransitionRepository,
)


@dataclass(frozen=True)
class OrchestratorRepos:
    """AgentOrchestrator 依赖的 8 个 SQLite Repository bundle（只读容器）。

    frozen 保证注入后字段稳定，便于测试用 fake bundle 替换。所有 repo 都继承
    BaseRepository，拥有 close()/__enter__/__exit__，可被 _close_orchestrator_resources
    统一遍历关闭。
    """

    session_repo: SessionRepository
    message_repo: MessageRepository
    transition_repo: WorkflowTransitionRepository
    failure_repo: TeachingFailureRepository
    tool_repo: ToolRepository
    profile_repo: AssistantProfileRepository
    task_repo: AssistantTaskRepository
    brain_repo: BrainRepository


def default_orchestrator_repos() -> OrchestratorRepos:
    """兜底工厂：未注入时用默认 Repository 实例组装 bundle（保持原硬编码行为）。"""
    return OrchestratorRepos(
        session_repo=SessionRepository(),
        message_repo=MessageRepository(),
        transition_repo=WorkflowTransitionRepository(),
        failure_repo=TeachingFailureRepository(),
        tool_repo=ToolRepository(),
        profile_repo=AssistantProfileRepository(),
        task_repo=AssistantTaskRepository(),
        brain_repo=BrainRepository(),
    )

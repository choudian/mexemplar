"""
数据访问层（DAO/Repository）

向后兼容模块 — 所有 Repository 已拆分到 src/data/repos/ 子包中。
新代码请直接从 src.data.repos 导入。
"""

from src.data.repos import (  # noqa: F401
    BaseRepository,
    ToolRepository,
    SessionRepository,
    MessageRepository,
    WorkflowTransitionRepository,
    PendingTaskRepository,
    AssistantProfileRepository,
    AssistantSummaryRepository,
    ToolSuggestionRepository,
    TeachingFailureRepository,
    SkillCompositionRepository,
    ToolOutputRepository,
    AssistantRunFailureRepository,
    UserTodoRepository,
)

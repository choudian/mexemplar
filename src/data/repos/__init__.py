"""
数据访问层（DAO/Repository）

提供对数据库表的 CRUD 操作。内部使用 SQLAlchemy ORM 实现，对外提供统一接口。
从 repositories.py 拆分而来，每个 Repository 独立文件，便于维护。
"""

from .base_repository import BaseRepository
from .tool_repository import ToolRepository
from .session_repository import SessionRepository
from .message_repository import MessageRepository
from .workflow_transition_repository import WorkflowTransitionRepository
from .pending_task_repository import PendingTaskRepository
from .assistant_profile_repository import AssistantProfileRepository
from .assistant_summary_repository import AssistantSummaryRepository
from .tool_suggestion_repository import ToolSuggestionRepository
from .teaching_failure_repository import TeachingFailureRepository
from .skill_composition_repository import SkillCompositionRepository
from .brain_repository import BrainRepository
from .specialist_repository import SpecialistRepository
from .tool_output_repository import ToolOutputRepository
from .assistant_run_failure_repository import AssistantRunFailureRepository

__all__ = [
    "BaseRepository",
    "ToolRepository",
    "SessionRepository",
    "MessageRepository",
    "WorkflowTransitionRepository",
    "PendingTaskRepository",
    "AssistantProfileRepository",
    "AssistantSummaryRepository",
    "ToolSuggestionRepository",
    "TeachingFailureRepository",
    "SkillCompositionRepository",
    "BrainRepository",
    "SpecialistRepository",
    "ToolOutputRepository",
    "AssistantRunFailureRepository",
]

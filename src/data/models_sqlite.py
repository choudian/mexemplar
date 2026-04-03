"""
SQLAlchemy ORM 模型 - SQLite 数据库 (mexemplar.db)

包含：tools, sessions, messages, workflow_transitions (Agent 会话相关)
"""

from datetime import datetime
from typing import Optional, Any
from enum import Enum
from sqlalchemy import String, Integer, Text, DateTime, Boolean, JSON, LargeBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """所有模型的基类"""

    pass


# ===== 枚举类型 =====


class AgentType(str, Enum):
    """Agent 类型枚举"""

    PM = "pm"
    PROGRAMMER = "programmer"
    TRIAL = "trial"
    ASSISTANT = "assistant"


class SessionStatus(str, Enum):
    """会话状态枚举"""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class Tool(Base):
    """工具定义表"""

    __tablename__ = "tools"

    tool_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, server_default="[]")
    steps: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, server_default="[]")

    # 代码执行相关字段
    execution_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    code_language: Mapped[str] = mapped_column(String(20), default="python")
    code_version: Mapped[str] = mapped_column(String(20), default="1.0")
    execution_strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dependencies: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, server_default="[]")

    # 意图和试用相关字段
    source_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    trial_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_tool_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Agent 工作流相关字段
    workflow_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    trial_success_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Tool(tool_id={self.tool_id!r}, tool_name={self.tool_name!r})>"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Tool":
        """从字典创建 Tool 对象（兼容旧代码）"""
        return cls(
            tool_id=data.get("tool_id"),
            tool_name=data.get("tool_name"),
            description=data.get("description"),
            parameters=data.get("parameters"),
            steps=data.get("steps"),
            execution_code=data.get("execution_code"),
            code_language=data.get("code_language", "python"),
            code_version=data.get("code_version", "1.0"),
            execution_strategy=data.get("execution_strategy"),
            dependencies=data.get("dependencies", []),
            source_intent_id=data.get("source_intent_id"),
            source=data.get("source", "manual"),
            trial_count=data.get("trial_count", 0),
            pending_tool_id=data.get("pending_tool_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# ===== Agent 会话相关模型 =====


class Session(Base):
    """会话表 ORM 模型"""

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    workflow_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")
    tool_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def get_tool_id_set(self) -> Optional[set]:
        """解析 tool_ids JSON 字段为 set。None 表示全部工具。"""
        if not self.tool_ids:
            return None
        import json

        return set(json.loads(self.tool_ids))

    def __repr__(self) -> str:
        return f"<Session(session_id={self.session_id!r}, agent_type={self.agent_type!r}, status={self.status!r})>"


class Message(Base):
    """消息表 ORM 模型"""

    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_type: Mapped[str] = mapped_column(String(20), default="normal")
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tool_calls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    compressed_range: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<Message(message_id={self.message_id!r}, session_id={self.session_id!r}, sequence={self.sequence!r})>"


class WorkflowTransition(Base):
    """工作流交接记录表 ORM 模型"""

    __tablename__ = "workflow_transitions"

    transition_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(50), nullable=False)
    from_session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<WorkflowTransition(transition_id={self.transition_id!r}, workflow_id={self.workflow_id!r})>"


# ===== 办公助理相关模型 =====


class AssistantProfile(Base):
    """助理用户偏好档案表"""

    __tablename__ = "assistant_profile"

    profile_id: Mapped[str] = mapped_column(String(50), primary_key=True, default="default")
    display_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    style: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<AssistantProfile(profile_id={self.profile_id!r}, display_name={self.display_name!r})>"


class PendingAssistantTask(Base):
    """助理异步任务队列表"""

    __tablename__ = "pending_assistant_tasks"

    task_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<PendingAssistantTask(task_id={self.task_id!r}, task_type={self.task_type!r}, status={self.status!r})>"


class TeachingFailureRecord(Base):
    """技能教学失败记录表"""

    __tablename__ = "teaching_failure_records"

    record_id: Mapped[str] = mapped_column(String(50), primary_key=True)  # UUID
    workflow_id: Mapped[str] = mapped_column(String(50), unique=True)  # = recording_id
    tool_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    failed_stage: Mapped[str] = mapped_column(String(20))  # "pm"|"programmer"|"trial"
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )  # active|retrying|resolved|dismissed
    retry_count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<TeachingFailureRecord(record_id={self.record_id!r}, workflow_id={self.workflow_id!r}, status={self.status!r})>"


class ToolSuggestionHistory(Base):
    """工具化建议历史表（重复模式检测 + 拒绝冷却）"""

    __tablename__ = "tool_suggestion_history"

    suggestion_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    task_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    accepted: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    times_seen: Mapped[int] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return f"<ToolSuggestionHistory(suggestion_id={self.suggestion_id!r}, task_pattern={self.task_pattern!r})>"


class AssistantSummary(Base):
    """助理跨会话记忆摘要表"""

    __tablename__ = "assistant_summaries"

    summary_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<AssistantSummary(summary_id={self.summary_id!r}, level={self.level!r})>"

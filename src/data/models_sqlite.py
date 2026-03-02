"""
SQLAlchemy ORM 模型 - SQLite 数据库 (mexemplar.db)

包含：tools, task_executions, conversations, app_settings, user_preferences
"""

from datetime import datetime
from typing import Optional, Any
from sqlalchemy import String, Integer, Text, DateTime, Boolean, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


class Tool(Base):
    """工具定义表"""
    __tablename__ = "tools"

    tool_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, server_default='[]')
    steps: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, server_default='[]')

    # 代码执行相关字段
    execution_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    code_language: Mapped[str] = mapped_column(String(20), default="python")
    code_version: Mapped[str] = mapped_column(String(20), default="1.0")
    execution_strategy: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # 意图和试用相关字段
    source_intent_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    trial_count: Mapped[int] = mapped_column(Integer, default=0)
    pending_tool_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

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
            source_intent_id=data.get("source_intent_id"),
            source=data.get("source", "manual"),
            trial_count=data.get("trial_count", 0),
            pending_tool_id=data.get("pending_tool_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


class TaskExecution(Base):
    """任务执行记录表"""
    __tablename__ = "task_executions"

    execution_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(50))
    parameters: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # pending, running, completed, failed
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    execution_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<TaskExecution(execution_id={self.execution_id!r}, status={self.status!r})>"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskExecution":
        """从字典创建 TaskExecution 对象（兼容旧代码）"""
        return cls(
            execution_id=data.get("execution_id"),
            tool_id=data.get("tool_id"),
            parameters=data.get("parameters"),
            status=data.get("status"),
            result=data.get("result"),
            error_message=data.get("error_message"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            execution_log=data.get("execution_log"),
        )


class Conversation(Base):
    """对话历史表"""
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    user_message: Mapped[str] = mapped_column(Text)
    assistant_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    parameters_extracted: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    def __repr__(self) -> str:
        return f"<Conversation(conversation_id={self.conversation_id!r})>"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        """从字典创建 Conversation 对象（兼容旧代码）"""
        return cls(
            conversation_id=data.get("conversation_id"),
            user_message=data.get("user_message"),
            assistant_response=data.get("assistant_response"),
            tool_used=data.get("tool_used"),
            parameters_extracted=data.get("parameters_extracted"),
            timestamp=data.get("timestamp"),
        )


class AppSetting(Base):
    """应用配置表（运行时配置）"""
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<AppSetting(key={self.key!r}, value={self.value!r})>"


class UserPreference(Base):
    """用户偏好表"""
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True, default="default")
    theme: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    auto_save: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<UserPreference(user_id={self.user_id!r}, theme={self.theme!r})>"


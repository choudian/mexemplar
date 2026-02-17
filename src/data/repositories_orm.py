"""
数据访问层（DAO/Repository）- 使用 SQLAlchemy ORM

提供对数据库表的 CRUD 操作
"""

import logging
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from .sqlalchemy_manager import get_sqlalchemy_manager
from .models_sqlite import Tool, TaskExecution, Conversation

logger = logging.getLogger(__name__)


class ToolRepository:
    """工具定义仓库（使用 SQLAlchemy ORM）"""

    def __init__(self, session: Optional[Session] = None):
        """
        初始化工具仓库

        Args:
            session: SQLAlchemy 会话，如果为 None 则使用全局会话
        """
        if session is None:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            self.session = manager.get_session()
        else:
            self.session = session

    def create(self, tool: Tool) -> Tool:
        """创建工具"""
        try:
            self.session.add(tool)
            self.session.commit()
            self.session.refresh(tool)
            logger.info(f"工具已创建: {tool.tool_name} ({tool.tool_id})")
            return tool
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建工具失败: {e}")
            raise

    def get_by_id(self, tool_id: str) -> Optional[Tool]:
        """根据ID获取工具"""
        return self.session.query(Tool).filter(Tool.tool_id == tool_id).first()

    def get_all(self) -> List[Tool]:
        """获取所有工具"""
        return self.session.query(Tool).order_by(Tool.created_at.desc()).all()

    def update(self, tool: Tool) -> Tool:
        """更新工具"""
        try:
            tool.updated_at = datetime.now()
            self.session.commit()
            self.session.refresh(tool)
            logger.info(f"工具已更新: {tool.tool_name} ({tool.tool_id})")
            return tool
        except Exception as e:
            self.session.rollback()
            logger.error(f"更新工具失败: {e}")
            raise

    def delete(self, tool_id: str) -> bool:
        """删除工具"""
        try:
            tool = self.get_by_id(tool_id)
            if tool:
                self.session.delete(tool)
                self.session.commit()
                logger.info(f"工具已删除: {tool_id}")
                return True
            return False
        except Exception as e:
            self.session.rollback()
            logger.error(f"删除工具失败: {e}")
            raise

    def search(self, keyword: str) -> List[Tool]:
        """搜索工具（按名称或描述）"""
        return (
            self.session.query(Tool)
            .filter(
                (Tool.tool_name.contains(keyword)) | (Tool.description.contains(keyword))
            )
            .order_by(Tool.created_at.desc())
            .all()
        )


class TaskExecutionRepository:
    """任务执行记录仓库（使用 SQLAlchemy ORM）"""

    def __init__(self, session: Optional[Session] = None):
        """初始化任务执行仓库"""
        if session is None:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            self.session = manager.get_session()
        else:
            self.session = session

    def create(self, execution: TaskExecution) -> TaskExecution:
        """创建执行记录"""
        try:
            if execution.started_at is None:
                execution.started_at = datetime.now()

            self.session.add(execution)
            self.session.commit()
            self.session.refresh(execution)
            logger.info(f"执行记录已创建: {execution.execution_id}")
            return execution
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建执行记录失败: {e}")
            raise

    def get_by_id(self, execution_id: str) -> Optional[TaskExecution]:
        """根据ID获取执行记录"""
        return (
            self.session.query(TaskExecution)
            .filter(TaskExecution.execution_id == execution_id)
            .first()
        )

    def get_by_tool_id(self, tool_id: str, limit: int = 100) -> List[TaskExecution]:
        """获取指定工具的执行记录"""
        return (
            self.session.query(TaskExecution)
            .filter(TaskExecution.tool_id == tool_id)
            .order_by(TaskExecution.started_at.desc())
            .limit(limit)
            .all()
        )

    def update(self, execution: TaskExecution) -> TaskExecution:
        """更新执行记录"""
        try:
            self.session.commit()
            self.session.refresh(execution)
            logger.info(f"执行记录已更新: {execution.execution_id}")
            return execution
        except Exception as e:
            self.session.rollback()
            logger.error(f"更新执行记录失败: {e}")
            raise

    def get_by_status(self, status: str, limit: int = 100) -> List[TaskExecution]:
        """根据状态获取执行记录"""
        return (
            self.session.query(TaskExecution)
            .filter(TaskExecution.status == status)
            .order_by(TaskExecution.started_at.desc())
            .limit(limit)
            .all()
        )


class ConversationRepository:
    """对话历史仓库（使用 SQLAlchemy ORM）"""

    def __init__(self, session: Optional[Session] = None):
        """初始化对话仓库"""
        if session is None:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            self.session = manager.get_session()
        else:
            self.session = session

    def create(self, conversation: Conversation) -> Conversation:
        """创建对话记录"""
        try:
            if conversation.timestamp is None:
                conversation.timestamp = datetime.now()

            self.session.add(conversation)
            self.session.commit()
            self.session.refresh(conversation)
            logger.info(f"对话记录已创建: {conversation.conversation_id}")
            return conversation
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建对话记录失败: {e}")
            raise

    def get_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """根据ID获取对话记录"""
        return (
            self.session.query(Conversation)
            .filter(Conversation.conversation_id == conversation_id)
            .first()
        )

    def get_recent(self, limit: int = 100) -> List[Conversation]:
        """获取最近的对话记录"""
        return (
            self.session.query(Conversation)
            .order_by(Conversation.timestamp.desc())
            .limit(limit)
            .all()
        )

    def get_by_tool(self, tool_id: str, limit: int = 100) -> List[Conversation]:
        """获取使用指定工具的对话记录"""
        return (
            self.session.query(Conversation)
            .filter(Conversation.tool_used == tool_id)
            .order_by(Conversation.timestamp.desc())
            .limit(limit)
            .all()
        )

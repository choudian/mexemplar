"""
数据访问层（DAO/Repository）

提供对数据库表的CRUD操作
内部使用 SQLAlchemy ORM 实现，但对外提供统一接口
"""

import logging
from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session as SQLAlchemySession
from sqlalchemy import and_, func
import uuid

from .sqlalchemy_manager import get_sqlalchemy_manager
from .models_sqlite import (
    Base, Tool, TaskExecution, Conversation,
    Session, Message, WorkflowTransition
)

logger = logging.getLogger(__name__)


class ToolRepository:
    """工具定义仓库"""

    def __init__(self, session: Optional[SQLAlchemySession] = None):
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
    """任务执行记录仓库"""

    def __init__(self, session: Optional[SQLAlchemySession] = None):
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
    """对话历史仓库"""

    def __init__(self, session: Optional[SQLAlchemySession] = None):
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


# ===== 新增：SessionRepository =====

class SessionRepository:
    """会话 Repository"""

    def __init__(self, session: Optional[SQLAlchemySession] = None):
        """
        初始化会话仓库

        Args:
            session: SQLAlchemy 会话，如果为 None 则使用全局会话
        """
        if session is None:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            self.session = manager.get_session()
        else:
            self.session = session

    def create(self, model: Session) -> Session:
        """创建会话"""
        try:
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
            logger.info(f"会话已创建: {model.session_id}")
            return model
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建会话失败: {e}")
            raise

    def get_by_id(self, session_id: str) -> Optional[Session]:
        """根据 ID 获取会话"""
        return self.session.query(Session).filter(
            Session.session_id == session_id
        ).first()

    def get_by_workflow(self, workflow_id: str) -> List[Session]:
        """获取指定工作流的所有会话"""
        return self.session.query(Session).filter(
            Session.workflow_id == workflow_id
        ).order_by(Session.created_at).all()

    def update_status(self, session_id: str, status: str):
        """更新会话状态"""
        model = self.session.query(Session).filter(
            Session.session_id == session_id
        ).first()
        if model:
            model.status = status
            self.session.commit()
            logger.debug(f"会话 {session_id} 状态更新为 {status}")

    def get_status(self, session_id: str) -> Optional[str]:
        """获取会话状态"""
        model = self.get_by_id(session_id)
        return model.status if model else None


# ===== 新增：MessageRepository =====

class MessageRepository:
    """消息 Repository"""

    def __init__(self, session: Optional[SQLAlchemySession] = None):
        """初始化消息仓库"""
        if session is None:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            self.session = manager.get_session()
        else:
            self.session = session

    def create(self, model: Message) -> Message:
        """创建消息"""
        try:
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
            logger.debug(f"消息已创建: {model.message_id}")
            return model
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建消息失败: {e}")
            raise

    def get_by_id(self, message_id: str) -> Optional[Message]:
        """根据 ID 获取消息"""
        return self.session.query(Message).filter(
            Message.message_id == message_id
        ).first()

    def get_first(self, session_id: str) -> Optional[Message]:
        """获取会话的第一条消息（最小序列号）"""
        return self.session.query(Message).filter(
            Message.session_id == session_id
        ).order_by(Message.sequence.asc()).first()

    def get_context(self, session_id: str) -> List[Message]:
        """获取会话上下文（非归档消息，按序列排序）"""
        return self.session.query(Message).filter(
            and_(
                Message.session_id == session_id,
                Message.is_archived.is_(False)
            )
        ).order_by(Message.sequence).all()

    def get_all(self, session_id: str) -> List[Message]:
        """获取会话的所有消息"""
        return self.session.query(Message).filter(
            Message.session_id == session_id
        ).order_by(Message.sequence).all()

    def get_next_sequence(self, session_id: str) -> int:
        """获取下一条消息的序列号"""
        max_seq = self.session.query(func.max(Message.sequence)).filter(
            Message.session_id == session_id
        ).scalar()
        return (max_seq or 0) + 1

    def mark_archived(self, session_id: str, from_seq: int, to_seq: int):
        """归档指定范围的消息"""
        self.session.query(Message).filter(
            and_(
                Message.session_id == session_id,
                Message.sequence >= from_seq,
                Message.sequence <= to_seq
            )
        ).update({"is_archived": True}, synchronize_session=False)
        self.session.commit()
        logger.debug(f"会话 {session_id} 消息 {from_seq}-{to_seq} 已归档")

    def bulk_copy(
        self,
        from_session_id: str,
        to_session_id: str,
        up_to_sequence: int
    ) -> List[Message]:
        """批量复制消息（用于 Fork 操作）"""
        # 查询源消息
        source_models = self.session.query(Message).filter(
            and_(
                Message.session_id == from_session_id,
                Message.sequence <= up_to_sequence
            )
        ).order_by(Message.sequence).all()

        # 复制并创建新消息
        new_messages = []
        for model in source_models:
            new_model = Message(
                message_id=str(uuid.uuid4()),
                session_id=to_session_id,
                sequence=model.sequence,
                role=model.role,
                content=model.content,
                message_type=model.message_type,
                tool_call_id=model.tool_call_id,
                tool_name=model.tool_name,
                tool_calls=model.tool_calls,
                compressed_range=model.compressed_range,
                is_archived=False,
            )
            new_messages.append(new_model)

        # 批量插入
        self.session.bulk_save_objects(new_messages)
        self.session.commit()
        logger.debug(f"从 {from_session_id} 复制 {len(new_messages)} 条消息到 {to_session_id}")

        # 刷新并返回
        for msg in new_messages:
            self.session.refresh(msg)

        return new_messages


# ===== 新增：WorkflowTransitionRepository =====

class WorkflowTransitionRepository:
    """工作流交接 Repository"""

    def __init__(self, session: Optional[SQLAlchemySession] = None):
        """初始化交接记录仓库"""
        if session is None:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            self.session = manager.get_session()
        else:
            self.session = session

    def create(self, model: WorkflowTransition) -> WorkflowTransition:
        """创建交接记录"""
        try:
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
            logger.debug(f"交接记录已创建: {model.transition_id}")
            return model
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建交接记录失败: {e}")
            raise

    def get_by_id(self, transition_id: str) -> Optional[WorkflowTransition]:
        """根据 ID 获取交接记录"""
        return self.session.query(WorkflowTransition).filter(
            WorkflowTransition.transition_id == transition_id
        ).first()

    def get_by_workflow(self, workflow_id: str) -> List[WorkflowTransition]:
        """获取指定工作流的所有交接记录"""
        return self.session.query(WorkflowTransition).filter(
            WorkflowTransition.workflow_id == workflow_id
        ).order_by(WorkflowTransition.created_at).all()

"""
数据访问层（DAO/Repository）

提供对数据库表的CRUD操作
"""

import sqlite3
import json
import logging
from typing import List, Optional
from datetime import datetime

from .database import DatabaseManager
from .models import Tool, TaskExecution, Conversation

logger = logging.getLogger(__name__)


class ToolRepository:
    """工具定义仓库"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def create(self, tool: Tool) -> Tool:
        """创建工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO tools (tool_id, tool_name, description, parameters, steps, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    tool.tool_id,
                    tool.tool_name,
                    tool.description,
                    json.dumps(tool.parameters, ensure_ascii=False),
                    json.dumps(tool.steps, ensure_ascii=False),
                    datetime.now(),
                    datetime.now(),
                ),
            )
            conn.commit()
            logger.info(f"工具已创建: {tool.tool_name} ({tool.tool_id})")
            return tool
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"创建工具失败: {e}")
            raise

    def get_by_id(self, tool_id: str) -> Optional[Tool]:
        """根据ID获取工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM tools WHERE tool_id = ?", (tool_id,))
        row = cursor.fetchone()

        if row:
            return Tool.from_dict(dict(row))
        return None

    def get_all(self) -> List[Tool]:
        """获取所有工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM tools ORDER BY created_at DESC")
        rows = cursor.fetchall()

        return [Tool.from_dict(dict(row)) for row in rows]

    def update(self, tool: Tool) -> Tool:
        """更新工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE tools
                SET tool_name = ?, description = ?, parameters = ?, steps = ?, updated_at = ?
                WHERE tool_id = ?
            """,
                (
                    tool.tool_name,
                    tool.description,
                    json.dumps(tool.parameters, ensure_ascii=False),
                    json.dumps(tool.steps, ensure_ascii=False),
                    datetime.now(),
                    tool.tool_id,
                ),
            )
            conn.commit()
            logger.info(f"工具已更新: {tool.tool_name} ({tool.tool_id})")
            return tool
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"更新工具失败: {e}")
            raise

    def delete(self, tool_id: str) -> bool:
        """删除工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM tools WHERE tool_id = ?", (tool_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"工具已删除: {tool_id}")
            return deleted
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"删除工具失败: {e}")
            raise

    def search(self, keyword: str) -> List[Tool]:
        """搜索工具（按名称或描述）"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        search_pattern = f"%{keyword}%"
        cursor.execute(
            """
            SELECT * FROM tools
            WHERE tool_name LIKE ? OR description LIKE ?
            ORDER BY created_at DESC
        """,
            (search_pattern, search_pattern),
        )
        rows = cursor.fetchall()

        return [Tool.from_dict(dict(row)) for row in rows]


class TaskExecutionRepository:
    """任务执行记录仓库"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def create(self, execution: TaskExecution) -> TaskExecution:
        """创建执行记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO task_executions 
                (execution_id, tool_id, parameters, status, result, error_message, 
                 started_at, finished_at, execution_log)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    execution.execution_id,
                    execution.tool_id,
                    (
                        json.dumps(execution.parameters, ensure_ascii=False)
                        if execution.parameters
                        else None
                    ),
                    execution.status,
                    json.dumps(execution.result, ensure_ascii=False) if execution.result else None,
                    execution.error_message,
                    execution.started_at or datetime.now(),
                    execution.finished_at,
                    execution.execution_log,
                ),
            )
            conn.commit()
            logger.info(f"执行记录已创建: {execution.execution_id}")
            return execution
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"创建执行记录失败: {e}")
            raise

    def get_by_id(self, execution_id: str) -> Optional[TaskExecution]:
        """根据ID获取执行记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM task_executions WHERE execution_id = ?", (execution_id,))
        row = cursor.fetchone()

        if row:
            return TaskExecution.from_dict(dict(row))
        return None

    def get_by_tool_id(self, tool_id: str, limit: int = 100) -> List[TaskExecution]:
        """获取指定工具的执行记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM task_executions
            WHERE tool_id = ?
            ORDER BY started_at DESC
            LIMIT ?
        """,
            (tool_id, limit),
        )
        rows = cursor.fetchall()

        return [TaskExecution.from_dict(dict(row)) for row in rows]

    def update(self, execution: TaskExecution) -> TaskExecution:
        """更新执行记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE task_executions
                SET status = ?, result = ?, error_message = ?, finished_at = ?, execution_log = ?
                WHERE execution_id = ?
            """,
                (
                    execution.status,
                    json.dumps(execution.result, ensure_ascii=False) if execution.result else None,
                    execution.error_message,
                    execution.finished_at,
                    execution.execution_log,
                    execution.execution_id,
                ),
            )
            conn.commit()
            logger.info(f"执行记录已更新: {execution.execution_id}")
            return execution
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"更新执行记录失败: {e}")
            raise

    def get_by_status(self, status: str, limit: int = 100) -> List[TaskExecution]:
        """根据状态获取执行记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM task_executions
            WHERE status = ?
            ORDER BY started_at DESC
            LIMIT ?
        """,
            (status, limit),
        )
        rows = cursor.fetchall()

        return [TaskExecution.from_dict(dict(row)) for row in rows]


class ConversationRepository:
    """对话历史仓库"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def create(self, conversation: Conversation) -> Conversation:
        """创建对话记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO conversations 
                (conversation_id, user_message, assistant_response, tool_used, parameters_extracted, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    conversation.conversation_id,
                    conversation.user_message,
                    conversation.assistant_response,
                    conversation.tool_used,
                    (
                        json.dumps(conversation.parameters_extracted, ensure_ascii=False)
                        if conversation.parameters_extracted
                        else None
                    ),
                    conversation.timestamp or datetime.now(),
                ),
            )
            conn.commit()
            logger.info(f"对话记录已创建: {conversation.conversation_id}")
            return conversation
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"创建对话记录失败: {e}")
            raise

    def get_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """根据ID获取对话记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,))
        row = cursor.fetchone()

        if row:
            return Conversation.from_dict(dict(row))
        return None

    def get_recent(self, limit: int = 100) -> List[Conversation]:
        """获取最近的对话记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM conversations
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (limit,),
        )
        rows = cursor.fetchall()

        return [Conversation.from_dict(dict(row)) for row in rows]

    def get_by_tool(self, tool_id: str, limit: int = 100) -> List[Conversation]:
        """获取使用指定工具的对话记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM conversations
            WHERE tool_used = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """,
            (tool_id, limit),
        )
        rows = cursor.fetchall()

        return [Conversation.from_dict(dict(row)) for row in rows]

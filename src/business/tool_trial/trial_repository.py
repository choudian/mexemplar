"""
Tool Trial Repository

提供工具试用数据的 CRUD 操作
"""

import sqlite3
import json
import logging
from typing import List, Optional
from datetime import datetime

from src.data.database import DatabaseManager
from .trial_models import PendingTool, PendingToolStatus, ToolTrial, TrialStatus

logger = logging.getLogger(__name__)


class PendingToolRepository:
    """待试用工具仓库"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def create(self, pending_tool: PendingTool) -> PendingTool:
        """创建待试用工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO pending_tools
                (pending_tool_id, intent_id, tool_name, tool_description,
                 execution_code, code_language, execution_strategy, parameters,
                 status, trial_count, max_trials, last_trial_result, last_error,
                 created_at, updated_at, promoted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    pending_tool.pending_tool_id,
                    pending_tool.intent_id,
                    pending_tool.tool_name,
                    pending_tool.tool_description,
                    pending_tool.execution_code,
                    pending_tool.code_language,
                    pending_tool.execution_strategy,
                    json.dumps(pending_tool.parameters, ensure_ascii=False),
                    (
                        pending_tool.status.value
                        if isinstance(pending_tool.status, PendingToolStatus)
                        else pending_tool.status
                    ),
                    pending_tool.trial_count,
                    pending_tool.max_trials,
                    pending_tool.last_trial_result,
                    pending_tool.last_error,
                    pending_tool.created_at or datetime.now(),
                    pending_tool.updated_at or datetime.now(),
                    pending_tool.promoted_at,
                ),
            )
            conn.commit()
            logger.info(f"待试用工具已创建: {pending_tool.pending_tool_id}")
            return pending_tool
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"创建待试用工具失败: {e}")
            raise

    def get_by_id(self, pending_tool_id: str) -> Optional[PendingTool]:
        """根据ID获取待试用工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM pending_tools WHERE pending_tool_id = ?", (pending_tool_id,))
        row = cursor.fetchone()

        if row:
            return PendingTool.from_dict(dict(row))
        return None

    def get_by_intent_id(self, intent_id: str) -> List[PendingTool]:
        """根据意图ID获取待试用工具列表"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM pending_tools
            WHERE intent_id = ?
            ORDER BY created_at DESC
        """,
            (intent_id,),
        )
        rows = cursor.fetchall()

        return [PendingTool.from_dict(dict(row)) for row in rows]

    def get_by_status(self, status: PendingToolStatus, limit: int = 100) -> List[PendingTool]:
        """根据状态获取待试用工具列表"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        status_value = status.value if isinstance(status, PendingToolStatus) else status
        cursor.execute(
            """
            SELECT * FROM pending_tools
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (status_value, limit),
        )
        rows = cursor.fetchall()

        return [PendingTool.from_dict(dict(row)) for row in rows]

    def get_all(self, limit: int = 100) -> List[PendingTool]:
        """获取所有待试用工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM pending_tools
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        rows = cursor.fetchall()

        return [PendingTool.from_dict(dict(row)) for row in rows]

    def update(self, pending_tool: PendingTool) -> PendingTool:
        """更新待试用工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE pending_tools
                SET tool_name = ?, tool_description = ?, execution_code = ?,
                    code_language = ?, execution_strategy = ?, parameters = ?,
                    status = ?, trial_count = ?, max_trials = ?,
                    last_trial_result = ?, last_error = ?, updated_at = ?, promoted_at = ?
                WHERE pending_tool_id = ?
            """,
                (
                    pending_tool.tool_name,
                    pending_tool.tool_description,
                    pending_tool.execution_code,
                    pending_tool.code_language,
                    pending_tool.execution_strategy,
                    json.dumps(pending_tool.parameters, ensure_ascii=False),
                    (
                        pending_tool.status.value
                        if isinstance(pending_tool.status, PendingToolStatus)
                        else pending_tool.status
                    ),
                    pending_tool.trial_count,
                    pending_tool.max_trials,
                    pending_tool.last_trial_result,
                    pending_tool.last_error,
                    pending_tool.updated_at or datetime.now(),
                    pending_tool.promoted_at,
                    pending_tool.pending_tool_id,
                ),
            )
            conn.commit()
            logger.info(f"待试用工具已更新: {pending_tool.pending_tool_id}")
            return pending_tool
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"更新待试用工具失败: {e}")
            raise

    def delete(self, pending_tool_id: str) -> bool:
        """删除待试用工具"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM pending_tools WHERE pending_tool_id = ?", (pending_tool_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"待试用工具已删除: {pending_tool_id}")
            return deleted
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"删除待试用工具失败: {e}")
            raise


class ToolTrialRepository:
    """工具试用记录仓库"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def create(self, trial: ToolTrial) -> ToolTrial:
        """创建试用记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO tool_trials
                (trial_id, pending_tool_id, trial_data, status, result,
                 error_message, error_type, execution_log, execution_steps,
                 fix_attempted, fix_successful, fixed_code, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    trial.trial_id,
                    trial.pending_tool_id,
                    json.dumps(trial.trial_data, ensure_ascii=False),
                    trial.status.value if isinstance(trial.status, TrialStatus) else trial.status,
                    json.dumps(trial.result, ensure_ascii=False) if trial.result else None,
                    trial.error_message,
                    trial.error_type,
                    trial.execution_log,
                    json.dumps(trial.execution_steps, ensure_ascii=False),
                    int(trial.fix_attempted),
                    int(trial.fix_successful),
                    trial.fixed_code,
                    trial.started_at or datetime.now(),
                    trial.finished_at,
                ),
            )
            conn.commit()
            logger.info(f"试用记录已创建: {trial.trial_id}")
            return trial
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"创建试用记录失败: {e}")
            raise

    def get_by_id(self, trial_id: str) -> Optional[ToolTrial]:
        """根据ID获取试用记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM tool_trials WHERE trial_id = ?", (trial_id,))
        row = cursor.fetchone()

        if row:
            return ToolTrial.from_dict(dict(row))
        return None

    def get_by_pending_tool_id(
        self, pending_tool_id: str, limit: int = 10
    ) -> List[ToolTrial]:
        """根据待试用工具ID获取试用记录列表"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM tool_trials
            WHERE pending_tool_id = ?
            ORDER BY started_at DESC
            LIMIT ?
        """,
            (pending_tool_id, limit),
        )
        rows = cursor.fetchall()

        return [ToolTrial.from_dict(dict(row)) for row in rows]

    def get_by_status(self, status: TrialStatus, limit: int = 100) -> List[ToolTrial]:
        """根据状态获取试用记录列表"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        status_value = status.value if isinstance(status, TrialStatus) else status
        cursor.execute(
            """
            SELECT * FROM tool_trials
            WHERE status = ?
            ORDER BY started_at DESC
            LIMIT ?
        """,
            (status_value, limit),
        )
        rows = cursor.fetchall()

        return [ToolTrial.from_dict(dict(row)) for row in rows]

    def update(self, trial: ToolTrial) -> ToolTrial:
        """更新试用记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE tool_trials
                SET trial_data = ?, status = ?, result = ?, error_message = ?,
                    error_type = ?, execution_log = ?, execution_steps = ?,
                    fix_attempted = ?, fix_successful = ?, fixed_code = ?,
                    started_at = ?, finished_at = ?
                WHERE trial_id = ?
            """,
                (
                    json.dumps(trial.trial_data, ensure_ascii=False),
                    trial.status.value if isinstance(trial.status, TrialStatus) else trial.status,
                    json.dumps(trial.result, ensure_ascii=False) if trial.result else None,
                    trial.error_message,
                    trial.error_type,
                    trial.execution_log,
                    json.dumps(trial.execution_steps, ensure_ascii=False),
                    int(trial.fix_attempted),
                    int(trial.fix_successful),
                    trial.fixed_code,
                    trial.started_at,
                    trial.finished_at,
                    trial.trial_id,
                ),
            )
            conn.commit()
            logger.info(f"试用记录已更新: {trial.trial_id}")
            return trial
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"更新试用记录失败: {e}")
            raise

    def delete(self, trial_id: str) -> bool:
        """删除试用记录"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM tool_trials WHERE trial_id = ?", (trial_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"试用记录已删除: {trial_id}")
            return deleted
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"删除试用记录失败: {e}")
            raise

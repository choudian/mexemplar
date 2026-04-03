"""
TrialDataTemplate Repository

试用数据模板的数据访问层
"""

import logging
import sqlite3
import json
from typing import List, Optional
from datetime import datetime

from src.data.database import DatabaseManager
from src.business.tool_trial.trial_models import TrialDataTemplate

logger = logging.getLogger(__name__)


class TrialDataTemplateRepository:
    """
    试用数据模板仓库

    负责试用数据模板的 CRUD 操作
    """

    def __init__(self, db_manager: DatabaseManager):
        """
        初始化仓库

        Args:
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager

    def create(self, template: TrialDataTemplate) -> TrialDataTemplate:
        """
        创建试用数据模板

        Args:
            template: 试用数据模板

        Returns:
            创建的试用数据模板

        Raises:
            sqlite3.Error: 数据库错误
        """
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            now = datetime.now()
            template.created_at = now
            template.updated_at = now

            cursor.execute(
                """
                INSERT INTO trial_data_templates
                (template_id, pending_tool_id, template_name, template_data,
                 is_real_data, description, data_source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    template.template_id,
                    template.pending_tool_id,
                    template.template_name,
                    template.to_dict()["template_data"],
                    1 if template.is_real_data else 0,
                    template.description,
                    template.data_source,
                    now.timestamp(),
                    now.timestamp(),
                ),
            )

            conn.commit()
            logger.info(f"创建试用数据模板: {template.template_id}")
            return template

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"创建试用数据模板失败: {e}")
            raise

    def get_by_id(self, template_id: str) -> Optional[TrialDataTemplate]:
        """
        根据 ID 获取试用数据模板

        Args:
            template_id: 模板 ID

        Returns:
            试用数据模板，如果不存在则返回 None
        """
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT template_id, pending_tool_id, template_name, template_data,
                       is_real_data, description, data_source, created_at, updated_at
                FROM trial_data_templates
                WHERE template_id = ?
            """,
                (template_id,),
            )

            row = cursor.fetchone()
            if not row:
                return None

            return self._row_to_template(row)

        except sqlite3.Error as e:
            logger.error(f"获取试用数据模板失败: {e}")
            return None

    def get_by_pending_tool_id(
        self, pending_tool_id: str, limit: int = 100
    ) -> List[TrialDataTemplate]:
        """
        获取指定待试用工具的所有数据模板

        Args:
            pending_tool_id: 待试用工具 ID
            limit: 最大返回数量

        Returns:
            试用数据模板列表
        """
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT template_id, pending_tool_id, template_name, template_data,
                       is_real_data, description, data_source, created_at, updated_at
                FROM trial_data_templates
                WHERE pending_tool_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (pending_tool_id, limit),
            )

            rows = cursor.fetchall()
            return [self._row_to_template(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"获取试用数据模板列表失败: {e}")
            return []

    def get_real_data_templates(
        self, pending_tool_id: str
    ) -> List[TrialDataTemplate]:
        """
        获取指定待试用工具的真实数据模板

        Args:
            pending_tool_id: 待试用工具 ID

        Returns:
            真实数据模板列表
        """
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT template_id, pending_tool_id, template_name, template_data,
                       is_real_data, description, data_source, created_at, updated_at
                FROM trial_data_templates
                WHERE pending_tool_id = ? AND is_real_data = 1
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (pending_tool_id, 100),
            )

            rows = cursor.fetchall()
            return [self._row_to_template(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"获取真实数据模板失败: {e}")
            return []

    def get_all(self, limit: int = 100) -> List[TrialDataTemplate]:
        """
        获取所有试用数据模板

        Args:
            limit: 最大返回数量

        Returns:
            试用数据模板列表
        """
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT template_id, pending_tool_id, template_name, template_data,
                       is_real_data, description, data_source, created_at, updated_at
                FROM trial_data_templates
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )

            rows = cursor.fetchall()
            return [self._row_to_template(row) for row in rows]

        except sqlite3.Error as e:
            logger.error(f"获取所有试用数据模板失败: {e}")
            return []

    def update(self, template: TrialDataTemplate) -> TrialDataTemplate:
        """
        更新试用数据模板

        Args:
            template: 试用数据模板

        Returns:
            更新后的试用数据模板

        Raises:
            ValueError: 如果模板不存在
            sqlite3.Error: 数据库错误
        """
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            template.updated_at = datetime.now()

            cursor.execute(
                """
                UPDATE trial_data_templates
                SET template_name = ?,
                    template_data = ?,
                    is_real_data = ?,
                    description = ?,
                    data_source = ?,
                    updated_at = ?
                WHERE template_id = ?
            """,
                (
                    template.template_name,
                    template.to_dict()["template_data"],
                    1 if template.is_real_data else 0,
                    template.description,
                    template.data_source,
                    template.updated_at.timestamp(),
                    template.template_id,
                ),
            )

            if cursor.rowcount == 0:
                raise ValueError(f"试用数据模板不存在: {template.template_id}")

            conn.commit()
            logger.info(f"更新试用数据模板: {template.template_id}")
            return template

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"更新试用数据模板失败: {e}")
            raise

    def delete(self, template_id: str) -> bool:
        """
        删除试用数据模板

        Args:
            template_id: 模板 ID

        Returns:
            是否删除成功
        """
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "DELETE FROM trial_data_templates WHERE template_id = ?",
                (template_id,),
            )

            conn.commit()
            success = cursor.rowcount > 0

            if success:
                logger.info(f"删除试用数据模板: {template_id}")
            else:
                logger.warning(f"试用数据模板不存在，无法删除: {template_id}")

            return success

        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"删除试用数据模板失败: {e}")
            return False

    def _row_to_template(self, row) -> TrialDataTemplate:
        """将数据库行转换为 TrialDataTemplate 对象"""
        # 解析 template_data JSON 字符串
        template_data_json = row[3]
        template_data = {}
        if template_data_json:
            try:
                template_data = json.loads(template_data_json) if template_data_json else {}
            except json.JSONDecodeError:
                logger.warning(f"解析 template_data JSON 失败: {template_data_json}")
                template_data = {}

        return TrialDataTemplate(
            template_id=row[0],
            pending_tool_id=row[1],
            template_name=row[2],
            template_data=template_data,
            is_real_data=bool(row[4]),
            description=row[5],
            data_source=row[6],
            created_at=datetime.fromtimestamp(row[7]) if row[7] else None,
            updated_at=datetime.fromtimestamp(row[8]) if row[8] else None,
        )

"""
TrialDataTemplate Repository

试用数据模板的数据访问层
"""

import logging
import sqlite3
import json
from typing import List, Optional
from datetime import datetime

from src.data.raw_repository import RawSQLRepository
from src.business.tool_trial.trial_models import TrialDataTemplate

logger = logging.getLogger(__name__)


class TrialDataTemplateRepository(RawSQLRepository):
    """
    试用数据模板仓库

    负责试用数据模板的 CRUD 操作
    """

    def __init__(self, db_manager):
        """
        初始化仓库

        Args:
            db_manager: 数据库管理器
        """
        super().__init__(db_manager)

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
        now = datetime.now()
        template.created_at = now
        template.updated_at = now

        self._execute(
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
        logger.info(f"创建试用数据模板: {template.template_id}")
        return template

    def get_by_id(self, template_id: str) -> Optional[TrialDataTemplate]:
        """
        根据 ID 获取试用数据模板

        Args:
            template_id: 模板 ID

        Returns:
            试用数据模板，如果不存在则返回 None
        """
        try:
            row = self._fetch_one(
                """
                SELECT template_id, pending_tool_id, template_name, template_data,
                       is_real_data, description, data_source, created_at, updated_at
                FROM trial_data_templates
                WHERE template_id = ?
            """,
                (template_id,),
            )
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
        try:
            rows = self._fetch_all(
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
        try:
            rows = self._fetch_all(
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
        try:
            rows = self._fetch_all(
                """
                SELECT template_id, pending_tool_id, template_name, template_data,
                       is_real_data, description, data_source, created_at, updated_at
                FROM trial_data_templates
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )
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
        template.updated_at = datetime.now()

        cursor = self._execute(
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

        logger.info(f"更新试用数据模板: {template.template_id}")
        return template

    def delete(self, template_id: str) -> bool:
        """
        删除试用数据模板

        Args:
            template_id: 模板 ID

        Returns:
            是否删除成功
        """
        cursor = self._execute(
            "DELETE FROM trial_data_templates WHERE template_id = ?",
            (template_id,),
        )
        success = cursor.rowcount > 0

        if success:
            logger.info(f"删除试用数据模板: {template_id}")
        else:
            logger.warning(f"试用数据模板不存在，无法删除: {template_id}")

        return success

    def _row_to_template(self, row) -> TrialDataTemplate:
        """将数据库行转换为 TrialDataTemplate 对象"""
        # row 为 sqlite3.Row 对象，支持列名访问
        template_data_json = row["template_data"]
        template_data = {}
        if template_data_json:
            try:
                template_data = json.loads(template_data_json)
            except json.JSONDecodeError:
                logger.warning(f"解析 template_data JSON 失败: {template_data_json}")
                template_data = {}

        return TrialDataTemplate(
            template_id=row["template_id"],
            pending_tool_id=row["pending_tool_id"],
            template_name=row["template_name"],
            template_data=template_data,
            is_real_data=bool(row["is_real_data"]),
            description=row["description"],
            data_source=row["data_source"],
            created_at=datetime.fromtimestamp(row["created_at"]) if row["created_at"] else None,
            updated_at=datetime.fromtimestamp(row["updated_at"]) if row["updated_at"] else None,
        )

"""
ToolRepository -- 工具定义仓库
"""

import logging
from typing import List, Optional
from datetime import datetime

from ..models_sqlite import Tool
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class ToolRepository(BaseRepository):
    """工具定义仓库"""

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
        escaped = keyword.replace("%", "\\%").replace("_", "\\_")
        return (
            self.session.query(Tool)
            .filter(
                (Tool.tool_name.contains(escaped, escape="\\"))
                | (Tool.description.contains(escaped, escape="\\"))
            )
            .order_by(Tool.created_at.desc())
            .all()
        )

    def get_by_workflow_id(self, workflow_id: str) -> Optional[Tool]:
        """按 workflow_id 查找工具（一个 workflow 对应一个工具）"""
        return self.session.query(Tool).filter(Tool.workflow_id == workflow_id).first()

    def update_trial_success_count(self, tool_id: str, count: int):
        """更新试用成功计数"""
        tool = self.get_by_id(tool_id)
        if tool:
            tool.trial_success_count = count
            self.session.commit()

    def update_status(self, tool_id: str, status: str):
        """更新工具状态（pending / published）"""
        tool = self.get_by_id(tool_id)
        if tool:
            tool.status = status
            self.session.commit()

    def get_published_summaries(self) -> List[dict]:
        """获取已发布工具的摘要信息（仅 tool_id, tool_name, description）"""
        rows = (
            self.session.query(Tool.tool_id, Tool.tool_name, Tool.description)
            .filter(Tool.status == "published")
            .order_by(Tool.created_at.desc())
            .all()
        )
        return [{"tool_id": r[0], "tool_name": r[1], "description": r[2] or ""} for r in rows]

    def search_published(self, query: str) -> List[Tool]:
        """搜索已发布的工具（参数化 LIKE 查询，防注入）"""
        escaped = query.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        return (
            self.session.query(Tool)
            .filter(
                Tool.status == "published",
                (Tool.tool_name.like(pattern, escape="\\"))
                | (Tool.description.like(pattern, escape="\\")),
            )
            .order_by(Tool.created_at.desc())
            .all()
        )

    def get_by_name(self, name: str) -> Optional[Tool]:
        """按工具名称精确查询"""
        return self.session.query(Tool).filter(Tool.tool_name == name).first()

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
    Tool,
    Session,
    Message,
    WorkflowTransition,
    PendingAssistantTask,
    AssistantProfile,
    AssistantSummary,
    ToolSuggestionHistory,
    TeachingFailureRecord,
)

logger = logging.getLogger(__name__)


class BaseRepository:
    """Repository 基类，提供统一的会话初始化"""

    def __init__(self, session: Optional[SQLAlchemySession] = None):
        if session is None:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            self.session = manager.get_session()
        else:
            self.session = session


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
                (Tool.tool_name.contains(escaped, escape="\\")) | (Tool.description.contains(escaped, escape="\\"))
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

    def get_published(self) -> List[Tool]:
        """获取所有已发布的工具"""
        return (
            self.session.query(Tool)
            .filter(Tool.status == "published")
            .order_by(Tool.created_at.desc())
            .all()
        )

    def search_published(self, query: str) -> List[Tool]:
        """搜索已发布的工具（参数化 LIKE 查询，防注入）"""
        escaped = query.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        return (
            self.session.query(Tool)
            .filter(
                Tool.status == "published",
                (Tool.tool_name.like(pattern, escape="\\")) | (Tool.description.like(pattern, escape="\\")),
            )
            .order_by(Tool.created_at.desc())
            .all()
        )

    def get_by_name(self, name: str) -> Optional[Tool]:
        """按工具名称精确查询"""
        return self.session.query(Tool).filter(Tool.tool_name == name).first()



# ===== 新增：SessionRepository =====


class SessionRepository(BaseRepository):
    """会话 Repository"""

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
        return self.session.query(Session).filter(Session.session_id == session_id).first()

    def get_by_workflow(
        self,
        workflow_id: str,
        agent_type: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> List[Session]:
        """获取指定工作流的所有会话"""
        query = self.session.query(Session).filter(Session.workflow_id == workflow_id)
        if agent_type:
            query = query.filter(Session.agent_type == agent_type)
        if order_by == "created_at_desc":
            query = query.order_by(Session.created_at.desc())
        else:
            query = query.order_by(Session.created_at)
        return query.all()

    def update_status(self, session_id: str, status: str):
        """更新会话状态"""
        model = self.session.query(Session).filter(Session.session_id == session_id).first()
        if model:
            model.status = status
            self.session.commit()
            logger.debug(f"会话 {session_id} 状态更新为 {status}")

    def get_status(self, session_id: str) -> Optional[str]:
        """获取会话状态"""
        model = self.get_by_id(session_id)
        return model.status if model else None

    def get_by_agent_type(self, agent_type: str, limit: int = 50) -> List[Session]:
        """获取指定 agent_type 的会话列表，按最近更新排序"""
        return (
            self.session.query(Session)
            .filter(Session.agent_type == agent_type)
            .order_by(Session.updated_at.desc())
            .limit(limit)
            .all()
        )


# ===== 新增：MessageRepository =====


class MessageRepository(BaseRepository):
    """消息 Repository"""

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
        return self.session.query(Message).filter(Message.message_id == message_id).first()

    def get_first(self, session_id: str) -> Optional[Message]:
        """获取会话的第一条消息（最小序列号）"""
        return (
            self.session.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.sequence.asc())
            .first()
        )

    def get_last(self, session_id: str, non_archived: bool = True) -> Optional[Message]:
        """获取会话的最后一条消息（最大序列号）"""
        query = self.session.query(Message).filter(Message.session_id == session_id)
        if non_archived:
            query = query.filter(Message.is_archived.is_(False))
        return query.order_by(Message.sequence.desc()).first()

    def get_context(self, session_id: str) -> List[Message]:
        """获取会话上下文（非归档消息，按序列排序）"""
        return (
            self.session.query(Message)
            .filter(and_(Message.session_id == session_id, Message.is_archived.is_(False)))
            .order_by(Message.sequence)
            .all()
        )

    def get_all(self, session_id: str) -> List[Message]:
        """获取会话的所有消息"""
        return (
            self.session.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.sequence)
            .all()
        )

    # 别名：外部模块（chat_widget, assistant_memory, assistant_tools）统一使用此名称
    get_by_session = get_all

    def get_next_sequence(self, session_id: str) -> int:
        """获取下一条消息的序列号"""
        max_seq = (
            self.session.query(func.max(Message.sequence))
            .filter(Message.session_id == session_id)
            .scalar()
        )
        return (max_seq or 0) + 1

    def mark_archived(self, session_id: str, from_seq: int, to_seq: int):
        """归档指定范围的消息"""
        self.session.query(Message).filter(
            and_(
                Message.session_id == session_id,
                Message.sequence >= from_seq,
                Message.sequence <= to_seq,
            )
        ).update({"is_archived": True}, synchronize_session=False)
        self.session.commit()
        logger.debug(f"会话 {session_id} 消息 {from_seq}-{to_seq} 已归档")

    def update_content(self, message_id: str, content: str):
        """更新消息内容"""
        msg = self.get_by_id(message_id)
        if msg:
            msg.content = content
            self.session.commit()


# ===== 新增：WorkflowTransitionRepository =====


class WorkflowTransitionRepository(BaseRepository):
    """工作流交接 Repository"""

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
        return (
            self.session.query(WorkflowTransition)
            .filter(WorkflowTransition.transition_id == transition_id)
            .first()
        )

    def get_by_workflow(self, workflow_id: str) -> List[WorkflowTransition]:
        """获取指定工作流的所有交接记录"""
        return (
            self.session.query(WorkflowTransition)
            .filter(WorkflowTransition.workflow_id == workflow_id)
            .order_by(WorkflowTransition.created_at)
            .all()
        )

    def get_latest_by_workflow_and_event(
        self,
        workflow_id: str,
        event_type: str,
    ) -> Optional[WorkflowTransition]:
        """按 workflow_id 和 event_type 取最近一条交接记录"""
        return (
            self.session.query(WorkflowTransition)
            .filter(
                WorkflowTransition.workflow_id == workflow_id,
                WorkflowTransition.event_type == event_type,
            )
            .order_by(WorkflowTransition.created_at.desc())
            .first()
        )


class PendingTaskRepository(BaseRepository):
    """助理异步任务队列仓库"""

    def create(self, task: PendingAssistantTask) -> PendingAssistantTask:
        """创建任务"""
        try:
            self.session.add(task)
            self.session.commit()
            self.session.refresh(task)
            logger.info(f"待处理任务已创建: {task.task_id} ({task.task_type})")
            return task
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建待处理任务失败: {e}")
            raise

    def get_by_id(self, task_id: str) -> Optional[PendingAssistantTask]:
        """根据 ID 获取任务"""
        return self.session.query(PendingAssistantTask).filter(
            PendingAssistantTask.task_id == task_id
        ).first()

    def get_pending(self, task_type: Optional[str] = None) -> List[PendingAssistantTask]:
        """获取待处理任务"""
        q = self.session.query(PendingAssistantTask).filter(
            PendingAssistantTask.status == "pending"
        )
        if task_type:
            q = q.filter(PendingAssistantTask.task_type == task_type)
        return q.order_by(PendingAssistantTask.created_at).all()

    def update_status(self, task_id: str, status: str):
        """更新任务状态"""
        task = self.session.query(PendingAssistantTask).filter(
            PendingAssistantTask.task_id == task_id
        ).first()
        if task:
            task.status = status
            self.session.commit()


class AssistantProfileRepository(BaseRepository):
    """助理用户偏好档案仓库"""

    def get_default(self) -> Optional[AssistantProfile]:
        """获取默认 profile"""
        return self.session.query(AssistantProfile).filter(
            AssistantProfile.profile_id == "default"
        ).first()

    def save(self, display_name: str = "", style: str = "", notes: str = "") -> AssistantProfile:
        """保存或更新默认 profile"""
        existing = self.get_default()
        if existing:
            if display_name:
                existing.display_name = display_name
            if style:
                existing.style = style
            if notes:
                existing.notes = notes
            self.session.commit()
            return existing
        else:
            profile = AssistantProfile(
                profile_id="default",
                display_name=display_name or None,
                style=style or None,
                notes=notes or None,
            )
            self.session.add(profile)
            self.session.commit()
            self.session.refresh(profile)
            return profile


class AssistantSummaryRepository(BaseRepository):
    """助理跨会话记忆摘要仓库"""

    def create(self, summary: AssistantSummary) -> AssistantSummary:
        """创建摘要"""
        try:
            self.session.add(summary)
            self.session.commit()
            self.session.refresh(summary)
            return summary
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建摘要失败: {e}")
            raise

    def get_by_summary_id(self, summary_id: str) -> Optional[AssistantSummary]:
        """按 summary_id 查询单条摘要"""
        return (
            self.session.query(AssistantSummary)
            .filter(AssistantSummary.summary_id == summary_id)
            .first()
        )

    def get_by_level(self, level: int, limit: int = 100) -> List[AssistantSummary]:
        """获取指定层级的摘要"""
        return (
            self.session.query(AssistantSummary)
            .filter(AssistantSummary.level == level)
            .order_by(AssistantSummary.created_at.desc())
            .limit(limit)
            .all()
        )

    def get_latest_global(self, level: int = 3) -> Optional[AssistantSummary]:
        """获取最新的指定层级摘要（默认 level=3 即全局摘要）"""
        return (
            self.session.query(AssistantSummary)
            .filter(AssistantSummary.level == level)
            .order_by(AssistantSummary.created_at.desc())
            .first()
        )

    def get_summarized_source_ids(self, level: int) -> set:
        """获取已有摘要的来源 ID 集合（只查 source_ids 列，避免加载 content/embedding）"""
        rows = (
            self.session.query(AssistantSummary.source_ids)
            .filter(AssistantSummary.level == level)
            .all()
        )
        ids = set()
        for (source_ids,) in rows:
            if source_ids:
                ids.update(source_ids.split(","))
        return ids

    def search_fts(self, query: str, levels: List[int], limit: int = 10) -> list:
        """
        FTS5 全文搜索摘要。

        Returns:
            list of dict: [{summary_id, level, content, created_at, fts_rank}]
        """
        from sqlalchemy import text

        # 构造 FTS5 查询：按空格拆分关键词用 OR 连接
        keywords = query.strip().split()
        if not keywords:
            return []
        fts_query = " OR ".join(f'"{kw.replace(chr(34), "")}"' for kw in keywords)

        # 参数化 IN 子句
        level_params = {f"lv{i}": int(lv) for i, lv in enumerate(levels)}
        level_placeholders = ",".join(f":lv{i}" for i in range(len(levels)))

        sql = text(f"""
            SELECT s.summary_id, s.level, s.content, s.created_at,
                   fts.rank AS fts_rank
            FROM assistant_summaries_fts fts
            JOIN assistant_summaries s ON s.summary_id = fts.summary_id
            WHERE assistant_summaries_fts MATCH :query
              AND s.level IN ({level_placeholders})
            ORDER BY fts.rank
            LIMIT :limit
        """)
        try:
            params = {"query": fts_query, "limit": limit}
            params.update(level_params)
            rows = self.session.execute(sql, params).fetchall()
            return [
                {
                    "summary_id": r[0],
                    "level": r[1],
                    "content": r[2],
                    "created_at": r[3],
                    "fts_rank": r[4],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"FTS5 搜索失败（可能表不存在），降级到 LIKE: {e}")
            return []

    def search_like(self, keywords: List[str], levels: List[int], limit: int = 5) -> List[AssistantSummary]:
        """关键词 LIKE 模糊搜索（FTS5 不可用时的最终降级）"""
        from sqlalchemy import or_
        q = self.session.query(AssistantSummary).filter(
            AssistantSummary.level.in_(levels)
        )
        if keywords:
            conditions = [AssistantSummary.content.contains(kw) for kw in keywords]
            q = q.filter(or_(*conditions))
        return q.order_by(AssistantSummary.created_at.desc()).limit(limit).all()

    def search_vec(self, query_embedding: list, levels: list, limit: int = 10) -> list:
        """
        sqlite-vec 向量相似度搜索。

        Args:
            query_embedding: 查询向量（float list，1536 维）
            levels: 搜索的摘要层级
            limit: 返回数量

        Returns:
            list of dict: [{summary_id, level, content, created_at, distance}]
        """
        try:
            import sqlite_vec
        except ImportError:
            return []

        from sqlalchemy import text

        query_blob = sqlite_vec.serialize_float32(query_embedding)

        # 参数化 IN 子句
        level_params = {f"lv{i}": int(lv) for i, lv in enumerate(levels)}
        level_placeholders = ",".join(f":lv{i}" for i in range(len(levels)))

        sql = text(f"""
            SELECT s.summary_id, s.level, s.content, s.created_at, v.distance
            FROM (
                SELECT summary_id, distance
                FROM assistant_summaries_vec
                WHERE embedding MATCH :query
                AND k = :k
            ) v
            JOIN assistant_summaries s ON s.summary_id = v.summary_id
            WHERE s.level IN ({level_placeholders})
            ORDER BY v.distance
        """)
        try:
            params = {"query": query_blob, "k": limit}
            params.update(level_params)
            rows = self.session.execute(sql, params).fetchall()
            return [
                {
                    "summary_id": r[0],
                    "level": r[1],
                    "content": r[2],
                    "created_at": r[3],
                    "distance": r[4],
                }
                for r in rows
            ]
        except Exception as e:
            logger.warning(f"向量搜索失败: {e}")
            return []

    def store_embedding(self, summary_id: str, embedding: list):
        """存储摘要的向量表示到 vec0 表和 assistant_summaries.embedding 列"""
        try:
            import sqlite_vec
        except ImportError:
            return

        from sqlalchemy import text

        embedding_blob = sqlite_vec.serialize_float32(embedding)

        try:
            # 更新 assistant_summaries.embedding 列（持久化备份）
            summary = self.session.query(AssistantSummary).filter(
                AssistantSummary.summary_id == summary_id
            ).first()
            if summary:
                summary.embedding = embedding_blob
                self.session.commit()

            # 插入 vec0 虚拟表
            self.session.execute(
                text("""
                    INSERT INTO assistant_summaries_vec(summary_id, embedding)
                    VALUES (:summary_id, :embedding)
                """),
                {"summary_id": summary_id, "embedding": embedding_blob},
            )
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.warning(f"存储 embedding 失败（summary_id={summary_id}）: {e}")

    def delete_by_level(self, level: int):
        """删除指定层级的所有摘要（用于重建全局摘要）"""
        # 先获取要删除的 summary_id（用于清理 vec0 表）
        summaries = self.session.query(AssistantSummary.summary_id).filter(
            AssistantSummary.level == level
        ).all()
        summary_ids = [s[0] for s in summaries]

        # 批量删除 vec0 表中的对应记录
        if summary_ids:
            from sqlalchemy import text
            try:
                placeholders = ",".join(f":id{i}" for i in range(len(summary_ids)))
                params = {f"id{i}": sid for i, sid in enumerate(summary_ids)}
                self.session.execute(
                    text(f"DELETE FROM assistant_summaries_vec WHERE summary_id IN ({placeholders})"),
                    params,
                )
            except Exception:
                pass  # vec0 表可能不存在

        self.session.query(AssistantSummary).filter(
            AssistantSummary.level == level
        ).delete()
        self.session.commit()


class ToolSuggestionRepository(BaseRepository):
    """工具化建议历史仓库（重复模式检测）"""

    def get_by_pattern(self, task_pattern: str) -> Optional[ToolSuggestionHistory]:
        """按任务模式查询"""
        return self.session.query(ToolSuggestionHistory).filter(
            ToolSuggestionHistory.task_pattern == task_pattern
        ).first()

    def create(self, task_pattern: str) -> ToolSuggestionHistory:
        """创建新的建议历史记录"""
        import uuid as _uuid
        record = ToolSuggestionHistory(
            suggestion_id=str(_uuid.uuid4()),
            task_pattern=task_pattern,
            times_seen=1,
        )
        try:
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
            return record
        except Exception:
            self.session.rollback()
            raise

    def increment(self, record: ToolSuggestionHistory):
        """执行次数 +1"""
        record.times_seen += 1
        self.session.commit()

    def mark_rejected(self, record: ToolSuggestionHistory):
        """记录拒绝状态，重置次数进入冷却"""
        record.accepted = False
        record.times_seen = 0
        self.session.commit()

    def reset_accepted(self, record: ToolSuggestionHistory):
        """冷却期结束，重置拒绝状态"""
        record.accepted = None
        self.session.commit()


class TeachingFailureRepository(BaseRepository):
    """技能教学失败记录仓库"""

    def create(self, record: TeachingFailureRecord) -> TeachingFailureRecord:
        try:
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
            logger.info(f"失败记录已创建: {record.workflow_id}")
            return record
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建失败记录失败: {e}")
            raise

    def get_by_id(self, record_id: str) -> Optional[TeachingFailureRecord]:
        return self.session.query(TeachingFailureRecord).filter(
            TeachingFailureRecord.record_id == record_id
        ).first()

    def get_by_workflow_id(self, workflow_id: str) -> Optional[TeachingFailureRecord]:
        return self.session.query(TeachingFailureRecord).filter(
            TeachingFailureRecord.workflow_id == workflow_id
        ).first()

    def update(self, record: TeachingFailureRecord) -> TeachingFailureRecord:
        try:
            self.session.commit()
            self.session.refresh(record)
            return record
        except Exception as e:
            self.session.rollback()
            logger.error(f"更新失败记录失败: {e}")
            raise

    def delete(self, record_id: str) -> bool:
        try:
            record = self.get_by_id(record_id)
            if record:
                self.session.delete(record)
                self.session.commit()
                return True
            return False
        except Exception as e:
            self.session.rollback()
            logger.error(f"删除失败记录失败: {e}")
            raise

    def get_active_failures(self) -> List[TeachingFailureRecord]:
        """返回所有 active / retrying 状态的记录，按 updated_at DESC 排序"""
        return (
            self.session.query(TeachingFailureRecord)
            .filter(TeachingFailureRecord.status.in_(["active", "retrying"]))
            .order_by(TeachingFailureRecord.updated_at.desc())
            .all()
        )

    def upsert_by_workflow(
        self,
        workflow_id: str,
        failed_stage: str,
        error_summary: str,
        error_type: str,
        tool_name: Optional[str] = None,
    ) -> bool:
        """
        按 workflow_id upsert 失败记录。

        Returns:
            True = 新建，False = 更新或终态跳过
        """
        existing = self.get_by_workflow_id(workflow_id)

        # 终态保护
        if existing and existing.status in ("resolved", "dismissed"):
            return False

        if not existing:
            record = TeachingFailureRecord(
                record_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                tool_name=tool_name,
                failed_stage=failed_stage,
                error_summary=error_summary,
                error_type=error_type,
                status="active",
                retry_count=1,
            )
            self.create(record)
            return True

        # 更新已有记录
        existing.failed_stage = failed_stage
        existing.error_summary = error_summary
        existing.error_type = error_type
        existing.status = "active"
        existing.retry_count = (existing.retry_count or 0) + 1
        if tool_name is not None:
            existing.tool_name = tool_name
        self.session.commit()
        return False

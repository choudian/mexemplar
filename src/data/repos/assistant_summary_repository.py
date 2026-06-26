"""
AssistantSummaryRepository -- 助理跨会话记忆摘要仓库
"""

import logging
from typing import List, Optional

from sqlalchemy import text

from ..models_sqlite import AssistantSummary
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


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

    def get_latest_global(self, level: int = 3) -> Optional[AssistantSummary]:
        """获取最新的指定层级摘要（默认 level=3 即全局摘要）"""
        return (
            self.session.query(AssistantSummary)
            .filter(AssistantSummary.level == level)
            .order_by(AssistantSummary.created_at.desc())
            .first()
        )

    def search_fts(self, query: str, levels: List[int], limit: int = 10) -> list:
        """
        FTS5 全文搜索摘要。

        Returns:
            list of dict: [{summary_id, level, content, created_at, fts_rank}]
        """
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

    def search_like(
        self, keywords: List[str], levels: List[int], limit: int = 5
    ) -> List[AssistantSummary]:
        """关键词 LIKE 模糊搜索（FTS5 不可用时的最终降级）"""
        from sqlalchemy import or_

        q = self.session.query(AssistantSummary).filter(AssistantSummary.level.in_(levels))
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

        embedding_blob = sqlite_vec.serialize_float32(embedding)

        try:
            # 更新 assistant_summaries.embedding 列（持久化备份）
            summary = (
                self.session.query(AssistantSummary)
                .filter(AssistantSummary.summary_id == summary_id)
                .first()
            )
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
        summaries = (
            self.session.query(AssistantSummary.summary_id)
            .filter(AssistantSummary.level == level)
            .all()
        )
        summary_ids = [s[0] for s in summaries]

        # 批量删除 vec0 表中的对应记录
        if summary_ids:
            try:
                placeholders = ",".join(f":id{i}" for i in range(len(summary_ids)))
                params = {f"id{i}": sid for i, sid in enumerate(summary_ids)}
                self.session.execute(
                    text(
                        f"DELETE FROM assistant_summaries_vec WHERE summary_id IN ({placeholders})"
                    ),
                    params,
                )
            except Exception:
                pass  # vec0 表可能不存在

        self.session.query(AssistantSummary).filter(AssistantSummary.level == level).delete()
        self.session.commit()

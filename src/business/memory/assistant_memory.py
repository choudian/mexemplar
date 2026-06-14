"""
助理跨会话记忆（legacy 路径 — FTS 搜索 + 全局摘要）

摘要生成的三层链路（session → group → global）已由 Brain Service 接管。
本模块仅保留搜索（search）和全局摘要读取（get_global_summary）作为
Brain Service 不可用时的降级路径。
"""

import json
import logging
import os
import threading
from datetime import datetime
from src.utils.timezone import utc_now_naive, to_naive_utc
from typing import Optional

logger = logging.getLogger(__name__)

SESSION_SUMMARY_LEVEL = 1
GROUP_SUMMARY_LEVEL = 2
GLOBAL_SUMMARY_LEVEL = 3


class AssistantMemoryManager:
    """助理跨会话记忆管理器（降级路径）"""

    def __init__(self, llm_client=None):
        self._llm = llm_client  # LangChainLLMClient，可为 None（FTS-only 模式）
        self._embedding_client = None  # 延迟初始化
        self._embedding_checked = False

    def _get_embedding_client(self):
        """
        获取 embedding 客户端（auto 降级策略）。
        通过统一配置读取 embedding API Key，失败时静默降级为 FTS-only。
        """
        if self._embedding_checked:
            return self._embedding_client

        self._embedding_checked = True
        try:
            from langchain_openai import OpenAIEmbeddings
            from src.data.real_tour_audit import is_real_tour_runtime
            from src.data.unified_config import get_unified_config

            if (
                is_real_tour_runtime()
                and os.environ.get("MEXEMPLAR_REAL_GRAND_TOUR_ENABLE_EMBEDDINGS") != "1"
            ):
                logger.info("[AssistantMemory] embedding disabled during real-tour runtime")
                return None
            openai_key = get_unified_config().get_embedding_api_key()
            if openai_key:
                try:
                    from src.business.debug.service import get_debug_service

                    get_debug_service().register_secret(openai_key)
                except Exception:
                    pass
                self._embedding_client = OpenAIEmbeddings(
                    api_key=openai_key, model="text-embedding-3-small"
                )
                logger.info("[AssistantMemory] OpenAI embedding 客户端已初始化")
        except (ImportError, Exception) as e:
            logger.debug(f"[AssistantMemory] embedding 不可用（FTS-only 模式）: {e}")

        return self._embedding_client

    def _try_embed_summary(self, summary_id: str, content: str):
        """尝试为摘要生成 embedding 并存储。失败时静默跳过。"""
        client = self._get_embedding_client()
        if not client:
            return
        try:
            from src.data.repositories import AssistantSummaryRepository

            embedding = client.embed_query(content)
            AssistantSummaryRepository().store_embedding(summary_id, embedding)
            logger.debug(f"[AssistantMemory] embedding 已存储: {summary_id}")
        except Exception as e:
            logger.warning(f"[AssistantMemory] embedding 存储失败: {e}")

    # =========================================================================
    # memory_search
    # =========================================================================

    def search(self, query: str, limit: int = 5) -> list:
        """
        搜索历史记忆摘要，按降级策略自动选择检索方式：
        1. 有 embedding API Key → 混合检索（0.7×向量 + 0.3×FTS5）
        2. 无 Key → FTS5 纯关键词搜索
        3. FTS5 不可用 → LIKE 模糊搜索

        所有结果都经过时间衰减加权。

        Returns:
            list of dict: [{summary_id, level, score, snippet, created_at}]
        """
        try:
            from src.data.repositories import AssistantSummaryRepository

            repo = AssistantSummaryRepository()
            search_levels = [SESSION_SUMMARY_LEVEL, GROUP_SUMMARY_LEVEL]

            # --- 层级 1：尝试混合检索（向量 + FTS5）---
            vector_results = self._try_vector_search(query, repo, search_levels, limit * 2)
            fts_results = self._try_fts_search(query, repo, search_levels, limit * 2)

            if vector_results and fts_results:
                merged = self._merge_hybrid(vector_results, fts_results, limit)
                return merged

            # --- 层级 2：FTS-only ---
            if fts_results:
                return self._apply_time_decay(fts_results, limit)

            # --- 层级 3：LIKE 降级 ---
            keywords = query.split()
            like_results = repo.search_like(keywords=keywords, levels=search_levels, limit=limit)
            return [
                {
                    "summary_id": s.summary_id,
                    "level": s.level,
                    "score": 1.0,
                    "snippet": s.content[:300] if s.content else "",
                    "created_at": self._format_created_at(s.created_at),
                }
                for s in like_results
            ]
        except Exception as e:
            logger.error(f"[AssistantMemory] 搜索失败: {e}")
            return []

    @staticmethod
    def _format_created_at(created_at) -> str:
        """将 created_at 统一转为 ISO 格式字符串（兼容 naive/aware datetime 和字符串）。"""
        if hasattr(created_at, "isoformat"):
            return created_at.isoformat()
        return str(created_at or "")

    def _try_vector_search(self, query: str, repo, levels: list, limit: int) -> list:
        """尝试向量检索。未配置 embedding 时返回空列表（静默降级）。"""
        embedding_client = self._get_embedding_client()
        if not embedding_client:
            return []

        try:
            query_embedding = embedding_client.embed_query(query)
            rows = repo.search_vec(query_embedding=query_embedding, levels=levels, limit=limit)
            if not rows:
                return []

            results = []
            for r in rows:
                # 余弦距离 → 相似度：similarity = 1 - distance/2
                similarity = 1.0 - (r["distance"] / 2.0) if r["distance"] is not None else 0.0
                results.append(
                    {
                        "summary_id": r["summary_id"],
                        "level": r["level"],
                        "score": similarity,
                        "snippet": r["content"][:300] if r["content"] else "",
                        "created_at": self._format_created_at(r["created_at"]),
                    }
                )
            return results
        except Exception as e:
            logger.warning(f"[AssistantMemory] 向量搜索失败（降级到 FTS）: {e}")
            return []

    def _try_fts_search(self, query: str, repo, levels: list, limit: int) -> list:
        """尝试 FTS5 搜索。FTS 表不存在时返回空列表（静默降级）。"""
        rows = repo.search_fts(query=query, levels=levels, limit=limit)
        if not rows:
            return []

        results = []
        for r in rows:
            results.append(
                {
                    "summary_id": r["summary_id"],
                    "level": r["level"],
                    "score": -r["fts_rank"] if r["fts_rank"] else 0.0,  # FTS5 rank 越负越好，取反
                    "snippet": r["content"][:300] if r["content"] else "",
                    "created_at": self._format_created_at(r["created_at"]),
                }
            )
        return results

    def _merge_hybrid(self, vector_results: list, fts_results: list, limit: int) -> list:
        """混合检索合并：0.7×向量 + 0.3×FTS5，叠加时间衰减。"""
        VECTOR_WEIGHT = 0.7
        FTS_WEIGHT = 0.3

        # 归一化各自分数到 [0, 1]
        def _normalize(results: list) -> dict:
            if not results:
                return {}
            scores = [r["score"] for r in results]
            max_s, min_s = max(scores), min(scores)
            span = max_s - min_s if max_s > min_s else 1.0
            return {r["summary_id"]: (r["score"] - min_s) / span for r in results}

        vec_norm = _normalize(vector_results)
        fts_norm = _normalize(fts_results)

        # 合并所有候选
        all_items = {}
        for r in vector_results + fts_results:
            sid = r["summary_id"]
            if sid not in all_items:
                all_items[sid] = r

        # 计算混合分数 + 时间衰减
        scored = []
        for sid, item in all_items.items():
            hybrid = VECTOR_WEIGHT * vec_norm.get(sid, 0.0) + FTS_WEIGHT * fts_norm.get(sid, 0.0)
            decay = self._time_decay_factor(item.get("created_at", ""))
            item["score"] = round(hybrid * decay, 4)
            scored.append(item)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def _apply_time_decay(self, results: list, limit: int) -> list:
        """对 FTS-only 结果应用时间衰减重排序。"""
        for r in results:
            decay = self._time_decay_factor(r.get("created_at", ""))
            r["score"] = round(r["score"] * decay, 4)
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    @staticmethod
    def _time_decay_factor(created_at_str: str) -> float:
        """时间衰减因子：越近权重越高。半衰期 30 天。"""
        import math

        try:
            if not created_at_str:
                return 0.5
            dt = (
                datetime.fromisoformat(created_at_str)
                if isinstance(created_at_str, str)
                else created_at_str
            )
            # dt 可能是 naive（旧数据）或 aware（新数据），统一转 naive UTC 后比较
            if dt.tzinfo is not None:
                dt = to_naive_utc(dt)
            days_ago = (utc_now_naive() - dt).total_seconds() / 86400.0
            return math.exp(-0.693 * days_ago / 30.0)  # ln(2)/半衰期
        except Exception:
            return 0.5

    def get_global_summary(self) -> Optional[str]:
        """获取全局摘要文本（注入 system prompt 用）"""
        try:
            from src.data.repositories import AssistantSummaryRepository

            repo = AssistantSummaryRepository()
            summary = repo.get_latest_global()
            return summary.content if summary else None
        except Exception as e:
            logger.error(f"[AssistantMemory] 获取全局摘要失败: {e}")
            return None


# =========================================================================
# memory_search 工具定义
# =========================================================================

MEMORY_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "memory_search",
        "description": "搜索历史会话记忆。当用户询问过去某个任务的结果，或想知道以前做过什么时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或问题描述"},
                "limit": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5",
                },
            },
            "required": ["query"],
        },
    },
}

# 全局实例（懒加载，线程安全）
_memory_manager: Optional[AssistantMemoryManager] = None
_memory_manager_lock = threading.Lock()


def get_memory_manager(llm_client=None) -> AssistantMemoryManager:
    """获取（或初始化）全局记忆管理器实例"""
    global _memory_manager
    with _memory_manager_lock:
        if _memory_manager is None:
            _memory_manager = AssistantMemoryManager(llm_client)
        elif llm_client and _memory_manager._llm is None:
            _memory_manager._llm = llm_client
        return _memory_manager


def memory_search_handler(query: str, limit: int = 5) -> str:
    """memory_search handler"""
    results = get_memory_manager().search(query, limit=limit)
    if not results:
        return json.dumps({"results": [], "message": "未找到相关历史记忆"}, ensure_ascii=False)
    return json.dumps({"results": results}, ensure_ascii=False)


__all__ = [
    "AssistantMemoryManager",
    "get_memory_manager",
    "memory_search_handler",
    "MEMORY_SEARCH_SCHEMA",
]

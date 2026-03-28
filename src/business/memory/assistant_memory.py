"""
助理跨会话记忆

三层摘要体系：
- 第一层：会话摘要（每个会话结束后生成）
- 第二层：分组摘要（每 10 个会话摘要合并一次）
- 第三层：全局摘要（随分组更新）

触发时机：
- 新建会话时后台异步批量生成未摘要的会话
- 每积累 10 个第一层摘要自动生成分组摘要
- 分组摘要更新时重新生成全局摘要
"""

import json
import logging
import threading
import uuid
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

SESSION_SUMMARY_LEVEL = 1
GROUP_SUMMARY_LEVEL = 2
GLOBAL_SUMMARY_LEVEL = 3
GROUP_SIZE = 10  # 每 N 个会话摘要合并一次


SESSION_SUMMARY_PROMPT = """\
请为以下助理会话生成摘要。

会话时间：{time_range}
会话消息：
{messages_text}

请按以下格式输出（不要添加其他内容）：
会话时间：{time_range}
任务记录：
- [任务描述] → [成功/失败/未完成]（[简短结果说明]）
（每行一个任务，从用户消息中识别任务意图，最多列 8 个）
使用工具：[工具名(次数)] 列表，如"web_search(2次)、天气查询(1次)"（无工具调用则写"无"）
"""

GROUP_SUMMARY_PROMPT = """\
请将以下会话摘要合并为一个分组摘要，概括这段时期的任务类型和趋势：

{session_summaries}

请按以下格式输出：
时间范围：[最早] ~ [最晚]
活跃会话：[数量]个
高频任务类型：[类型(次数)] 列表
关键事件：
- [重要的单个事件或趋势变化]
（最多 5 条关键事件）
"""

GLOBAL_SUMMARY_PROMPT = """\
请将以下分组摘要合并为全局摘要，提炼用户的长期使用习惯：

{group_summaries}

请按以下格式输出（不超过 300 字）：
整体使用情况：[高度概括]
常用工具：[最常用的 3-5 个工具]
典型任务模式：[用户最常做的 2-3 类任务]
近期变化：[最近一两个月的显著变化（若有）]
"""


class AssistantMemoryManager:
    """助理跨会话记忆管理器"""

    def __init__(self, llm_client=None):
        self._llm = llm_client  # LangChainLLMClient，可为 None（FTS-only 模式）
        self._embedding_client = None  # 延迟初始化
        self._embedding_checked = False

    def _get_embedding_client(self):
        """
        获取 embedding 客户端（auto 降级策略）。
        按优先级检测 keyring 中的 API Key：OpenAI → 其他 → None。
        返回 None 时静默降级为 FTS-only。
        """
        if self._embedding_checked:
            return self._embedding_client

        self._embedding_checked = True
        try:
            import keyring
            openai_key = keyring.get_password("Mexemplar", "openai_api_key")
            if openai_key:
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)

                class _EmbeddingClient:
                    """轻量封装，提供 embed_query 接口"""
                    def __init__(self, oai_client):
                        self._client = oai_client
                    def embed_query(self, text: str) -> list:
                        resp = self._client.embeddings.create(
                            input=text, model="text-embedding-3-small"
                        )
                        return resp.data[0].embedding

                self._embedding_client = _EmbeddingClient(client)
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
    # 触发入口
    # =========================================================================

    def trigger_on_new_session(self, new_session_id: str):
        """
        新建会话时调用：后台异步为所有未摘要的旧会话生成摘要。
        不阻塞新会话创建。
        """
        threading.Thread(
            target=self._batch_generate_session_summaries,
            args=(new_session_id,),
            daemon=True,
        ).start()

    def _batch_generate_session_summaries(self, exclude_session_id: str):
        """批量为未生成摘要的历史会话生成摘要"""
        try:
            from src.data.repositories import SessionRepository, MessageRepository, AssistantSummaryRepository

            session_repo = SessionRepository()
            all_sessions = session_repo.get_by_agent_type("assistant", limit=200)

            summary_repo = AssistantSummaryRepository()
            summarized_ids = summary_repo.get_summarized_source_ids(SESSION_SUMMARY_LEVEL)

            msg_repo = MessageRepository()
            new_summary_count = 0
            for session in all_sessions:
                if session.session_id == exclude_session_id:
                    continue
                if session.session_id in summarized_ids:
                    continue
                if session.status == "active":
                    continue  # 跳过仍在进行的会话

                messages = msg_repo.get_by_session(session.session_id)
                if len(messages) < 2:  # 太短不值得摘要
                    continue

                self._generate_session_summary(session, messages)
                new_summary_count += 1

            if new_summary_count > 0:
                logger.info(f"[AssistantMemory] 批量生成 {new_summary_count} 个会话摘要")
                # 检查是否需要生成分组摘要
                self._maybe_generate_group_summary()

        except Exception as e:
            logger.error(f"[AssistantMemory] 批量摘要失败: {e}", exc_info=True)

    # =========================================================================
    # 摘要生成
    # =========================================================================

    def _generate_session_summary(self, session, messages: list) -> Optional[str]:
        """为单个会话生成第一层摘要，返回 summary_id"""
        try:
            from src.data.repositories import AssistantSummaryRepository
            from src.data.models_sqlite import AssistantSummary

            content = self._call_llm_for_summary(
                SESSION_SUMMARY_PROMPT,
                session=session,
                messages=messages,
            )
            if not content:
                return None

            summary = AssistantSummary(
                summary_id=f"ss_{session.session_id[:8]}_{uuid.uuid4().hex[:4]}",
                level=SESSION_SUMMARY_LEVEL,
                content=content,
                source_ids=session.session_id,
            )
            repo = AssistantSummaryRepository()
            repo.create(summary)
            self._try_embed_summary(summary.summary_id, content)
            logger.debug(f"[AssistantMemory] 会话摘要已生成: {summary.summary_id}")
            return summary.summary_id
        except Exception as e:
            logger.error(f"[AssistantMemory] 生成会话摘要失败: {e}")
            return None

    def _maybe_generate_group_summary(self):
        """检查第一层摘要数量，达到阈值时生成分组摘要"""
        try:
            from src.data.repositories import AssistantSummaryRepository
            from src.data.models_sqlite import AssistantSummary

            repo = AssistantSummaryRepository()

            # 找出尚未被分组的第一层摘要（按时间升序取最老的）
            all_l1 = repo.get_by_level(SESSION_SUMMARY_LEVEL, limit=500)
            all_l1_asc = list(reversed(all_l1))  # get_by_level 返回 desc，翻转为 asc

            grouped_ids = repo.get_summarized_source_ids(GROUP_SUMMARY_LEVEL)
            ungrouped = [s for s in all_l1_asc if s.summary_id not in grouped_ids]

            if len(ungrouped) < GROUP_SIZE:
                return

            # 取最老的 GROUP_SIZE 个生成分组摘要
            batch = ungrouped[:GROUP_SIZE]
            summaries_text = "\n\n".join(
                f"[{s.summary_id}]\n{s.content}" for s in batch
            )

            content = self._call_llm_simple(
                GROUP_SUMMARY_PROMPT.format(session_summaries=summaries_text)
            )
            if not content:
                return

            source_ids = ",".join(s.summary_id for s in batch)
            group_summary = AssistantSummary(
                summary_id=f"gs_{uuid.uuid4().hex[:8]}",
                level=GROUP_SUMMARY_LEVEL,
                content=content,
                source_ids=source_ids,
            )
            repo.create(group_summary)
            self._try_embed_summary(group_summary.summary_id, content)
            logger.info(f"[AssistantMemory] 分组摘要已生成: {group_summary.summary_id}")

            # 更新全局摘要
            self._refresh_global_summary()

        except Exception as e:
            logger.error(f"[AssistantMemory] 生成分组摘要失败: {e}")

    def _refresh_global_summary(self):
        """重新生成第三层全局摘要"""
        try:
            from src.data.repositories import AssistantSummaryRepository
            from src.data.models_sqlite import AssistantSummary

            repo = AssistantSummaryRepository()
            all_groups = repo.get_by_level(GROUP_SUMMARY_LEVEL, limit=10)

            if not all_groups:
                return

            group_text = "\n\n".join(
                f"[{g.summary_id}]\n{g.content}" for g in all_groups
            )
            content = self._call_llm_simple(
                GLOBAL_SUMMARY_PROMPT.format(group_summaries=group_text)
            )
            if not content:
                return

            # 删旧的全局摘要，写新的
            repo.delete_by_level(GLOBAL_SUMMARY_LEVEL)
            global_summary = AssistantSummary(
                summary_id=f"global_{uuid.uuid4().hex[:8]}",
                level=GLOBAL_SUMMARY_LEVEL,
                content=content,
                source_ids=",".join(g.summary_id for g in all_groups),
            )
            repo.create(global_summary)
            self._try_embed_summary(global_summary.summary_id, content)
            logger.info("[AssistantMemory] 全局摘要已更新")

        except Exception as e:
            logger.error(f"[AssistantMemory] 更新全局摘要失败: {e}")

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
                    "snippet": s.content[:300],
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                }
                for s in like_results
            ]
        except Exception as e:
            logger.error(f"[AssistantMemory] 搜索失败: {e}")
            return []

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
                created_at = r["created_at"]
                results.append({
                    "summary_id": r["summary_id"],
                    "level": r["level"],
                    "score": similarity,
                    "snippet": r["content"][:300] if r["content"] else "",
                    "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
                })
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
            created_at = r["created_at"]
            results.append({
                "summary_id": r["summary_id"],
                "level": r["level"],
                "score": -r["fts_rank"] if r["fts_rank"] else 0.0,  # FTS5 rank 越负越好，取反
                "snippet": r["content"][:300] if r["content"] else "",
                "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at or ""),
            })
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
            dt = datetime.fromisoformat(created_at_str) if isinstance(created_at_str, str) else created_at_str
            days_ago = (datetime.now() - dt).total_seconds() / 86400.0
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
    # LLM 调用辅助
    # =========================================================================

    def _call_llm_for_summary(self, prompt_template: str, session, messages: list, max_tokens: int = 300) -> Optional[str]:
        """为会话生成摘要"""
        if not self._llm:
            return self._fallback_session_summary(session, messages)

        try:
            # 格式化消息文本（只取 role=user/assistant 的消息，最多 50 条）
            msg_lines = []
            for msg in messages[-50:]:
                if msg.role in ("user", "assistant") and msg.content:
                    role_label = "用户" if msg.role == "user" else "助理"
                    msg_lines.append(f"[{role_label}] {msg.content[:200]}")

            time_range = self._session_time_range(session, messages)
            prompt = prompt_template.format(
                time_range=time_range,
                messages_text="\n".join(msg_lines[:40]),
            )

            result = self._llm.chat(prompt, max_tokens=max_tokens)
            return result if result else None
        except Exception as e:
            logger.error(f"[AssistantMemory] LLM 摘要失败: {e}")
            return self._fallback_session_summary(session, messages)

    def _call_llm_simple(self, prompt: str, max_tokens: int = 500) -> Optional[str]:
        """调用 LLM 生成文本"""
        if not self._llm:
            return None
        try:
            result = self._llm.chat(prompt, max_tokens=max_tokens)
            return result if result else None
        except Exception as e:
            logger.error(f"[AssistantMemory] LLM 调用失败: {e}")
            return None

    def _fallback_session_summary(self, session, messages: list) -> str:
        """无 LLM 时的降级摘要（基于统计）"""
        user_msgs = [m for m in messages if m.role == "user" and m.content]
        time_range = self._session_time_range(session, messages)
        return (
            f"会话时间：{time_range}\n"
            f"消息数量：{len(messages)} 条\n"
            f"用户消息：{len(user_msgs)} 条\n"
            f"（摘要生成需要配置 LLM）"
        )

    def _session_time_range(self, session, messages: list) -> str:
        """计算会话时间范围"""
        try:
            if messages:
                start = messages[0].created_at
                end = messages[-1].created_at
                if start and end:
                    return f"{start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%H:%M')}"
            if session.created_at:
                return session.created_at.strftime('%Y-%m-%d %H:%M')
        except Exception:
            pass
        return "未知时间"


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

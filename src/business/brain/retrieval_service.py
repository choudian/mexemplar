"""
Retrieval Service - 归档区显式检索

负责：
- 关键词检索归档区条目
- 复合评分：relevance + recency + effectiveness + exploration
- invalidated 条目降权但仍可检索
- 检索后递增 loaded_count
"""

from src.business.brain.scoring import compute_recency_score
from src.utils.events import emit

# 复合评分权重
RELEVANCE_WEIGHT = 0.35
RECENCY_WEIGHT = 0.25
EFFECTIVENESS_WEIGHT = 0.25
EXPLORATION_WEIGHT = 0.15

# invalidated 降权系数
INVALIDATED_PENALTY = 0.5

# 新条目探索加分阈值
EXPLORATION_LOADED_THRESHOLD = 3


class RetrievalService:
    """归档区检索服务"""

    def __init__(self, brain_repo=None, config=None):
        self._repo = brain_repo
        self._config = config

    def _get_repo(self):
        if self._repo is None:
            from src.data.repos.brain_repository import BrainRepository

            self._repo = BrainRepository()
        return self._repo

    def retrieve_archive(self, query: str) -> list[dict]:
        """显式检索归档区条目。

        Args:
            query: 搜索关键词

        Returns:
            按 composite_score 降序排列的结果列表
        """
        if not query or not query.strip():
            return []

        repo = self._get_repo()
        entries = repo.search_archive_entries(query.strip())
        results = []
        for entry in entries:
            result = self._entry_to_result(entry)
            result["composite_score"] = self._compute_composite_score(result)
            results.append(result)

        # 按 composite_score 降序排序
        results.sort(key=lambda r: r["composite_score"], reverse=True)

        # 递增 loaded_count
        if results:
            repo.batch_increment_loaded_counts([r["entry_id"] for r in results])

        return results

    def retrieve_failure_zone(self, context: str) -> list[dict]:
        """Retrieve active/invalidated failure-zone memories for decision avoidance."""
        if not context or not context.strip():
            return []

        repo = self._get_repo()
        entries = repo.search_entries(
            "failure",
            context.strip(),
            statuses=("active", "invalidated"),
        )
        results = []
        for entry in entries:
            result = self._entry_to_result(entry)
            result["composite_score"] = self._compute_composite_score(result)
            results.append(result)
        results.sort(key=lambda r: r["composite_score"], reverse=True)
        if results:
            repo.batch_increment_loaded_counts([r["entry_id"] for r in results])
        return results

    def invalidate_memory_entry(
        self,
        entry_id: str,
        reason: str,
        *,
        current_context_entry_ids: list[str] | set[str] | tuple[str, ...] | None = None,
    ) -> dict:
        """Invalidate an entry only when it is part of the current context window."""
        entry_id = (entry_id or "").strip()
        reason = (reason or "").strip()
        if not entry_id or not reason:
            return {
                "success": False,
                "message": "entry_id and reason are required",
                "entry_id": entry_id,
            }

        if current_context_entry_ids is not None and entry_id not in set(current_context_entry_ids):
            return {
                "success": False,
                "message": "Entry is outside the current context window",
                "entry_id": entry_id,
            }

        repo = self._get_repo()
        entry = repo.get_entry(entry_id)
        if entry is None:
            return {
                "success": False,
                "message": "Entry not found",
                "entry_id": entry_id,
            }
        if getattr(entry, "status", "") == "soft-deleted":
            return {
                "success": False,
                "message": "Entry is already deleted",
                "entry_id": entry_id,
            }

        updated = repo.invalidate_entry(entry_id, reason)
        if updated:
            emit(
                "brain_zone_changed",
                zone=getattr(entry, "zone", ""),
                entry_id=entry_id,
                operation="invalidate",
            )
        return {
            "success": bool(updated),
            "message": "Entry invalidated" if updated else "Entry was not invalidated",
            "entry_id": entry_id,
        }

    def _entry_to_result(self, entry) -> dict:
        """Normalize ORM, dataclass, or mock entries into API-facing dicts."""
        created_at = getattr(entry, "created_at", "") or ""
        updated_at = getattr(entry, "updated_at", "") or ""
        return {
            "entry_id": getattr(entry, "entry_id", ""),
            "content": getattr(entry, "content", ""),
            "zone": getattr(entry, "zone", "archive"),
            "status": getattr(entry, "status", "active"),
            "reason": getattr(entry, "reason", ""),
            "scope": getattr(entry, "scope", None),
            "relevance_score": getattr(entry, "relevance_score", 0.0) or 0.0,
            "loaded_count": getattr(entry, "loaded_count", 0) or 0,
            "referenced_count": getattr(entry, "referenced_count", 0) or 0,
            "created_at": str(created_at),
            "updated_at": str(updated_at),
            "invalidation_factor": (
                INVALIDATED_PENALTY if getattr(entry, "status", "active") == "invalidated" else 1.0
            ),
        }

    def _compute_composite_score(self, entry: dict) -> float:
        """计算复合评分。

        composite = relevance_w * relevance
                  + recency_w * recency_score
                  + effectiveness_w * effectiveness_score
                  + exploration_w * exploration_bonus
        """
        relevance = entry.get("relevance_score", 0.0)

        # recency: 基于创建时间的衰减
        recency_score = self._compute_recency_score(entry.get("created_at", ""))

        # effectiveness: referenced_count / max(loaded_count, 1)
        loaded = max(entry.get("loaded_count", 0), 1)
        referenced = entry.get("referenced_count", 0)
        effectiveness_score = min(referenced / loaded, 1.0)

        # exploration: loaded_count 很低的条目获得加分
        loaded_count = entry.get("loaded_count", 0)
        if loaded_count < EXPLORATION_LOADED_THRESHOLD:
            exploration_bonus = 1.0 - (loaded_count / EXPLORATION_LOADED_THRESHOLD)
        else:
            exploration_bonus = 0.0

        composite = (
            RELEVANCE_WEIGHT * relevance
            + RECENCY_WEIGHT * recency_score
            + EFFECTIVENESS_WEIGHT * effectiveness_score
            + EXPLORATION_WEIGHT * exploration_bonus
        )

        # invalidated 降权
        if entry.get("status") == "invalidated":
            composite *= INVALIDATED_PENALTY

        return round(composite, 4)

    def _compute_recency_score(self, created_at_str: str) -> float:
        """基于创建时间计算新近度评分（0-1）。"""
        # Archive memories intentionally retain value longer than hot-zone context.
        return compute_recency_score(created_at_str, half_life_days=365)

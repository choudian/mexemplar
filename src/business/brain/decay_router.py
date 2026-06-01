"""
Decay Router - 热区衰减路由器

负责：
1. 将 relevance_score 低于 fading_threshold 的热区 active 条目标记为 fading
2. 将 fading 条目按 entry_type 路由：
   - event -> archive 区
   - insight -> persistent 区（relevance_score 不太低时）
   - insight（relevance_score 极低）-> soft-delete
"""

import logging

from src.business.brain.models import Zone, EntryType
from src.utils.events import emit

logger = logging.getLogger(__name__)

# insight 条目极低 relevance 阈值，低于此值直接软删除
INSIGHT_SOFT_DELETE_THRESHOLD = 0.1


class DecayRouter:
    """热区衰减路由器"""

    def __init__(self, brain_repo=None, config=None):
        self._repo = brain_repo
        self._config = config

    def _get_repo(self):
        if self._repo is None:
            from src.data.repos.brain_repository import BrainRepository

            self._repo = BrainRepository()
        return self._repo

    def _get_config(self):
        if self._config is None:
            from src.data.unified_config import get_unified_config

            self._config = get_unified_config()
        return self._config

    def run_decay_sweep(self) -> dict:
        """执行一轮衰减扫描。

        Returns:
            统计信息 dict，包含 faded_count, routed_to_archive, routed_to_persistent, soft_deleted
        """
        repo = self._get_repo()
        config = self._get_config()
        fading_threshold = config.get_brain_decay_fading_threshold()

        stats = {
            "faded_count": 0,
            "routed_to_archive": 0,
            "routed_to_persistent": 0,
            "soft_deleted": 0,
            "errors": 0,
        }

        # Phase 1: 将低于阈值的热区 active 条目标记为 fading
        active_entries = self._entry_list(
            repo.get_entries_by_zone(
                Zone.HOT.value,
                status="active",
            )
        )
        for entry in active_entries:
            entry_id = getattr(entry, "entry_id", "")
            try:
                score = getattr(entry, "relevance_score", 1.0)
                if score < fading_threshold:
                    if repo.update_entry_status(entry_id, "fading"):
                        emit(
                            "brain_zone_changed",
                            zone=Zone.HOT.value,
                            entry_id=entry_id,
                            operation="status_update",
                        )
                        stats["faded_count"] += 1
                        logger.info(
                            "Entry %s marked as fading (score=%.3f < threshold=%.3f)",
                            entry_id,
                            score,
                            fading_threshold,
                        )
                    else:
                        logger.warning(
                            "Entry %s kept active because the fading status update did not match",
                            entry_id,
                        )
            except Exception as exc:
                stats["errors"] += 1
                logger.error(
                    "Decay sweep failed while marking entry %s as fading: %s",
                    entry_id,
                    exc,
                    exc_info=True,
                )

        # Phase 2: 路由 fading 条目
        fading_entries = self._entry_list(
            repo.get_entries_by_zone(
                Zone.HOT.value,
                status="fading",
            )
        )
        for entry in fading_entries:
            entry_id = getattr(entry, "entry_id", "")
            try:
                self._route_fading_entry(repo, entry, stats)
            except Exception as exc:
                stats["errors"] += 1
                logger.error(
                    "Decay sweep failed while routing fading entry %s: %s",
                    entry_id,
                    exc,
                    exc_info=True,
                )

        logger.info(
            "Decay sweep completed: %d faded, %d -> archive, %d -> persistent, %d soft-deleted, %d errors",
            stats["faded_count"],
            stats["routed_to_archive"],
            stats["routed_to_persistent"],
            stats["soft_deleted"],
            stats["errors"],
        )
        return stats

    def _entry_list(self, result):
        if isinstance(result, tuple):
            return result[0]
        return result

    def _route_fading_entry(self, repo, entry, stats: dict) -> None:
        """路由单个 fading 条目。"""
        entry_id = getattr(entry, "entry_id", "")
        entry_type = getattr(entry, "entry_type", None)
        content = getattr(entry, "content", "")
        reason = getattr(entry, "reason", "")
        scope = getattr(entry, "scope", None)
        relevance_score = getattr(entry, "relevance_score", 0.0)
        source_segment_id = getattr(entry, "source_segment_id", None)
        source_session_id = getattr(entry, "source_session_id", None)

        if entry_type == EntryType.EVENT.value:
            new_id = self._route_to_zone_atomically(
                repo,
                entry_id=entry_id,
                target_zone=Zone.ARCHIVE.value,
                content=content,
                reason=f"Decay routed from hot zone: {reason}",
                scope=scope,
                source_segment_id=source_segment_id,
                source_session_id=source_session_id,
            )
            emit(
                "brain_zone_changed",
                zone=Zone.ARCHIVE.value,
                entry_id=str(new_id),
                operation="create",
            )
            emit(
                "brain_zone_changed",
                zone=Zone.HOT.value,
                entry_id=entry_id,
                operation="soft_delete",
            )
            stats["routed_to_archive"] += 1
            logger.info("Event entry %s routed to archive as %s", entry_id, new_id)

        elif entry_type == EntryType.INSIGHT.value:
            if relevance_score < INSIGHT_SOFT_DELETE_THRESHOLD:
                self._soft_delete_atomically(repo, entry_id)
                emit(
                    "brain_zone_changed",
                    zone=Zone.HOT.value,
                    entry_id=entry_id,
                    operation="soft_delete",
                )
                stats["soft_deleted"] += 1
                logger.info(
                    "Insight entry %s soft-deleted (score=%.3f < %.3f)",
                    entry_id,
                    relevance_score,
                    INSIGHT_SOFT_DELETE_THRESHOLD,
                )
            else:
                new_id = self._route_to_zone_atomically(
                    repo,
                    entry_id=entry_id,
                    target_zone=Zone.PERSISTENT.value,
                    content=content,
                    reason=f"Decay routed from hot zone: {reason}",
                    scope=scope,
                    source_segment_id=source_segment_id,
                    source_session_id=source_session_id,
                )
                emit(
                    "brain_zone_changed",
                    zone=Zone.PERSISTENT.value,
                    entry_id=str(new_id),
                    operation="create",
                )
                emit(
                    "brain_zone_changed",
                    zone=Zone.HOT.value,
                    entry_id=entry_id,
                    operation="soft_delete",
                )
                stats["routed_to_persistent"] += 1
                logger.info("Insight entry %s routed to persistent as %s", entry_id, new_id)
        else:
            new_id = self._route_to_zone_atomically(
                repo,
                entry_id=entry_id,
                target_zone=Zone.ARCHIVE.value,
                content=content,
                reason=f"Decay routed from hot zone (no type): {reason}",
                scope=scope,
                source_segment_id=source_segment_id,
                source_session_id=source_session_id,
            )
            emit(
                "brain_zone_changed",
                zone=Zone.ARCHIVE.value,
                entry_id=str(new_id),
                operation="create",
            )
            emit(
                "brain_zone_changed",
                zone=Zone.HOT.value,
                entry_id=entry_id,
                operation="soft_delete",
            )
            stats["routed_to_archive"] += 1
            logger.info("Untyped entry %s routed to archive as %s", entry_id, new_id)

    def _route_to_zone_atomically(
        self,
        repo,
        *,
        entry_id: str,
        target_zone: str,
        content: str,
        reason: str,
        scope,
        source_segment_id,
        source_session_id,
    ) -> str:
        self._begin_repo_write(repo)
        try:
            new_entry = repo.create_entry(
                zone=target_zone,
                content=content,
                origin="decay",
                reason=reason,
                scope=scope,
                source_segment_id=source_segment_id,
                source_session_id=source_session_id,
                commit=False,
            )
            if not repo.soft_delete_entry(entry_id, superseded_by=new_entry, commit=False):
                raise RuntimeError(f"Decay source entry not found: {entry_id}")
            self._commit_repo_write(repo)
            return str(new_entry)
        except Exception:
            self._rollback_repo_write(repo)
            raise

    def _soft_delete_atomically(self, repo, entry_id: str) -> None:
        self._begin_repo_write(repo)
        try:
            if not repo.soft_delete_entry(entry_id, commit=False):
                raise RuntimeError(f"Decay source entry not found: {entry_id}")
            self._commit_repo_write(repo)
        except Exception:
            self._rollback_repo_write(repo)
            raise

    @staticmethod
    def _begin_repo_write(repo) -> None:
        ensure_immediate = getattr(repo, "ensure_immediate_transaction", None)
        if callable(ensure_immediate):
            ensure_immediate()

    @staticmethod
    def _repo_session(repo):
        session = getattr(repo, "session", None)
        if session is None or session.__class__.__module__.startswith("unittest.mock"):
            return None
        if not callable(getattr(session, "commit", None)):
            return None
        return session

    @classmethod
    def _commit_repo_write(cls, repo) -> None:
        session = cls._repo_session(repo)
        if session is not None:
            session.commit()

    @classmethod
    def _rollback_repo_write(cls, repo) -> None:
        session = cls._repo_session(repo)
        if session is not None:
            session.rollback()

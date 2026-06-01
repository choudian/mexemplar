"""
长期上下文与归档检索集成测试 (T052)

覆盖：
- 完整归档写入 -> 检索流程
- 沉淀写入归档区条目后可通过关键词检索
- 跨 Segment 归档条目检索
- 检索后 loaded_count 递增
"""

import pytest
from uuid import uuid4

from src.business.brain.models import Zone
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


class TestArchiveRetrievalIntegration:
    """集成测试：归档区写入与检索完整流程。"""

    def test_distilled_archive_entries_searchable(self, in_memory_db, mock_config):
        """沉淀写入归档区的条目应可通过检索服务找到。"""
        from src.data.repos.brain_repository import BrainRepository
        from src.business.brain.retrieval_service import RetrievalService

        repo = BrainRepository()

        # 写入归档区条目
        entry_id_1 = repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="用户讨论了 Q3 季度预算审核",
            origin="decay",
            reason="热区衰减路由",
            entry_type="event",
        )
        repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="用户偏好简洁的汇报格式",
            origin="decay",
            reason="洞察路由到归档",
            entry_type="insight",
        )

        service = RetrievalService(brain_repo=repo)
        results = service.retrieve_archive("预算")

        assert len(results) >= 1
        matching_ids = [r["entry_id"] for r in results]
        assert entry_id_1 in matching_ids

    def test_retrieval_updates_loaded_count(self, in_memory_db, mock_config):
        """检索返回的条目应递增 loaded_count。"""
        from src.data.repos.brain_repository import BrainRepository
        from src.business.brain.retrieval_service import RetrievalService

        repo = BrainRepository()

        entry_id = repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="测试预算条目",
            origin="decay",
            reason="test",
        )

        entry_before = repo.get_entry(entry_id)
        loaded_before = entry_before.loaded_count

        service = RetrievalService(brain_repo=repo)
        service.retrieve_archive("预算")

        entry_after = repo.get_entry(entry_id)
        assert entry_after.loaded_count > loaded_before

    def test_cross_segment_archive_entries_retrievable(self, in_memory_db, mock_config):
        """来自不同 Segment 的归档条目都应可检索。"""
        from src.data.repos.brain_repository import BrainRepository
        from src.business.brain.retrieval_service import RetrievalService

        repo = BrainRepository()

        session_1 = uuid4().hex[:50]
        session_2 = uuid4().hex[:50]

        repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="第一个 Segment 的预算讨论",
            origin="decay",
            reason="Segment 1 decay",
            source_session_id=session_1,
        )
        repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="第二个 Segment 的预算更新",
            origin="decay",
            reason="Segment 2 decay",
            source_session_id=session_2,
        )

        service = RetrievalService(brain_repo=repo)
        results = service.retrieve_archive("预算")

        assert len(results) >= 2

    def test_archive_retrieval_returns_composite_scores(self, in_memory_db, mock_config):
        """检索结果应包含 composite_score 用于排序。"""
        from src.data.repos.brain_repository import BrainRepository
        from src.business.brain.retrieval_service import RetrievalService

        repo = BrainRepository()

        repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="预算审核 A",
            origin="decay",
            reason="test",
        )

        service = RetrievalService(brain_repo=repo)
        results = service.retrieve_archive("预算")

        for result in results:
            assert "composite_score" in result
            assert isinstance(result["composite_score"], float)

    def test_invalidated_archive_entry_still_retrievable(self, in_memory_db, mock_config):
        """invalidated 状态的归档条目仍应可检索。"""
        from src.data.repos.brain_repository import BrainRepository
        from src.business.brain.retrieval_service import RetrievalService

        repo = BrainRepository()

        entry_id = repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="已过时的预算假设",
            origin="decay",
            reason="test",
        )
        repo.update_entry_status(entry_id, "invalidated")

        service = RetrievalService(brain_repo=repo)
        results = service.retrieve_archive("预算")

        matching = [r for r in results if r["entry_id"] == entry_id]
        assert len(matching) >= 1


class TestInvalidateMemoryEntryContextBoundary:
    """invalidate_memory_entry 的上下文窗口安全边界。"""

    def test_invalidate_rejects_entry_outside_context_window(self, in_memory_db, mock_config):
        """entry 不在当前上下文窗口内时拒绝 invalidation。"""
        from src.data.repos.brain_repository import BrainRepository
        from src.business.brain.retrieval_service import RetrievalService

        repo = BrainRepository()
        entry_id = repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="测试归档条目",
            origin="decay",
            reason="test",
        )

        service = RetrievalService(brain_repo=repo)
        result = service.invalidate_memory_entry(
            entry_id,
            reason="过期",
            current_context_entry_ids=["other-id-1", "other-id-2"],
        )

        assert result["success"] is False
        assert "outside the current context window" in result["message"]
        entry = repo.get_entry(entry_id)
        assert entry.status != "invalidated"

    def test_invalidate_allows_entry_within_context_window(self, in_memory_db, mock_config):
        """entry 在当前上下文窗口内时允许 invalidation。"""
        from src.data.repos.brain_repository import BrainRepository
        from src.business.brain.retrieval_service import RetrievalService

        repo = BrainRepository()
        entry_id = repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="可被 invalidate 的条目",
            origin="decay",
            reason="test",
        )

        service = RetrievalService(brain_repo=repo)
        result = service.invalidate_memory_entry(
            entry_id,
            reason="信息已过期",
            current_context_entry_ids=[entry_id, "other-id"],
        )

        assert result["success"] is True
        entry = repo.get_entry(entry_id)
        assert entry.status == "invalidated"

    def test_invalidate_with_no_context_restriction_succeeds(self, in_memory_db, mock_config):
        """current_context_entry_ids=None 表示不限制上下文，允许 invalidation。"""
        from src.data.repos.brain_repository import BrainRepository
        from src.business.brain.retrieval_service import RetrievalService

        repo = BrainRepository()
        entry_id = repo.create_entry(
            zone=Zone.ARCHIVE.value,
            content="无限制 invalidation 测试",
            origin="decay",
            reason="test",
        )

        service = RetrievalService(brain_repo=repo)
        result = service.invalidate_memory_entry(
            entry_id,
            reason="不限制上下文",
            current_context_entry_ids=None,
        )

        assert result["success"] is True

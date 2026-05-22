"""
归档区检索服务测试 (T048)

覆盖：
- 归档区关键词检索与复合评分排序
- invalidated 条目降权但仍可检索
- 空查询返回空结果
- 检索结果有效性比加权（referenced_count / loaded_count）
- 探索加分（新条目额外加权）
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock

from src.business.brain.models import Zone
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


class TestArchiveRetrievalRanking:
    """归档区检索应按复合评分排序。"""

    def test_archive_search_returns_matching_entries(self):
        """关键词匹配的归档区条目应被返回。"""
        from src.business.brain.retrieval_service import RetrievalService

        mock_repo = MagicMock()
        entry_id = uuid4().hex[:50]
        matching_entry = MagicMock(
            entry_id=entry_id,
            zone=Zone.ARCHIVE.value,
            content="用户讨论了季度预算审核",
            status="active",
            relevance_score=0.8,
            loaded_count=3,
            referenced_count=1,
            created_at="2025-01-01T00:00:00",
        )

        mock_repo.search_archive_entries.return_value = [matching_entry]

        service = RetrievalService(brain_repo=mock_repo)
        results = service.retrieve_archive("预算")

        assert len(results) >= 1
        assert results[0]["entry_id"] == entry_id

    def test_archive_search_ranked_by_composite_score(self):
        """检索结果应按复合评分排序（relevance + recency + effectiveness + exploration）。"""
        from src.business.brain.retrieval_service import RetrievalService

        mock_repo = MagicMock()
        entries = [
            MagicMock(
                entry_id="low-relevance",
                zone=Zone.ARCHIVE.value,
                content="预算讨论 A",
                status="active",
                relevance_score=0.3,
                loaded_count=10,
                referenced_count=0,
                created_at="2025-01-01T00:00:00",
            ),
            MagicMock(
                entry_id="high-relevance",
                zone=Zone.ARCHIVE.value,
                content="预算讨论 B",
                status="active",
                relevance_score=0.9,
                loaded_count=5,
                referenced_count=3,
                created_at="2025-06-01T00:00:00",
            ),
        ]

        mock_repo.search_archive_entries.return_value = entries

        service = RetrievalService(brain_repo=mock_repo)
        results = service.retrieve_archive("预算")

        assert len(results) == 2
        assert results[0]["entry_id"] == "high-relevance"

    def test_archive_search_empty_query_returns_empty(self):
        """空查询应返回空结果。"""
        from src.business.brain.retrieval_service import RetrievalService

        mock_repo = MagicMock()
        service = RetrievalService(brain_repo=mock_repo)
        results = service.retrieve_archive("")

        assert results == []
        mock_repo.search_archive_entries.assert_not_called()


class TestInvalidatedFallback:
    """invalidated 条目应可检索但降权。"""

    def test_invalidated_entries_included_with_degraded_weight(self):
        """invalidated 条目应包含在结果中但排在非 invalidated 条目之后。"""
        from src.business.brain.retrieval_service import RetrievalService

        mock_repo = MagicMock()
        entries = [
            MagicMock(
                entry_id="invalidated-entry",
                zone=Zone.ARCHIVE.value,
                content="旧的预算假设",
                status="invalidated",
                relevance_score=0.9,
                loaded_count=5,
                referenced_count=2,
                created_at="2025-01-01T00:00:00",
            ),
            MagicMock(
                entry_id="active-entry",
                zone=Zone.ARCHIVE.value,
                content="新的预算假设",
                status="active",
                relevance_score=0.7,
                loaded_count=2,
                referenced_count=1,
                created_at="2025-06-01T00:00:00",
            ),
        ]

        mock_repo.search_archive_entries.return_value = entries

        service = RetrievalService(brain_repo=mock_repo)
        results = service.retrieve_archive("预算")

        assert len(results) == 2
        # active 条目应排在 invalidated 之前（即使 relevance 更低）
        assert results[0]["entry_id"] == "active-entry"
        assert results[1]["entry_id"] == "invalidated-entry"
        assert results[1]["invalidation_factor"] == 0.5

    def test_only_invalidated_entries_still_returned(self):
        """如果只有 invalidated 条目匹配，仍应返回结果。"""
        from src.business.brain.retrieval_service import RetrievalService

        mock_repo = MagicMock()
        invalidated_entry = MagicMock(
            entry_id="only-invalidated",
            zone=Zone.ARCHIVE.value,
            content="已过时的预算信息",
            status="invalidated",
            relevance_score=0.8,
            loaded_count=1,
            referenced_count=0,
            created_at="2025-01-01T00:00:00",
        )

        mock_repo.search_archive_entries.return_value = [invalidated_entry]

        service = RetrievalService(brain_repo=mock_repo)
        results = service.retrieve_archive("预算")

        assert len(results) == 1
        assert results[0]["entry_id"] == "only-invalidated"
        assert results[0]["invalidation_factor"] == 0.5


class TestEffectivenessScoring:
    """有效性比（referenced_count / loaded_count）应影响排序。"""

    def test_higher_effectiveness_ranks_higher(self):
        """有效性比更高的条目应排名更高。"""
        from src.business.brain.retrieval_service import RetrievalService

        mock_repo = MagicMock()
        entries = [
            MagicMock(
                entry_id="low-eff",
                zone=Zone.ARCHIVE.value,
                content="预算讨论低效",
                status="active",
                relevance_score=0.8,
                loaded_count=10,
                referenced_count=0,
                created_at="2025-06-01T00:00:00",
            ),
            MagicMock(
                entry_id="high-eff",
                zone=Zone.ARCHIVE.value,
                content="预算讨论高效",
                status="active",
                relevance_score=0.8,
                loaded_count=5,
                referenced_count=4,
                created_at="2025-06-01T00:00:00",
            ),
        ]

        mock_repo.search_archive_entries.return_value = entries

        service = RetrievalService(brain_repo=mock_repo)
        results = service.retrieve_archive("预算")

        assert results[0]["entry_id"] == "high-eff"


class TestExplorationAllowance:
    """新条目（loaded_count 很低）应获得探索加分。"""

    def test_new_entry_gets_exploration_bonus(self):
        """新条目应获得额外探索加分，可能排名高于纯 relevance 更高的条目。"""
        from src.business.brain.retrieval_service import RetrievalService

        mock_repo = MagicMock()
        entries = [
            MagicMock(
                entry_id="old-high-relevance",
                zone=Zone.ARCHIVE.value,
                content="预算讨论 A",
                status="active",
                relevance_score=0.85,
                loaded_count=100,
                referenced_count=50,
                created_at="2024-01-01T00:00:00",
            ),
            MagicMock(
                entry_id="new-low-relevance",
                zone=Zone.ARCHIVE.value,
                content="预算讨论 B",
                status="active",
                relevance_score=0.7,
                loaded_count=0,
                referenced_count=0,
                created_at="2025-06-01T00:00:00",
            ),
        ]

        mock_repo.search_archive_entries.return_value = entries

        service = RetrievalService(brain_repo=mock_repo)
        results = service.retrieve_archive("预算")

        # 新条目因探索加分和 recency 加分应排名较高
        assert results[0]["entry_id"] == "new-low-relevance"

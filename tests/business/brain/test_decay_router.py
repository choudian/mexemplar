"""
热区衰减路由测试 (T049)

覆盖：
- fading 阈值以下的条目标记为 fading
- event 类型条目从 fading 路由到归档区
- insight 类型条目从 fading 路由到持久区（relevance_score 不太低时）
- insight 类型条目 relevance_score 极低时软删除
- 非 hot 区条目不受影响
"""

import pytest
from unittest.mock import MagicMock

from src.business.brain.models import Zone
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


class TestFadingThreshold:
    """relevance_score 低于 fading_threshold 的热区条目应标记为 fading。"""

    def test_below_threshold_marked_fading(self):
        """relevance_score 低于阈值的 active 条目应标记为 fading。"""
        from src.business.brain.decay_router import DecayRouter

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_decay_fading_threshold.return_value = 0.3

        entries = [
            MagicMock(
                entry_id="low-score",
                zone=Zone.HOT.value,
                status="active",
                relevance_score=0.2,
                entry_type="event",
            ),
        ]
        mock_repo.get_entries_by_zone.return_value = (entries, 1)

        router = DecayRouter(brain_repo=mock_repo, config=mock_config)
        router.run_decay_sweep()

        mock_repo.update_entry_status.assert_called_with("low-score", "fading")

    def test_above_threshold_not_marked_fading(self):
        """relevance_score 高于阈值的条目应保持 active。"""
        from src.business.brain.decay_router import DecayRouter

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_decay_fading_threshold.return_value = 0.3

        entries = [
            MagicMock(
                entry_id="high-score",
                zone=Zone.HOT.value,
                status="active",
                relevance_score=0.8,
                entry_type="event",
            ),
        ]
        mock_repo.get_entries_by_zone.return_value = (entries, 1)

        router = DecayRouter(brain_repo=mock_repo, config=mock_config)
        router.run_decay_sweep()

        # 不应调用 update_entry_status 将其标记为 fading
        calls = [
            c
            for c in mock_repo.update_entry_status.call_args_list
            if c == pytest.approx(("high-score", "fading"))
        ]
        assert len(calls) == 0

    def test_exactly_at_threshold_not_marked_fading(self):
        """relevance_score 恰好等于阈值的条目不应被标记为 fading。"""
        from src.business.brain.decay_router import DecayRouter

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_decay_fading_threshold.return_value = 0.3

        entries = [
            MagicMock(
                entry_id="exact-threshold",
                zone=Zone.HOT.value,
                status="active",
                relevance_score=0.3,
                entry_type="event",
            ),
        ]
        mock_repo.get_entries_by_zone.return_value = (entries, 1)

        router = DecayRouter(brain_repo=mock_repo, config=mock_config)
        router.run_decay_sweep()

        fading_calls = [
            c
            for c in mock_repo.update_entry_status.call_args_list
            if c[0] == ("exact-threshold", "fading")
        ]
        assert len(fading_calls) == 0


class TestEventRouting:
    """event 类型的 fading 条目应路由到归档区。"""

    def test_event_fading_routed_to_archive(self):
        """event 类型的 fading 条目应被移动到 archive 区。"""
        from src.business.brain.decay_router import DecayRouter

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_decay_fading_threshold.return_value = 0.5

        # 先无 active 条目需要标记为 fading
        mock_repo.get_entries_by_zone.side_effect = lambda zone, status=None, limit=50, offset=0: (
            ([], 0)
            if status == "active"
            else (
                [
                    MagicMock(
                        entry_id="fading-event",
                        zone=Zone.HOT.value,
                        status="fading",
                        relevance_score=0.2,
                        entry_type="event",
                        content="Old event",
                        origin="distillation",
                        reason="test",
                        scope=None,
                        source_segment_id=None,
                        source_session_id=None,
                    ),
                ],
                1,
            )
        )

        router = DecayRouter(brain_repo=mock_repo, config=mock_config)
        router.run_decay_sweep()

        # 验证归档区写入被调用
        mock_repo.create_entry.assert_called()
        call_kwargs = mock_repo.create_entry.call_args[1]
        assert call_kwargs["zone"] == Zone.ARCHIVE.value
        assert call_kwargs["origin"] == "decay"

        # 验证旧条目被软删除
        mock_repo.soft_delete_entry.assert_called_with(
            "fading-event", superseded_by=mock_repo.create_entry.return_value
        )


class TestInsightRouting:
    """insight 类型的 fading 条目应路由到持久区或软删除。"""

    def test_insight_fading_routed_to_persistent(self):
        """insight 类型且 relevance_score 不太低的 fading 条目应路由到持久区。"""
        from src.business.brain.decay_router import DecayRouter

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_decay_fading_threshold.return_value = 0.5

        mock_repo.get_entries_by_zone.side_effect = lambda zone, status=None, limit=50, offset=0: (
            ([], 0)
            if status == "active"
            else (
                [
                    MagicMock(
                        entry_id="fading-insight",
                        zone=Zone.HOT.value,
                        status="fading",
                        relevance_score=0.2,
                        entry_type="insight",
                        content="Important insight",
                        origin="distillation",
                        reason="test",
                        scope=None,
                        source_segment_id=None,
                        source_session_id=None,
                    ),
                ],
                1,
            )
        )

        router = DecayRouter(brain_repo=mock_repo, config=mock_config)
        router.run_decay_sweep()

        mock_repo.create_entry.assert_called()
        call_kwargs = mock_repo.create_entry.call_args[1]
        assert call_kwargs["zone"] == Zone.PERSISTENT.value

    def test_insight_very_low_relevance_soft_deleted(self):
        """insight 类型且 relevance_score 极低（<0.1）的 fading 条目应被软删除。"""
        from src.business.brain.decay_router import DecayRouter

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_decay_fading_threshold.return_value = 0.5

        mock_repo.get_entries_by_zone.side_effect = lambda zone, status=None, limit=50, offset=0: (
            ([], 0)
            if status == "active"
            else (
                [
                    MagicMock(
                        entry_id="very-low-insight",
                        zone=Zone.HOT.value,
                        status="fading",
                        relevance_score=0.05,
                        entry_type="insight",
                        content="Trivial insight",
                        origin="distillation",
                        reason="test",
                    ),
                ],
                1,
            )
        )

        router = DecayRouter(brain_repo=mock_repo, config=mock_config)
        router.run_decay_sweep()

        # 极低 relevance 的 insight 应被软删除，不创建新条目
        mock_repo.soft_delete_entry.assert_called_with("very-low-insight")
        # 不应创建到持久区
        persistent_calls = [
            c
            for c in mock_repo.create_entry.call_args_list
            if c[1].get("zone") == Zone.PERSISTENT.value
        ]
        assert len(persistent_calls) == 0


class TestNonHotZoneUnaffected:
    """非 hot 区条目不应受衰减路由影响。"""

    def test_persistent_entries_not_decayed(self):
        """持久区条目不应被衰减路由处理。"""
        from src.business.brain.decay_router import DecayRouter

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_decay_fading_threshold.return_value = 0.5

        mock_repo.get_entries_by_zone.return_value = ([], 0)

        router = DecayRouter(brain_repo=mock_repo, config=mock_config)
        router.run_decay_sweep()

        # 不应对非 hot 区做任何修改
        mock_repo.update_entry_status.assert_not_called()
        mock_repo.create_entry.assert_not_called()
        mock_repo.soft_delete_entry.assert_not_called()

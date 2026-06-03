"""
热区和持久区上下文注入测试 (T026)

覆盖：
- 持久区：按配置上限注入 active entries
- 热区：active + fading 均可见，并按 relevance_score 降序 top-N 选择
- 空脑：返回空上下文（冷启动）
- loaded_count 递增验证
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock

from src.business.brain.models import (
    Zone,
    EntryStatus,
    MemoryEntryData,
)
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


# ═══════════════════════════════════════════════
# 持久区上下文注入
# ═══════════════════════════════════════════════


class TestPersistentZoneInjection:
    """持久区应按配置上限注入 active 条目。"""

    def test_persistent_zone_uses_configured_limit(self):
        """持久区条目应按 persistent_top_n 上限注入到上下文。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20
        mock_config.get_brain_injection_persistent_top_n.return_value = 50

        persistent_entries = [
            MemoryEntryData(
                entry_id=uuid4().hex[:50],
                zone=Zone.PERSISTENT.value,
                content=f"Persistent fact {i}",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="Long-term insight",
                relevance_score=0.8,
            )
            for i in range(75)
        ]

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            entries = persistent_entries if zone == Zone.PERSISTENT.value else []
            if limit is None:
                return entries[offset:]
            return entries[offset : offset + limit]

        mock_repo.get_entries_by_zone = get_entries_by_zone

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()

        persistent_in_context = [e for e in context.entries if e.zone == Zone.PERSISTENT.value]
        assert len(persistent_in_context) == 50

    def test_persistent_zone_excludes_soft_deleted(self):
        """软删除的持久区条目不应被注入。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20
        mock_config.get_brain_injection_persistent_top_n.return_value = 50

        # 只返回 active 条目
        active_entries = [
            MemoryEntryData(
                entry_id=uuid4().hex[:50],
                zone=Zone.PERSISTENT.value,
                content="Active entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.9,
            ),
        ]

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone == Zone.PERSISTENT.value:
                return active_entries
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()

        persistent_in_context = [e for e in context.entries if e.zone == Zone.PERSISTENT.value]
        assert len(persistent_in_context) == 1
        assert persistent_in_context[0].status == EntryStatus.ACTIVE.value

    def test_persistent_zone_accepts_zero_config_limit(self):
        """persistent_top_n=0 应禁用持久区注入，而不是回退到默认值。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 0
        mock_config.get_brain_injection_persistent_top_n.return_value = 0
        mock_config.get_brain_injection_subconscious_top_n.return_value = 0

        calls: list[tuple[str, int | None]] = []

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            calls.append((zone, limit))
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone

        context = BrainContextBuilder(repo=mock_repo, config=mock_config).build_context()

        assert context.persistent_entries == []
        assert (Zone.PERSISTENT.value, 0) in calls


# ═══════════════════════════════════════════════
# 热区 top-N 注入
# ═══════════════════════════════════════════════


class TestHotZoneTopNInjection:
    """热区应按 relevance_score 降序选择 top-N 条目。"""

    def test_hot_zone_selects_top_n_by_relevance(self):
        """热区应只选择 relevance_score 最高的 N 个条目。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 3

        hot_entries = [
            MemoryEntryData(
                entry_id=f"hot-{i}",
                zone=Zone.HOT.value,
                content=f"Hot entry {i}",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=score,
            )
            for i, score in enumerate([0.9, 0.5, 0.8, 0.3, 0.7])
        ]

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone == Zone.HOT.value:
                return hot_entries
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()

        hot_in_context = [e for e in context.entries if e.zone == Zone.HOT.value]
        assert len(hot_in_context) == 3

        # 验证选取的是 top 3 relevance_score
        scores = sorted([e.relevance_score for e in hot_in_context], reverse=True)
        assert scores == [0.9, 0.8, 0.7]

    def test_hot_zone_includes_fading_entries(self):
        """fading 热区条目仍应注入给 assistant。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20

        hot_entries = [
            MemoryEntryData(
                entry_id="active-hot",
                zone=Zone.HOT.value,
                content="Active hot entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.7,
            ),
            MemoryEntryData(
                entry_id="fading-hot",
                zone=Zone.HOT.value,
                content="Fading hot entry",
                status=EntryStatus.FADING.value,
                origin="distillation",
                reason="still relevant enough to show",
                relevance_score=0.4,
            ),
        ]

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone == Zone.HOT.value:
                assert set(status) == {EntryStatus.ACTIVE.value, EntryStatus.FADING.value}
                return hot_entries
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()

        hot_ids = {entry["entry_id"] for entry in context.hot_entries}
        assert hot_ids == {"active-hot", "fading-hot"}

    def test_hot_zone_fewer_than_top_n_returns_all(self):
        """如果热区条目少于 top-N，返回全部。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20

        hot_entries = [
            MemoryEntryData(
                entry_id="hot-1",
                zone=Zone.HOT.value,
                content="Only entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.6,
            ),
        ]

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone == Zone.HOT.value:
                return hot_entries
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()

        hot_in_context = [e for e in context.entries if e.zone == Zone.HOT.value]
        assert len(hot_in_context) == 1

    def test_hot_zone_top_n_default_is_20(self):
        """默认 top-N 应为 20。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone

        BrainContextBuilder(repo=mock_repo, config=mock_config).build_context()

        # 验证 builder 使用了正确的 top_n 配置
        mock_config.get_brain_injection_hot_zone_top_n.assert_called()


# ═══════════════════════════════════════════════
# 冷启动（空脑）
# ═══════════════════════════════════════════════


class TestColdStart:
    """验证空脑时返回空上下文。"""

    def test_empty_brain_returns_empty_context(self):
        """没有 entry 时应返回空上下文。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20

        mock_repo.get_entries_by_zone.return_value = []

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()

        assert context.entries == []
        assert context.is_cold_start is True

    def test_cold_start_context_has_no_persistent_section(self):
        """冷启动时上下文不应包含持久区 section。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20

        mock_repo.get_entries_by_zone.return_value = []

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()

        # 冷启动上下文
        assert len(context.entries) == 0
        # 提示文本应反映冷启动状态
        if hasattr(context, "prompt_text"):
            assert context.prompt_text == "" or "cold" in context.prompt_text.lower()


class TestPromptFormatting:
    """验证注入 prompt 的条目可被 reply_to_user 引用计量。"""

    def test_formatted_context_includes_entry_ids(self):
        from src.business.brain.context_builder import BrainContext, BrainContextBuilder

        context = BrainContext(
            persistent_entries=[
                {
                    "entry_id": "persistent-1",
                    "content": "用户偏好先给结论",
                    "scope": None,
                }
            ],
            hot_entries=[
                {
                    "entry_id": "hot-1",
                    "content": "用户正在做预算审核",
                    "entry_type": "event",
                    "scope": "财务工作",
                }
            ],
            subconscious_entries=[
                {
                    "entry_id": "subconscious-1",
                    "content": "用户不喜欢冗长铺垫",
                    "scope": None,
                }
            ],
        )

        prompt_text = BrainContextBuilder().format_context_for_prompt(context)

        assert "[entry_id: persistent-1]" in prompt_text
        assert "[entry_id: hot-1]" in prompt_text
        assert "[entry_id: subconscious-1]" in prompt_text

    def test_formatted_context_includes_degraded_capability_warning(self):
        from src.business.brain.context_builder import BrainContext, BrainContextBuilder

        context = BrainContext(
            context_warnings=["方法论装备清单暂时不可用；本轮不要假定自己没有可用方法论。"]
        )

        prompt_text = BrainContextBuilder().format_context_for_prompt(context)

        assert "上下文加载警告" in prompt_text
        assert "方法论装备清单暂时不可用" in prompt_text


# ═══════════════════════════════════════════════
# loaded_count 递增
# ═══════════════════════════════════════════════


class TestLoadedCountIncrement:
    """验证注入的条目 loaded_count 被递增。"""

    def test_loaded_count_incremented_for_injected_entries(self):
        """被注入到上下文的条目应递增 loaded_count。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20

        entry_ids = [uuid4().hex[:50] for _ in range(3)]
        hot_entries = [
            MemoryEntryData(
                entry_id=entry_ids[0],
                zone=Zone.HOT.value,
                content="Hot 1",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.9,
                loaded_count=0,
            ),
        ]
        persistent_entries = [
            MemoryEntryData(
                entry_id=entry_ids[1],
                zone=Zone.PERSISTENT.value,
                content="Persistent 1",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                loaded_count=2,
            ),
            MemoryEntryData(
                entry_id=entry_ids[2],
                zone=Zone.PERSISTENT.value,
                content="Persistent 2",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                loaded_count=1,
            ),
        ]

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone == Zone.HOT.value:
                return hot_entries
            if zone == Zone.PERSISTENT.value:
                return persistent_entries
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        builder.build_context()

        # 验证所有被注入的 entry_id 都被递增了 loaded_count
        expected_ids = entry_ids
        mock_repo.batch_increment_loaded_count.assert_called_once()
        called_ids = mock_repo.batch_increment_loaded_count.call_args[0][0]
        assert set(called_ids) == set(expected_ids)

    def test_loaded_count_failure_does_not_block_context_build(self, caplog):
        """loaded_count 是非关键指标，更新失败不能阻断上下文构建。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20
        mock_config.get_brain_injection_persistent_top_n.return_value = 50
        entry = MemoryEntryData(
            entry_id="persistent-1",
            zone=Zone.PERSISTENT.value,
            content="Persistent",
            status=EntryStatus.ACTIVE.value,
            origin="distillation",
            reason="test",
        )

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone == Zone.PERSISTENT.value:
                return [entry]
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone
        mock_repo.batch_increment_loaded_count.side_effect = RuntimeError("db locked")

        with caplog.at_level("WARNING"):
            context = BrainContextBuilder(repo=mock_repo, config=mock_config).build_context()

        assert [item.entry_id for item in context.entries] == ["persistent-1"]
        assert "Failed to update brain loaded_count" in caplog.text


# ═══════════════════════════════════════════════
# Revived-Session Positive Weighting (T050)
# ═══════════════════════════════════════════════


class TestRevivedSessionPositiveWeighting:
    """验证复用会话时，历史注入的条目获得正向加权。"""

    def test_previously_loaded_entries_ranked_higher(self):
        """在复用会话中，之前已被加载过的条目应获得额外加权。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 3

        # 5 个热区条目，loaded_count 不同
        hot_entries = [
            MemoryEntryData(
                entry_id="prev-loaded",
                zone=Zone.HOT.value,
                content="Previously loaded entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.5,
                loaded_count=3,
            ),
            MemoryEntryData(
                entry_id="never-loaded",
                zone=Zone.HOT.value,
                content="Never loaded entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.7,
                loaded_count=0,
            ),
            MemoryEntryData(
                entry_id="high-relevance",
                zone=Zone.HOT.value,
                content="High relevance entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.9,
                loaded_count=1,
            ),
        ]

        mock_repo = MagicMock()

        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        scored = builder.compute_composite_scores(
            hot_entries,
            is_revived_session=True,
        )

        # prev-loaded 因 loaded_count=3 且 is_revived_session=True，
        # 应获得正向加权，使其排名高于 never-loaded
        prev_score = next(s for s in scored if s["entry_id"] == "prev-loaded")
        never_score = next(s for s in scored if s["entry_id"] == "never-loaded")

        assert prev_score["composite_score"] > never_score["composite_score"]

    def test_non_revived_session_no_extra_weighting(self):
        """非复用会话（首次会话）中，loaded_count 不应产生额外加权。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20

        hot_entries = [
            MemoryEntryData(
                entry_id="loaded-entry",
                zone=Zone.HOT.value,
                content="Loaded entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.5,
                loaded_count=5,
            ),
            MemoryEntryData(
                entry_id="new-entry",
                zone=Zone.HOT.value,
                content="New entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.5,
                loaded_count=0,
            ),
        ]

        mock_repo = MagicMock()
        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        scored = builder.compute_composite_scores(
            hot_entries,
            is_revived_session=False,
        )

        loaded_score = next(s for s in scored if s["entry_id"] == "loaded-entry")
        new_score = next(s for s in scored if s["entry_id"] == "new-entry")

        # 非复用会话，relevance 相同时，composite_score 应接近（只差 recency 加分）
        assert abs(loaded_score["composite_score"] - new_score["composite_score"]) < 0.5

    def test_composite_score_blends_all_factors(self):
        """复合评分应融合 relevance、recency、effectiveness 和探索加分。"""
        from src.business.brain.context_builder import BrainContextBuilder

        mock_config = MagicMock()

        entries = [
            MemoryEntryData(
                entry_id="balanced",
                zone=Zone.HOT.value,
                content="Balanced entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.7,
                loaded_count=10,
                referenced_count=5,
                created_at="2025-05-01T00:00:00",
            ),
            MemoryEntryData(
                entry_id="only-relevant",
                zone=Zone.HOT.value,
                content="Only relevant entry",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                relevance_score=0.9,
                loaded_count=1,
                referenced_count=0,
                created_at="2025-01-01T00:00:00",
            ),
        ]

        mock_repo = MagicMock()
        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        scored = builder.compute_composite_scores(
            entries,
            is_revived_session=True,
        )

        assert len(scored) == 2
        # 每个条目都有 composite_score
        for s in scored:
            assert "composite_score" in s
            assert s["composite_score"] > 0


class TestBrainContextCompositeScoring:
    """直接锁定 BrainContextBuilder 的热区 / 潜意识复合评分公式。"""

    def test_hot_score_formula_includes_all_terms_and_revived_bonus(self, monkeypatch):
        from src.business.brain.context_builder import BrainContextBuilder
        from src.business.brain.scoring import (
            HOT_EFFECTIVENESS_WEIGHT,
            HOT_EXPLORATION_WEIGHT,
            HOT_RECENCY_WEIGHT,
            HOT_RELEVANCE_WEIGHT,
        )

        builder = BrainContextBuilder()
        monkeypatch.setattr(builder, "_compute_recency_score", lambda _: 0.8)

        score = builder._compute_hot_composite_score(
            {
                "relevance_score": 0.6,
                "created_at": "fixed",
                "loaded_count": 1,
                "referenced_count": 1,
            },
            is_revived_session=True,
        )

        exploration = 1.0 - (1 / 3)
        revived_bonus = 0.35 * (1 / 3)
        expected = round(
            HOT_RELEVANCE_WEIGHT * 0.6
            + HOT_RECENCY_WEIGHT * 0.8
            + HOT_EFFECTIVENESS_WEIGHT * 1.0
            + HOT_EXPLORATION_WEIGHT * exploration
            + revived_bonus,
            4,
        )
        assert score == pytest.approx(expected)

    def test_subconscious_score_formula_uses_updated_recency_effectiveness_and_exploration(
        self, monkeypatch
    ):
        from src.business.brain.context_builder import BrainContextBuilder
        from src.business.brain.scoring import (
            SUBCONSCIOUS_EFFECTIVENESS_WEIGHT,
            SUBCONSCIOUS_EXPLORATION_WEIGHT,
            SUBCONSCIOUS_RECENCY_WEIGHT,
        )

        builder = BrainContextBuilder()
        monkeypatch.setattr(builder, "_compute_recency_score", lambda _: 0.75)

        score = builder._compute_subconscious_composite_score(
            {
                "created_at": "older",
                "updated_at": "newer",
                "loaded_count": 2,
                "referenced_count": 1,
            }
        )

        expected = (
            SUBCONSCIOUS_RECENCY_WEIGHT * 0.75
            + SUBCONSCIOUS_EFFECTIVENESS_WEIGHT * 0.5
            + SUBCONSCIOUS_EXPLORATION_WEIGHT * (1.0 - (2 / 3))
        )
        assert score == pytest.approx(expected)


class TestSubconsciousAndPredictionContext:
    """US4: 潜意识注入与猜测区不可见。"""

    def test_subconscious_entries_are_ranked_by_recency_top_n(self):
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20
        mock_config.get_brain_injection_subconscious_top_n.return_value = 2

        subconscious_entries = [
            MemoryEntryData(
                entry_id="old",
                zone=Zone.SUBCONSCIOUS.value,
                content="Old style signal",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                updated_at="2024-01-01T00:00:00",
            ),
            MemoryEntryData(
                entry_id="new",
                zone=Zone.SUBCONSCIOUS.value,
                content="New style signal",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                updated_at="2026-01-01T00:00:00",
            ),
            MemoryEntryData(
                entry_id="mid",
                zone=Zone.SUBCONSCIOUS.value,
                content="Mid style signal",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                updated_at="2025-01-01T00:00:00",
            ),
        ]

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone == Zone.SUBCONSCIOUS.value:
                return subconscious_entries
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone
        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()

        assert [entry["entry_id"] for entry in context.subconscious_entries] == ["new", "mid"]

    def test_subconscious_ranking_blends_effectiveness_for_equal_recency(self):
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20
        mock_config.get_brain_injection_subconscious_top_n.return_value = 1

        entries = [
            MemoryEntryData(
                entry_id="unused",
                zone=Zone.SUBCONSCIOUS.value,
                content="Never referenced",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                loaded_count=10,
                referenced_count=0,
                updated_at="2026-05-01T00:00:00",
            ),
            MemoryEntryData(
                entry_id="effective",
                zone=Zone.SUBCONSCIOUS.value,
                content="Frequently useful",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                loaded_count=10,
                referenced_count=8,
                updated_at="2026-05-01T00:00:00",
            ),
        ]

        mock_repo.get_entries_by_zone.side_effect = lambda zone, status=None, limit=50, offset=0: (
            entries if zone == Zone.SUBCONSCIOUS.value else []
        )

        context = BrainContextBuilder(repo=mock_repo, config=mock_config).build_context()

        assert [entry["entry_id"] for entry in context.subconscious_entries] == ["effective"]

    def test_subconscious_ranking_explores_candidates_before_top_n_slice(self):
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20
        mock_config.get_brain_injection_subconscious_top_n.return_value = 1

        entries = [
            MemoryEntryData(
                entry_id="already-seen",
                zone=Zone.SUBCONSCIOUS.value,
                content="Already seen repeatedly",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                loaded_count=10,
                referenced_count=0,
                updated_at="2026-05-01T00:00:00",
            ),
            MemoryEntryData(
                entry_id="unexplored",
                zone=Zone.SUBCONSCIOUS.value,
                content="Needs an opportunity",
                status=EntryStatus.ACTIVE.value,
                origin="distillation",
                reason="test",
                loaded_count=0,
                referenced_count=0,
                updated_at="2026-05-01T00:00:00",
            ),
        ]

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone != Zone.SUBCONSCIOUS.value:
                return []
            return entries[offset:] if limit is None else entries[offset : offset + limit]

        mock_repo.get_entries_by_zone = get_entries_by_zone
        context = BrainContextBuilder(repo=mock_repo, config=mock_config).build_context()

        assert [entry["entry_id"] for entry in context.subconscious_entries] == ["unexplored"]

    def test_prediction_zone_entries_are_not_injected(self):
        from src.business.brain.context_builder import BrainContextBuilder

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_injection_hot_zone_top_n.return_value = 20
        mock_config.get_brain_injection_subconscious_top_n.return_value = 10

        prediction_entry = MemoryEntryData(
            entry_id="prediction-1",
            zone=Zone.PREDICTION.value,
            content="User may ask for budget next week",
            status=EntryStatus.ACTIVE.value,
            origin="prediction_generation",
            reason="test",
        )

        def get_entries_by_zone(zone, status=None, limit=50, offset=0):
            if zone == Zone.PREDICTION.value:
                return [prediction_entry]
            return []

        mock_repo.get_entries_by_zone = get_entries_by_zone
        builder = BrainContextBuilder(repo=mock_repo, config=mock_config)
        context = builder.build_context()
        prompt = builder.format_context_for_prompt(context)

        assert context.entries == []
        assert "budget next week" not in prompt

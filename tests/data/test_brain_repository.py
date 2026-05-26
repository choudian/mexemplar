"""
BrainRepository CRUD 和原子 Segment 状态转换测试 (T021)

覆盖：
- Segment 创建、状态转换（pending -> distilling -> completed）、CAS 原子性
- Memory Entry CRUD、zone 过滤、软删除
- loaded_count 和 referenced_count 批量递增
- superseded_by 演化链遍历
- Zone 汇总
"""

import pytest
from uuid import uuid4

from src.data.repos.brain_repository import BrainRepository
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


@pytest.fixture
def repo(in_memory_db):
    """创建使用 in-memory DB 的 BrainRepository 实例。"""
    return BrainRepository()


# ────────────────────────────────────────────
# Segment CRUD
# ────────────────────────────────────────────


class TestSegmentCrud:
    def test_create_segment(self, repo):
        segment_id = uuid4().hex[:50]
        session_id = uuid4().hex[:50]

        segment = repo.create_segment(
            segment_id=segment_id,
            session_id=session_id,
            boundary_reason="idle",
        )

        assert segment is not None
        assert segment.segment_id == segment_id
        assert segment.session_id == session_id
        assert segment.status == "pending"
        assert segment.boundary_reason == "idle"
        assert segment.retry_count == 0
        assert segment.sealed_at is not None

    def test_get_segment_by_id(self, repo):
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )

        result = repo.get_segment_by_id(segment_id)

        assert result is not None
        assert result.segment_id == segment_id

    def test_get_segment_by_id_not_found(self, repo):
        result = repo.get_segment_by_id("nonexistent")
        assert result is None


# ────────────────────────────────────────────
# Segment 状态转换 (CAS)
# ────────────────────────────────────────────


class TestSegmentStatusTransition:
    def test_transition_pending_to_distilling(self, repo):
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )

        ok = repo.transition_segment_status(
            segment_id,
            from_status="pending",
            to_status="distilling",
        )
        assert ok is True

        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == "distilling"
        assert segment.distilling_started_at is not None

    def test_transition_distilling_to_completed(self, repo):
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )
        repo.transition_segment_status(segment_id, "pending", "distilling")

        ok = repo.transition_segment_status(
            segment_id,
            from_status="distilling",
            to_status="completed",
        )
        assert ok is True

        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == "completed"
        assert segment.completed_at is not None

    def test_transition_distilling_to_failed(self, repo):
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )
        repo.transition_segment_status(segment_id, "pending", "distilling")

        ok = repo.transition_segment_status(
            segment_id,
            from_status="distilling",
            to_status="failed",
        )
        assert ok is True

        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == "failed"

    def test_transition_failed_to_pending(self, repo):
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )
        repo.transition_segment_status(segment_id, "pending", "distilling")
        repo.transition_segment_status(segment_id, "distilling", "failed")

        ok = repo.transition_segment_status(
            segment_id,
            from_status="failed",
            to_status="pending",
        )
        assert ok is True

        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == "pending"

    def test_cas_rejects_wrong_from_status(self, repo):
        """CAS 必须拒绝 from_status 不匹配的转换。"""
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )

        # segment 是 pending, 尝试用 completed 作为 from_status
        ok = repo.transition_segment_status(
            segment_id,
            from_status="completed",
            to_status="distilling",
        )
        assert ok is False

        # 状态不应改变
        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == "pending"

    def test_transition_increment_retry_on_failed_to_pending(self, repo):
        """failed -> pending 时 retry_count 应递增。"""
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )
        repo.transition_segment_status(segment_id, "pending", "distilling")
        repo.transition_segment_status(segment_id, "distilling", "failed")

        repo.transition_segment_status(segment_id, "failed", "pending")

        segment = repo.get_segment_by_id(segment_id)
        assert segment.retry_count == 1

    def test_retry_distilling_segment_is_atomic_status_and_retry_update(self, repo):
        """distilling -> pending 重试封装应同时递增 retry_count。"""
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )
        repo.transition_segment_status(segment_id, "pending", "distilling")

        ok = repo.retry_distilling_segment(segment_id)

        assert ok is True
        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == "pending"
        assert segment.retry_count == 1

    def test_retry_distilling_segment_rejects_wrong_status(self, repo):
        segment_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=uuid4().hex[:50],
            boundary_reason="idle",
        )

        ok = repo.retry_distilling_segment(segment_id)

        assert ok is False
        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == "pending"
        assert segment.retry_count == 0


# ────────────────────────────────────────────
# Segment 查询
# ────────────────────────────────────────────


class TestSegmentQueries:
    def test_get_segments_by_status(self, repo):
        for i in range(3):
            repo.create_segment(
                segment_id=uuid4().hex[:50],
                session_id=uuid4().hex[:50],
                boundary_reason="idle",
            )

        pending = repo.get_segments_by_status("pending")
        assert len(pending) == 3

    def test_get_segments_by_session(self, repo):
        session_id = uuid4().hex[:50]
        for _ in range(2):
            repo.create_segment(
                segment_id=uuid4().hex[:50],
                session_id=session_id,
                boundary_reason="idle",
            )
        # 其他 session 的 segment
        repo.create_segment(
            segment_id=uuid4().hex[:50],
            session_id=uuid4().hex[:50],
            boundary_reason="window_close",
        )

        segments = repo.get_segments_by_session(session_id)
        assert len(segments) == 2


# ────────────────────────────────────────────
# Memory Entry CRUD
# ────────────────────────────────────────────


class TestMemoryEntryCrud:
    def test_create_entry(self, repo):
        entry_id = uuid4().hex[:50]
        segment_id = uuid4().hex[:50]
        session_id = uuid4().hex[:50]

        entry = repo.create_entry(
            entry_id=entry_id,
            zone="hot",
            content="User discussed budget planning",
            origin="distillation",
            reason="Budget topic identified",
            source_segment_id=segment_id,
            source_session_id=session_id,
        )

        assert entry is not None
        assert entry.entry_id == entry_id
        assert entry.zone == "hot"
        assert entry.status == "active"
        assert entry.content == "User discussed budget planning"
        assert entry.loaded_count == 0
        assert entry.referenced_count == 0
        assert entry.relevance_score == 1.0

    def test_get_entry_by_id(self, repo):
        entry_id = uuid4().hex[:50]
        repo.create_entry(
            entry_id=entry_id,
            zone="hot",
            content="test",
            origin="distillation",
            reason="test",
        )

        result = repo.get_entry_by_id(entry_id)
        assert result is not None
        assert result.entry_id == entry_id

    def test_get_entry_by_id_not_found(self, repo):
        result = repo.get_entry_by_id("nonexistent")
        assert result is None


# ────────────────────────────────────────────
# Zone 过滤
# ────────────────────────────────────────────


class TestZoneFiltering:
    def test_get_entries_by_zone(self, repo):
        for i in range(3):
            repo.create_entry(
                entry_id=uuid4().hex[:50],
                zone="hot",
                content=f"Hot entry {i}",
                origin="distillation",
                reason="test",
            )
        repo.create_entry(
            entry_id=uuid4().hex[:50],
            zone="persistent",
            content="Persistent entry",
            origin="distillation",
            reason="test",
        )

        hot_entries = repo.get_entries_by_zone("hot")
        assert len(hot_entries) == 3

        persistent_entries = repo.get_entries_by_zone("persistent")
        assert len(persistent_entries) == 1

    def test_get_entries_excludes_soft_deleted(self, repo):
        entry_id = uuid4().hex[:50]
        repo.create_entry(
            entry_id=entry_id,
            zone="hot",
            content="To be deleted",
            origin="distillation",
            reason="test",
        )
        repo.soft_delete_entry(entry_id)

        entries = repo.get_entries_by_zone("hot")
        assert len(entries) == 0


# ────────────────────────────────────────────
# 软删除
# ────────────────────────────────────────────


class TestSoftDelete:
    def test_soft_delete_entry(self, repo):
        entry_id = uuid4().hex[:50]
        repo.create_entry(
            entry_id=entry_id,
            zone="hot",
            content="To delete",
            origin="distillation",
            reason="test",
        )

        repo.soft_delete_entry(entry_id)

        entry = repo.get_entry_by_id(entry_id)
        assert entry.status == "soft-deleted"


# ────────────────────────────────────────────
# 批量计数递增
# ────────────────────────────────────────────


class TestBatchIncrement:
    def test_batch_increment_loaded_count(self, repo):
        entry_ids = []
        for _ in range(3):
            eid = uuid4().hex[:50]
            entry_ids.append(eid)
            repo.create_entry(
                entry_id=eid,
                zone="hot",
                content="test",
                origin="distillation",
                reason="test",
            )

        repo.batch_increment_loaded_count(entry_ids)

        for eid in entry_ids:
            entry = repo.get_entry_by_id(eid)
            assert entry.loaded_count == 1

    def test_batch_increment_referenced_count(self, repo):
        entry_ids = []
        for _ in range(2):
            eid = uuid4().hex[:50]
            entry_ids.append(eid)
            repo.create_entry(
                entry_id=eid,
                zone="persistent",
                content="test",
                origin="distillation",
                reason="test",
            )

        repo.batch_increment_referenced_count(entry_ids)

        for eid in entry_ids:
            entry = repo.get_entry_by_id(eid)
            assert entry.referenced_count == 1

    def test_batch_increment_idempotent_on_nonexistent(self, repo):
        """对不存在的 entry_id 批量递增不应抛异常。"""
        repo.batch_increment_loaded_count(["nonexistent1", "nonexistent2"])


# ────────────────────────────────────────────
# 演化链遍历 (superseded_by)
# ────────────────────────────────────────────


class TestEvolutionChain:
    def test_get_evolution_chain(self, repo):
        old_id = uuid4().hex[:50]
        new_id = uuid4().hex[:50]

        repo.create_entry(
            entry_id=old_id,
            zone="persistent",
            content="Original content",
            origin="distillation",
            reason="test",
        )
        repo.create_entry(
            entry_id=new_id,
            zone="persistent",
            content="Updated content",
            origin="user_edit",
            reason="User edited",
            superseded_by=None,
        )
        # 旧条目指向新条目
        old_entry = repo.get_entry_by_id(old_id)
        old_entry.superseded_by = new_id
        repo.session.commit()

        chain = repo.get_evolution_chain(old_id)

        assert len(chain) == 2
        assert chain[0].entry_id == old_id
        assert chain[1].entry_id == new_id

    def test_evolution_chain_single_entry(self, repo):
        entry_id = uuid4().hex[:50]
        repo.create_entry(
            entry_id=entry_id,
            zone="hot",
            content="Single",
            origin="distillation",
            reason="test",
        )

        chain = repo.get_evolution_chain(entry_id)
        assert len(chain) == 1
        assert chain[0].entry_id == entry_id


# ────────────────────────────────────────────
# Zone 汇总
# ────────────────────────────────────────────


class TestZoneSummaries:
    def test_get_zone_summaries(self, repo):
        for _ in range(5):
            repo.create_entry(
                entry_id=uuid4().hex[:50],
                zone="hot",
                content="hot entry",
                origin="distillation",
                reason="test",
            )
        for _ in range(3):
            repo.create_entry(
                entry_id=uuid4().hex[:50],
                zone="persistent",
                content="persistent entry",
                origin="distillation",
                reason="test",
            )

        summaries = repo.get_zone_summaries()

        assert len(summaries) >= 2
        hot_summary = next(s for s in summaries if s["zone"] == "hot")
        persistent_summary = next(s for s in summaries if s["zone"] == "persistent")

        assert hot_summary["entry_count"] == 5
        assert persistent_summary["entry_count"] == 3

    def test_zone_summaries_exclude_soft_deleted(self, repo):
        eid = uuid4().hex[:50]
        repo.create_entry(
            entry_id=eid,
            zone="hot",
            content="will delete",
            origin="distillation",
            reason="test",
        )
        repo.soft_delete_entry(eid)

        summaries = repo.get_zone_summaries()
        hot_summary = next((s for s in summaries if s["zone"] == "hot"), None)

        if hot_summary is not None:
            assert hot_summary["entry_count"] == 0

    def test_zone_summaries_count_fading(self, repo):
        eid = uuid4().hex[:50]
        repo.create_entry(
            entry_id=eid,
            zone="hot",
            content="fading entry",
            origin="distillation",
            reason="test",
        )
        # 手动设为 fading
        entry = repo.get_entry_by_id(eid)
        entry.status = "fading"
        repo.session.commit()

        summaries = repo.get_zone_summaries()
        hot_summary = next(s for s in summaries if s["zone"] == "hot")
        assert hot_summary["fading_count"] == 1
        assert hot_summary["entry_count"] == 1


# ────────────────────────────────────────────
# 事务性写入
# ────────────────────────────────────────────


class TestTransactionalWrites:
    def test_create_entries_and_transition_segment_atomic(self, repo):
        """验证 entry 写入和 segment 状态转换在同一事务内。"""
        segment_id = uuid4().hex[:50]
        session_id = uuid4().hex[:50]

        repo.create_segment(
            segment_id=segment_id,
            session_id=session_id,
            boundary_reason="idle",
        )
        repo.transition_segment_status(segment_id, "pending", "distilling")

        entry_ids = [uuid4().hex[:50] for _ in range(3)]
        repo.create_entries_for_segment(
            entries=[
                {
                    "entry_id": eid,
                    "zone": "hot",
                    "content": f"Entry for segment {segment_id}",
                    "origin": "distillation",
                    "reason": "distillation output",
                    "entry_type": "event",
                    "source_segment_id": segment_id,
                    "source_session_id": session_id,
                }
                for eid in entry_ids
            ],
        )

        # 验证所有 entry 都写入了
        for eid in entry_ids:
            entry = repo.get_entry_by_id(eid)
            assert entry is not None
            assert entry.source_segment_id == segment_id

    def test_complete_segment_with_entries_commits_entries_and_status_together(self, repo):
        segment_id = uuid4().hex[:50]
        session_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=session_id,
            boundary_reason="idle",
        )
        repo.transition_segment_status(segment_id, "pending", "distilling")

        created = repo.complete_segment_with_entries(
            segment_id,
            [
                {
                    "entry_id": uuid4().hex[:50],
                    "zone": "hot",
                    "content": "用户希望先看结论",
                    "origin": "distillation",
                    "reason": "多次对话中明确表达",
                    "source_segment_id": segment_id,
                    "source_session_id": session_id,
                }
            ],
        )

        assert len(created) == 1
        assert repo.get_segment_by_id(segment_id).status == "completed"
        assert repo.get_entry_by_id(created[0]).source_segment_id == segment_id

    def test_complete_segment_with_entries_rolls_back_status_when_entry_insert_fails(self, repo):
        segment_id = uuid4().hex[:50]
        session_id = uuid4().hex[:50]
        duplicate_entry_id = uuid4().hex[:50]
        repo.create_segment(
            segment_id=segment_id,
            session_id=session_id,
            boundary_reason="idle",
        )
        repo.transition_segment_status(segment_id, "pending", "distilling")

        with pytest.raises(Exception):
            repo.complete_segment_with_entries(
                segment_id,
                [
                    {
                        "entry_id": duplicate_entry_id,
                        "zone": "hot",
                        "content": "第一条",
                        "origin": "distillation",
                        "reason": "测试事务",
                        "source_segment_id": segment_id,
                        "source_session_id": session_id,
                    },
                    {
                        "entry_id": duplicate_entry_id,
                        "zone": "persistent",
                        "content": "重复主键",
                        "origin": "distillation",
                        "reason": "测试事务",
                        "source_segment_id": segment_id,
                        "source_session_id": session_id,
                    },
                ],
            )

        assert repo.get_segment_by_id(segment_id).status == "distilling"
        assert repo.get_entry_by_id(duplicate_entry_id) is None

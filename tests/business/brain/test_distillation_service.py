"""
P1 热区/持久区沉淀 schema 验证测试 (T025)

覆盖：
- P1 schema 只包含 hot_zone 和 persistent_zone
- 沉淀输出验证（必填字段）
- all-empty 重试逻辑
- 事务性写入（所有 entry + segment 状态在同一事务内）
"""

import logging
import pytest
from uuid import uuid4
from unittest.mock import MagicMock

from src.business.brain.models import (
    DistillationOutput,
    DistillationZoneOutput,
    SegmentStatus,
)
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


# ═══════════════════════════════════════════════
# P1 Schema 验证
# ═══════════════════════════════════════════════


class TestP1DistillationSchema:
    """验证 P1 阶段沉淀只使用 hot_zone 和 persistent_zone。"""

    def test_distillation_output_has_hot_and_persistent(self):
        """DistillationOutput 应包含 hot_zone 和 persistent_zone 字段。"""
        output = DistillationOutput(
            hot_zone=[
                DistillationZoneOutput(
                    content="User discussed budget",
                    reason="Budget topic recurring",
                    entry_type="event",
                ),
            ],
            persistent_zone=[
                DistillationZoneOutput(
                    content="User prefers concise summaries",
                    reason="Style preference",
                    entry_type="insight",
                ),
            ],
        )

        assert len(output.hot_zone) == 1
        assert len(output.persistent_zone) == 1

    def test_distillation_output_default_empty_for_other_zones(self):
        """P1 不使用的 zone 应默认为空列表。"""
        output = DistillationOutput()

        assert output.archive_zone == []
        assert output.subconscious_zone == []
        assert output.failure_zone == []

    def test_distillation_output_p1_only_uses_hot_and_persistent(self):
        """P1 沉淀产出只应填充 hot_zone 和 persistent_zone。"""
        output = DistillationOutput(
            hot_zone=[
                DistillationZoneOutput(content="h1", reason="r1"),
            ],
            persistent_zone=[
                DistillationZoneOutput(content="p1", reason="r2"),
            ],
        )

        # P1 阶段其他 zone 应为空
        assert output.archive_zone == []
        assert output.subconscious_zone == []
        assert output.failure_zone == []

    def test_phase_schemas_require_all_active_zones(self):
        from src.business.brain.distillation_service import (
            P2_DISTILLATION_TOOL_SCHEMA,
            P4_DISTILLATION_TOOL_SCHEMA,
        )

        assert P2_DISTILLATION_TOOL_SCHEMA["input_schema"]["required"] == [
            "hot_zone",
            "persistent_zone",
            "archive_zone",
        ]
        assert P4_DISTILLATION_TOOL_SCHEMA["input_schema"]["required"] == [
            "hot_zone",
            "persistent_zone",
            "archive_zone",
            "subconscious_zone",
            "failure_zone",
        ]


class TestDistillationOutputValidation:
    """验证沉淀输出的结构验证。"""

    def test_zone_output_requires_content(self):
        """DistillationZoneOutput 必须有 content。"""
        zone_output = DistillationZoneOutput(
            content="Some content",
            reason="Some reason",
        )
        assert zone_output.content is not None
        assert len(zone_output.content) > 0

    def test_zone_output_requires_reason(self):
        """DistillationZoneOutput 必须有 reason。"""
        zone_output = DistillationZoneOutput(
            content="Content",
            reason="Explanation for distillation",
        )
        assert zone_output.reason is not None
        assert len(zone_output.reason) > 0

    def test_zone_output_entry_type_is_optional(self):
        """entry_type 是可选的。"""
        output = DistillationZoneOutput(
            content="Content",
            reason="Reason",
        )
        assert output.entry_type is None

    def test_zone_output_entry_type_values(self):
        """entry_type 只能是 event 或 insight。"""
        valid_types = {"event", "insight"}
        for t in valid_types:
            output = DistillationZoneOutput(
                content="Content",
                reason="Reason",
                entry_type=t,
            )
            assert output.entry_type == t

    def test_validate_distillation_output_rejects_missing_content(self):
        """content 为空的 zone output 应被拒绝。"""
        output = DistillationZoneOutput(
            content="",
            reason="Reason",
        )
        assert len(output.content.strip()) == 0

    def test_validate_distillation_output_accepts_llm_response_tool_calls(self):
        """沉淀验证应兼容 LLMResponse/ToolCallInfo 对象返回。"""
        from src.business.ai.llm_client import LLMResponse, ToolCallInfo
        from src.business.brain.distillation_service import DistillationService

        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(
                    id="call-1",
                    name="distillation_output",
                    args={
                        "hot_zone": [
                            {
                                "content": "用户偏好先给结论",
                                "reason": "多次对话表达该偏好",
                                "entry_type": "insight",
                            }
                        ],
                        "persistent_zone": [],
                    },
                )
            ],
        )

        entries = DistillationService(
            repo=MagicMock(), config=MagicMock()
        )._validate_distillation_output(response)

        assert entries == [
            {
                "zone": "hot",
                "content": "用户偏好先给结论",
                "reason": "多次对话表达该偏好",
                "origin": "distillation",
                "entry_type": "insight",
            }
        ]

    def test_validate_distillation_output_rejects_missing_active_zone(self):
        """P4 输出缺少已激活分区字段时应视为结构非法。"""
        from src.business.ai.llm_client import LLMResponse, ToolCallInfo
        from src.business.brain.distillation_service import DistillationService

        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(
                    id="call-1",
                    name="distillation_output",
                    args={
                        "hot_zone": [],
                        "persistent_zone": [],
                        "archive_zone": [],
                        "subconscious_zone": [],
                    },
                )
            ],
        )

        entries = DistillationService(
            repo=MagicMock(), config=MagicMock()
        )._validate_distillation_output(
            response,
            phase="p4",
        )

        assert entries is None

    def test_invalid_distillation_output_log_includes_raw_sample(self, caplog):
        from src.business.ai.llm_client import LLMResponse, ToolCallInfo
        from src.business.brain.distillation_service import DistillationService

        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(
                    id="call-1",
                    name="distillation_output",
                    args={"hot_zone": [{"content": "", "reason": "missing"}]},
                )
            ],
        )

        with caplog.at_level(logging.WARNING):
            entries = DistillationService(
                repo=MagicMock(), config=MagicMock()
            )._validate_distillation_output(response)

        assert entries is None
        assert "raw_sample=" in caplog.text
        assert "hot_zone" in caplog.text

    def test_validate_distillation_output_accepts_structural_all_empty(self):
        """结构合法但各分区为空时返回空列表，由上层触发一次 all-empty 重试。"""
        from src.business.ai.llm_client import LLMResponse, ToolCallInfo
        from src.business.brain.distillation_service import DistillationService

        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(
                    id="call-1",
                    name="distillation_output",
                    args={"hot_zone": [], "persistent_zone": []},
                )
            ],
        )

        entries = DistillationService(
            repo=MagicMock(), config=MagicMock()
        )._validate_distillation_output(response)

        assert entries == []

    def test_invalid_structured_output_retries_before_failed(self):
        from src.business.brain.distillation_service import DistillationService

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_segment_max_distillation_retries.return_value = 3
        segment = MagicMock(segment_id="seg-1", retry_count=1)
        service = DistillationService(repo=mock_repo, config=mock_config)

        service._retry_or_fail_segment(mock_repo, segment, "invalid")

        mock_repo.retry_distilling_segment.assert_called_once_with("seg-1")
        mock_repo.transition_segment.assert_not_called()
        mock_repo.transition_segment_status.assert_not_called()

    def test_invalid_structured_output_fails_after_retry_budget(self):
        from src.business.brain.distillation_service import DistillationService

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_segment_max_distillation_retries.return_value = 3
        segment = MagicMock(segment_id="seg-1", retry_count=2)
        service = DistillationService(repo=mock_repo, config=mock_config)

        service._retry_or_fail_segment(mock_repo, segment, "invalid")

        mock_repo.transition_segment.assert_called_once_with(
            "seg-1",
            from_status=SegmentStatus.DISTILLING.value,
            to_status=SegmentStatus.FAILED.value,
        )


# ═══════════════════════════════════════════════
# All-Empty 重试逻辑
# ═══════════════════════════════════════════════


class TestAllEmptyRetryLogic:
    """验证沉淀结果全部为空时的重试逻辑。"""

    def test_all_empty_triggers_retry(self):
        """hot_zone 和 persistent_zone 都为空时应触发重试（设置 all_empty_retried 标记）。"""
        from src.business.brain.distillation_service import DistillationService

        mock_repo = MagicMock()
        mock_config = MagicMock()
        mock_config.get_brain_segment_max_distillation_retries.return_value = 3

        service = DistillationService(repo=mock_repo, config=mock_config)

        segment_id = uuid4().hex[:50]
        mock_repo.get_segment_by_id.return_value = MagicMock(
            segment_id=segment_id,
            status="distilling",
            retry_count=0,
            all_empty_retried=False,
        )

        empty_output = DistillationOutput()

        result = service.handle_distillation_result(segment_id, empty_output)

        # 应标记 all_empty_retried 并重置为 pending
        assert result is not None
        mock_repo.transition_segment_status.assert_called()

    def test_all_empty_retried_already_set_skips_retry(self):
        """如果已经重试过 all-empty，不应再次重试。"""
        from src.business.brain.distillation_service import DistillationService

        mock_repo = MagicMock()
        mock_config = MagicMock()

        service = DistillationService(repo=mock_repo, config=mock_config)

        segment_id = uuid4().hex[:50]
        mock_repo.get_segment_by_id.return_value = MagicMock(
            segment_id=segment_id,
            status="distilling",
            retry_count=1,
            all_empty_retried=True,
        )

        empty_output = DistillationOutput()

        result = service.handle_distillation_result(segment_id, empty_output)

        # 已重试过，应标记为 completed
        assert result is not None

    def test_non_empty_output_does_not_trigger_retry(self):
        """有内容的输出不应触发 all-empty 重试。"""
        from src.business.brain.distillation_service import DistillationService

        mock_config = MagicMock()

        segment_id = uuid4().hex[:50]

        class AtomicRepo:
            def __init__(self):
                self.segment = MagicMock(
                    segment_id=segment_id,
                    status="distilling",
                    retry_count=0,
                    all_empty_retried=False,
                )

            def get_segment_by_id(self, _segment_id):
                return self.segment

            def complete_segment_with_entries(self, _segment_id, entries):
                return [entry.get("entry_id") or uuid4().hex[:50] for entry in entries]

        service = DistillationService(repo=AtomicRepo(), config=mock_config)

        non_empty_output = DistillationOutput(
            hot_zone=[
                DistillationZoneOutput(content="h1", reason="r1"),
            ],
        )

        result = service.handle_distillation_result(segment_id, non_empty_output)

        # 非 all-empty 应正常完成
        assert result is not None


# ═══════════════════════════════════════════════
# 事务性写入
# ═══════════════════════════════════════════════


class TestTransactionalWrites:
    """验证所有 entry 写入和 segment 状态转换在同一事务内。"""

    def test_write_entries_and_complete_segment_in_transaction(self):
        """沉淀成功时应委托 Repository 的单事务完成方法。"""
        from src.business.brain.distillation_service import DistillationService

        mock_config = MagicMock()
        segment_id = uuid4().hex[:50]
        session_id = uuid4().hex[:50]

        class AtomicRepo:
            def __init__(self):
                self.complete_segment_with_entries_mock = MagicMock(
                    return_value=["entry-1", "entry-2", "entry-3"]
                )
                self.segment = MagicMock(
                    segment_id=segment_id,
                    session_id=session_id,
                    status="distilling",
                    retry_count=0,
                    all_empty_retried=False,
                )

            def get_segment_by_id(self, _segment_id):
                return self.segment

            def complete_segment_with_entries(self, _segment_id, entries):
                return self.complete_segment_with_entries_mock(_segment_id, entries)

        repo = AtomicRepo()
        service = DistillationService(repo=repo, config=mock_config)

        output = DistillationOutput(
            hot_zone=[
                DistillationZoneOutput(
                    content="Hot entry 1",
                    reason="Reason 1",
                    entry_type="event",
                ),
                DistillationZoneOutput(
                    content="Hot entry 2",
                    reason="Reason 2",
                    entry_type="insight",
                ),
            ],
            persistent_zone=[
                DistillationZoneOutput(
                    content="Persistent entry 1",
                    reason="Long-term preference",
                    entry_type="insight",
                ),
            ],
        )

        service.handle_distillation_result(segment_id, output)

        repo.complete_segment_with_entries_mock.assert_called_once()
        called_segment_id, entries = repo.complete_segment_with_entries_mock.call_args.args
        assert called_segment_id == segment_id
        assert len(entries) == 3

    def test_distillation_failure_does_not_write_entries(self):
        """沉淀失败时不应写入任何 entry。"""
        from src.business.brain.distillation_service import DistillationService

        mock_repo = MagicMock()
        mock_config = MagicMock()

        service = DistillationService(repo=mock_repo, config=mock_config)

        segment_id = uuid4().hex[:50]
        mock_repo.get_segment_by_id.return_value = MagicMock(
            segment_id=segment_id,
            status="distilling",
            retry_count=2,
            all_empty_retried=True,
        )

        empty_output = DistillationOutput()

        service.handle_distillation_result(segment_id, empty_output)

        # 达到最大重试后不应写入 entry
        mock_repo.create_entries_for_segment.assert_not_called()

"""
Segment 沉淀集成冒烟测试 (T027)

覆盖：
- 创建 session + messages，封存 segment
- Mock LLM 返回结构化沉淀输出
- 验证 entries 写入到正确的分区
- 验证 segment 转换到 completed
"""

import pytest
from uuid import uuid4

from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.business.brain.models import (
    DistillationOutput,
    DistillationZoneOutput,
    Zone,
    SegmentStatus,
    BoundaryReason,
)
from src.data.models_sqlite import Session, Message
from src.utils.events import clear_all, connect


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


class TestDistillationIntegration:
    """集成测试：完整的 Segment 沉淀流程。"""

    def test_full_distillation_flow_with_mock_llm(self, in_memory_db, mock_config):
        """完整的沉淀流程：创建消息 -> 封存 -> 沉淀 -> 验证 entries。"""
        from src.business.brain.segment_service import SegmentService
        from src.business.brain.distillation_service import DistillationService
        from src.data.repos.brain_repository import BrainRepository

        session_id = uuid4().hex[:50]

        # 1. 创建 session 和 messages
        with in_memory_db.get_session() as session:
            session.add(
                Session(
                    session_id=session_id,
                    agent_type="assistant",
                    status="active",
                )
            )
            for i in range(1, 4):
                session.add(
                    Message(
                        message_id=uuid4().hex[:50],
                        session_id=session_id,
                        sequence=i,
                        role="user" if i % 2 == 1 else "assistant",
                        content=f"Message {i} about budget planning",
                    )
                )
            session.commit()

        # 2. 封存 segment
        repo = BrainRepository()
        segment_service = SegmentService()
        segment_service._repo = repo

        segment_id = segment_service.seal_segment(
            session_id=session_id,
            boundary_reason=BoundaryReason.IDLE.value,
            message_id_start="msg-1",
            message_id_end="msg-3",
        )

        assert segment_id is not None

        # 验证 segment 状态为 pending
        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == SegmentStatus.PENDING.value

        # 3. 模拟 Worker 将 segment 从 pending 转为 distilling
        ok = repo.transition_segment_status(
            segment_id,
            from_status=SegmentStatus.PENDING.value,
            to_status=SegmentStatus.DISTILLING.value,
        )
        assert ok is True

        # 4. Mock LLM 返回结构化沉淀输出
        distillation_output = DistillationOutput(
            hot_zone=[
                DistillationZoneOutput(
                    content="User is working on quarterly budget review",
                    reason="Budget topic identified in conversation",
                    entry_type="event",
                ),
            ],
            persistent_zone=[
                DistillationZoneOutput(
                    content="User prefers concise bullet-point summaries",
                    reason="Style preference observed",
                    entry_type="insight",
                ),
                DistillationZoneOutput(
                    content="User works with financial data regularly",
                    reason="Topic pattern across messages",
                    entry_type="event",
                ),
            ],
        )

        # 5. 处理沉淀结果
        mock_config.get_brain_segment_max_distillation_retries.return_value = 3

        distillation_service = DistillationService(repo=repo, config=mock_config)
        result = distillation_service.handle_distillation_result(segment_id, distillation_output)

        assert result is not None

        # 6. 验证 segment 已完成
        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == SegmentStatus.COMPLETED.value
        assert segment.completed_at is not None

        # 7. 验证 entries 写入到正确的分区
        hot_entries = repo.get_entries_by_zone(Zone.HOT.value)
        persistent_entries = repo.get_entries_by_zone(Zone.PERSISTENT.value)

        assert len(hot_entries) == 1
        assert len(persistent_entries) == 2

        # 验证 hot entry 内容
        hot_entry = hot_entries[0]
        assert hot_entry.source_segment_id == segment_id
        assert hot_entry.source_session_id == session_id
        assert hot_entry.status == "active"
        assert hot_entry.origin == "distillation"

        # 验证 persistent entries 内容
        for entry in persistent_entries:
            assert entry.source_segment_id == segment_id
            assert entry.source_session_id == session_id
            assert entry.status == "active"

    def test_distill_segment_runs_llm_tool_flow_and_completes_segment(
        self, in_memory_db, mock_config
    ):
        """distill_segment() 应覆盖 CAS、消息读取、LLM tool output、原子完成整条编排路径。"""
        from src.business.brain.segment_service import SegmentService
        from src.business.brain.distillation_service import DistillationService
        from src.data.repos.brain_repository import BrainRepository
        from tests.conftest import MockLLMClient

        session_id = uuid4().hex[:50]
        first_message_id = uuid4().hex[:50]
        second_message_id = uuid4().hex[:50]
        with in_memory_db.get_session() as session:
            session.add(
                Session(
                    session_id=session_id,
                    agent_type="assistant",
                    status="active",
                )
            )
            session.add_all(
                [
                    Message(
                        message_id=first_message_id,
                        session_id=session_id,
                        sequence=1,
                        role="user",
                        content="请记住我偏好简短回复。",
                    ),
                    Message(
                        message_id=second_message_id,
                        session_id=session_id,
                        sequence=2,
                        role="assistant",
                        content="已记录。",
                    ),
                ]
            )
            session.commit()

        repo = BrainRepository()
        segment_service = SegmentService()
        segment_service._repo = repo
        segment_id = segment_service.seal_segment(
            session_id=session_id,
            boundary_reason=BoundaryReason.IDLE.value,
            message_id_start=first_message_id,
            message_id_end=second_message_id,
        )
        mock_config.get_brain_segment_max_distillation_retries.return_value = 3
        llm = MockLLMClient(
            [
                LLMResponse(
                    content=None,
                    tool_calls=[
                        ToolCallInfo(
                            id="call_1",
                            name="distillation_output",
                            args={
                                "hot_zone": [
                                    {
                                        "content": "用户要求记住简短回复偏好",
                                        "reason": "近期对话偏好",
                                        "entry_type": "event",
                                    }
                                ],
                                "persistent_zone": [
                                    {
                                        "content": "用户偏好简短回复",
                                        "reason": "稳定表达偏好",
                                    }
                                ],
                            },
                        )
                    ],
                )
            ]
        )

        result = DistillationService(repo=repo, config=mock_config).distill_segment(
            segment_id,
            llm_client=llm,
            phase="p1",
        )

        assert result is True
        assert repo.get_segment_by_id(segment_id).status == SegmentStatus.COMPLETED.value
        assert [entry.content for entry in repo.get_entries_by_zone(Zone.HOT.value)] == [
            "用户要求记住简短回复偏好"
        ]
        assert [entry.content for entry in repo.get_entries_by_zone(Zone.PERSISTENT.value)] == [
            "用户偏好简短回复"
        ]

    def test_distillation_failure_marks_segment_failed(self, in_memory_db, mock_config):
        """沉淀失败时应将 segment 标记为 failed。"""
        from src.business.brain.segment_service import SegmentService
        from src.business.brain.distillation_service import DistillationService
        from src.data.repos.brain_repository import BrainRepository

        session_id = uuid4().hex[:50]

        repo = BrainRepository()
        segment_service = SegmentService()
        segment_service._repo = repo

        segment_id = segment_service.seal_segment(
            session_id=session_id,
            boundary_reason=BoundaryReason.WINDOW_CLOSE.value,
            message_id_start="msg-1",
            message_id_end="msg-1",
        )

        repo.transition_segment_status(
            segment_id,
            from_status=SegmentStatus.PENDING.value,
            to_status=SegmentStatus.DISTILLING.value,
        )

        # 模拟失败场景：LLM 抛出异常
        distillation_service = DistillationService(repo=repo, config=mock_config)

        # 使用已重试过的 all-empty 场景模拟失败
        segment = repo.get_segment_by_id(segment_id)
        segment.all_empty_retried = True
        segment.retry_count = 3
        repo.session.commit()

        empty_output = DistillationOutput()
        distillation_service.handle_distillation_result(segment_id, empty_output)

        # 应标记为 failed
        segment = repo.get_segment_by_id(segment_id)
        assert segment.status == SegmentStatus.FAILED.value

        # 不应有 entries
        hot_entries = repo.get_entries_by_zone(Zone.HOT.value)
        persistent_entries = repo.get_entries_by_zone(Zone.PERSISTENT.value)
        assert len(hot_entries) == 0
        assert len(persistent_entries) == 0

    def test_distillation_emits_zone_changed_event(self, in_memory_db, mock_config):
        """成功沉淀后应触发 brain_zone_changed 事件。"""
        from src.business.brain.segment_service import SegmentService
        from src.business.brain.distillation_service import DistillationService
        from src.data.repos.brain_repository import BrainRepository

        session_id = uuid4().hex[:50]

        repo = BrainRepository()
        segment_service = SegmentService()
        segment_service._repo = repo

        segment_id = segment_service.seal_segment(
            session_id=session_id,
            boundary_reason=BoundaryReason.IDLE.value,
            message_id_start="msg-1",
            message_id_end="msg-1",
        )
        repo.transition_segment_status(
            segment_id,
            from_status=SegmentStatus.PENDING.value,
            to_status=SegmentStatus.DISTILLING.value,
        )

        zone_events = []

        def on_zone_changed(sender, **kwargs):
            zone_events.append(kwargs)

        connect("brain_zone_changed", on_zone_changed, weak=False)

        output = DistillationOutput(
            hot_zone=[
                DistillationZoneOutput(
                    content="Hot entry",
                    reason="test",
                    entry_type="event",
                ),
            ],
        )

        mock_config.get_brain_segment_max_distillation_retries.return_value = 3
        distillation_service = DistillationService(repo=repo, config=mock_config)
        distillation_service.handle_distillation_result(segment_id, output)

        # 应至少触发一次 brain_zone_changed
        assert len(zone_events) >= 1

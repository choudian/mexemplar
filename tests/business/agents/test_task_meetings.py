from __future__ import annotations

from datetime import datetime, timedelta
import json

import pytest

from src.business.agents.tools.assistant_tools import (
    create_meeting_send_message_handler,
    create_open_meeting_channel_handler,
)
from src.business.task_collaboration.meetings import TaskMeetingService
from src.data.repos import AssistantMeetingRepository, AssistantTaskAdjudicationRepository
from src.data.repos import AssistantTaskRepository


class _Config:
    def get_assistant_tasks_meeting_turn_budget(self) -> int:
        return 10

    def get_assistant_tasks_meeting_time_budget_seconds(self) -> int:
        return 60

    def get_assistant_tasks_meeting_mutual_wait_window(self) -> int:
        return 4

    def get_assistant_tasks_api_default_limit(self) -> int:
        return 50


def _task():
    return AssistantTaskRepository().create_task(
        graph_id="tg_meeting",
        session_id="ast_meeting",
        task_id="tsk_parent",
        title="parent",
        description="parent",
        owner_session_id="ast_meeting",
        status="running",
    )


def test_supervised_meeting_records_messages_and_conclusion(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _Config(),
    )
    task = _task()
    service = TaskMeetingService()
    channel = service.open_channel(
        parent_task_id=task.task_id,
        participant_a={"type": "specialist", "id": "sp_a"},
        participant_b={"type": "specialist", "id": "sp_b"},
    )

    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_a",
        content="Use date order.",
    )
    concluded = service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_b",
        content="Agreed.",
        conclusion="Sort by date.",
    )

    transcript = service.get_transcript(channel.channel_id)
    assert concluded.status == "concluded"
    assert transcript["messages"][0]["sequence"] == 1
    assert transcript["conclusion"] == "Sort by date."


def test_meeting_is_message_only_and_sender_must_be_participant(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _Config(),
    )
    task = _task()
    service = TaskMeetingService()
    channel = service.open_channel(
        parent_task_id=task.task_id,
        participant_a={"type": "specialist", "id": "sp_a", "toolIds": ["tool.secret"]},
        participant_b={"type": "specialist", "id": "sp_b"},
    )

    with pytest.raises(PermissionError):
        service.send_message(
            channel_id=channel.channel_id,
            sender_type="specialist",
            sender_id="sp_c",
            content="Can I join?",
        )
    assert not hasattr(channel, "tool_ids")


def test_open_meeting_channel_records_message_only_task_edges(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _Config(),
    )
    task_repo = AssistantTaskRepository()
    parent = _task()
    child_a = task_repo.create_task(
        graph_id=parent.graph_id,
        session_id=parent.session_id,
        task_id="tsk_meeting_a",
        root_task_id=parent.task_id,
        parent_task_id=parent.task_id,
        title="A",
        description="A",
        owner_session_id=parent.session_id,
        assignee_type="specialist",
        assignee_id="sp_a",
        status="running",
    )
    child_b = task_repo.create_task(
        graph_id=parent.graph_id,
        session_id=parent.session_id,
        task_id="tsk_meeting_b",
        root_task_id=parent.task_id,
        parent_task_id=parent.task_id,
        title="B",
        description="B",
        owner_session_id=parent.session_id,
        assignee_type="specialist",
        assignee_id="sp_b",
        status="running",
    )

    TaskMeetingService().open_channel(
        parent_task_id=parent.task_id,
        participant_a={"type": "specialist", "id": "sp_a"},
        participant_b={"type": "specialist", "id": "sp_b"},
    )

    meeting_edges = [
        edge
        for edge in AssistantTaskRepository().list_graph_edges(parent.graph_id)
        if edge.edge_type == "meeting_channel"
    ]
    assert {
        (edge.source_task_id, edge.target_task_id, edge.propagation) for edge in meeting_edges
    } == {
        (parent.task_id, child_a.task_id, "message_only"),
        (parent.task_id, child_b.task_id, "message_only"),
    }


def test_meeting_budget_timeout_closes_channel_and_creates_parent_adjudication(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _Config(),
    )
    task = _task()
    service = TaskMeetingService()
    channel = service.open_channel(
        parent_task_id=task.task_id,
        participant_a={"type": "specialist", "id": "sp_a"},
        participant_b={"type": "specialist", "id": "sp_b"},
    )

    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_a",
        content="First.",
    )
    closed = service.close_expired_channels(datetime.now() + timedelta(seconds=90))

    refreshed = AssistantMeetingRepository().get_channel(channel.channel_id)
    adjudication = AssistantTaskAdjudicationRepository().get_pending_for_task(task.task_id)
    assert closed == 1
    assert refreshed.status == "closed_timeout"
    assert adjudication is not None
    assert adjudication.delivered_status == "stuck"


def test_meeting_turn_budget_exhaustion_closes_and_adjudicates(monkeypatch) -> None:
    # FR-016/FR-023：轮次预算耗尽必须触发 _close_timeout → 通道转 closed_timeout +
    # 生成父侧 stuck 裁定，防止会议无限等待环。用独立小 turn_budget=2 的 Config 隔离。
    class _SmallBudgetConfig(_Config):
        def get_assistant_tasks_meeting_turn_budget(self) -> int:
            return 2

    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _SmallBudgetConfig(),
    )
    task = _task()
    service = TaskMeetingService()
    channel = service.open_channel(
        parent_task_id=task.task_id,
        participant_a={"type": "specialist", "id": "sp_a"},
        participant_b={"type": "specialist", "id": "sp_b"},
    )

    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_a",
        content="第 1 轮，还没结论。",
    )
    # 第 2 条把 turns_used 顶到 turn_budget=2 且仍无 conclusion → 触发超时关闭
    closed = service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_b",
        content="第 2 轮，仍然没结论。",
    )

    refreshed = AssistantMeetingRepository().get_channel(channel.channel_id)
    adjudication = AssistantTaskAdjudicationRepository().get_pending_for_task(task.task_id)
    assert closed.status == "closed_timeout"
    assert refreshed.status == "closed_timeout"
    assert adjudication is not None
    assert adjudication.delivered_status == "stuck"


def test_meeting_message_with_secret_is_redacted_in_transcript(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _Config(),
    )
    task = _task()
    service = TaskMeetingService()
    channel = service.open_channel(
        parent_task_id=task.task_id,
        participant_a={"type": "specialist", "id": "sp_a"},
        participant_b={"type": "specialist", "id": "sp_b"},
    )

    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_a",
        content="连接串是 password=hunter2 千万别外泄",
    )

    transcript = service.get_transcript(channel.channel_id)

    # 会议消息含密钥模式时 transcript 只暴露占位符，不泄漏原文
    assert "hunter2" not in transcript["messages"][0]["content"]
    assert transcript["messages"][0]["content"] == "[内容已隐藏]"


def test_meeting_tool_handlers_return_message_only_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _Config(),
    )
    task = _task()
    open_result = json.loads(
        create_open_meeting_channel_handler()(
            taskId=task.task_id,
            participantA={"type": "specialist", "id": "sp_a", "toolIds": ["tool.secret"]},
            participantB={"type": "specialist", "id": "sp_b"},
        )
    )
    send_result = json.loads(
        create_meeting_send_message_handler(
            executor_type="specialist",
            executor_id="sp_a",
        )(
            channelId=open_result["channelId"],
            content="Use date order.",
        )
    )

    assert open_result["success"] is True
    assert send_result["success"] is True
    assert "tool" not in json.dumps(open_result)
    assert "tool" not in json.dumps(send_result)


def test_meeting_mutual_wait_detection_closes_channel(monkeypatch) -> None:
    # FR-016 / Edge "会议死锁"：双方连续发送等待/反问语义消息（window=4）时，
    # _detect_mutual_wait 返回 True → _close_timeout → closed_timeout + 父侧裁定。
    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _Config(),
    )
    task = _task()
    service = TaskMeetingService()
    channel = service.open_channel(
        parent_task_id=task.task_id,
        participant_a={"type": "specialist", "id": "sp_a"},
        participant_b={"type": "specialist", "id": "sp_b"},
    )

    # 双方交替发送等待语义消息，共 4 条（window=4）
    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_a",
        content="等待你的回复，请告诉我怎么处理。",
    )
    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_b",
        content="你先说说你的意见？",
    )
    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_a",
        content="我在等你的决定，你怎么看？",
    )
    # 第 4 条触发互等检测
    _ = service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_b",
        content="please answer me first, waiting for your response.",
    )

    refreshed = AssistantMeetingRepository().get_channel(channel.channel_id)
    adjudication = AssistantTaskAdjudicationRepository().get_pending_for_task(task.task_id)
    assert refreshed.status == "closed_timeout"
    assert adjudication is not None
    assert adjudication.delivered_status == "stuck"


def test_meeting_mutual_wait_not_triggered_by_substantive_messages(monkeypatch) -> None:
    # 正常实质交流不应触发互等检测
    monkeypatch.setattr(
        "src.business.task_collaboration.meetings.get_unified_config",
        lambda: _Config(),
    )
    task = _task()
    service = TaskMeetingService()
    channel = service.open_channel(
        parent_task_id=task.task_id,
        participant_a={"type": "specialist", "id": "sp_a"},
        participant_b={"type": "specialist", "id": "sp_b"},
    )

    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_a",
        content="我建议按日期排序。",
    )
    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_b",
        content="好的，按名称排序更合适。",
    )
    service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_a",
        content="日期排序更直观。",
    )
    _ = service.send_message(
        channel_id=channel.channel_id,
        sender_type="specialist",
        sender_id="sp_b",
        content="同意日期排序。",
    )

    refreshed = AssistantMeetingRepository().get_channel(channel.channel_id)
    assert refreshed.status == "open"

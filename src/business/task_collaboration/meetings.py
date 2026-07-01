"""Business service for supervised message-only meeting channels."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from src.business.task_collaboration.models import MeetingChannelStatus, safe_public_preview
from src.business.task_collaboration.service import (
    TaskCollaborationService,
    emit_meeting_changed,
)
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import (
    AssistantMeetingRepository,
    AssistantTaskAdjudicationRepository,
    AssistantTaskRepository,
)
from src.data.unified_config import get_unified_config

# 等待/反问语义关键词（中英文），用于互等检测。
_MUTUAL_WAIT_PATTERNS = re.compile(
    r"(?:等待|等.*回|请.*回复|please.*answer|waiting|what about you|"
    r"你的意见|你怎么看|你先说|你那边|any update|status\?)",
    re.IGNORECASE,
)


class TaskMeetingService(AtomicTaskService):
    def __init__(
        self,
        meeting_repo: AssistantMeetingRepository | None = None,
        task_repo: AssistantTaskRepository | None = None,
        adjudication_repo: AssistantTaskAdjudicationRepository | None = None,
    ) -> None:
        self._init_repos(
            tasks=(AssistantTaskRepository, task_repo),
            meetings=(AssistantMeetingRepository, meeting_repo),
            adjudications=(AssistantTaskAdjudicationRepository, adjudication_repo),
        )
        self._graph_service = TaskCollaborationService(
            task_repo=self._tasks,
            adjudication_repo=self._adjudications,
        )
        self._config = get_unified_config()

    def open_channel(
        self,
        *,
        parent_task_id: str,
        participant_a: dict[str, Any],
        participant_b: dict[str, Any],
    ):
        task = self._tasks.get_task(parent_task_id)
        if task is None:
            raise LookupError("parent task not found")
        a_type, a_id = _participant_identity(participant_a)
        b_type, b_id = _participant_identity(participant_b)
        if (a_type, a_id) == (b_type, b_id):
            raise ValueError("meeting requires two distinct participants")
        with self._atomic():
            channel = self._meetings.create_channel(
                graph_id=task.graph_id,
                parent_task_id=task.task_id,
                supervisor_session_id=task.owner_session_id or task.session_id,
                participant_a_type=a_type,
                participant_a_id=a_id,
                participant_b_type=b_type,
                participant_b_id=b_id,
                turn_budget=self._config.get_assistant_tasks_meeting_turn_budget(),
                time_budget_seconds=self._config.get_assistant_tasks_meeting_time_budget_seconds(),
            )
            self._add_meeting_edges(
                task,
                participants=((a_type, a_id), (b_type, b_id)),
            )
        emit_meeting_changed(self, task, channel, change_type="opened", status=channel.status)
        return channel

    def send_message(
        self,
        *,
        channel_id: str,
        sender_type: str,
        sender_id: str,
        content: str,
        conclusion: str | None = None,
    ):
        channel = self._meetings.get_channel(channel_id)
        if channel is None:
            raise LookupError("meeting channel not found")
        if channel.status != MeetingChannelStatus.OPEN:
            raise ValueError("meeting channel is closed")
        if not _is_participant(channel, sender_type, sender_id):
            raise PermissionError("meeting messages are restricted to channel participants")
        with self._atomic():
            message = self._meetings.add_message(
                channel_id=channel_id,
                sender_type=sender_type,
                sender_id=sender_id,
                content=safe_public_preview(content, key="content", max_chars=1000),
            )
        task = self._tasks.get_task(channel.parent_task_id)
        emit_meeting_changed(
            self,
            task,
            channel,
            change_type="message_added",
            status=MeetingChannelStatus.OPEN,
            sequence=message.sequence,
        )
        if conclusion:
            with self._atomic():
                closed = self._meetings.close_channel(
                    channel_id,
                    status=MeetingChannelStatus.CONCLUDED,
                    conclusion=safe_public_preview(conclusion, key="conclusion", max_chars=1000),
                )
                if closed is not None and task is not None:
                    self._graph_service.create_parent_adjudication(
                        task_id=task.task_id,
                        delivered_status="done",
                        safe_summary=safe_public_preview(conclusion, key="conclusion"),
                    )
            emit_meeting_changed(
                self, task, channel, change_type="concluded", status=MeetingChannelStatus.CONCLUDED
            )
            return closed
        refreshed = self._meetings.get_channel(channel_id)
        if refreshed is None:
            # 通道在本条消息提交后消失（防御性，正常不会发生）：不在 None 上解引用
            # turns_used（否则 AttributeError → 不透明 500），按通道不存在处理，
            # 与本文件其它 get_channel None 守卫一致。
            raise LookupError("meeting channel not found")
        if refreshed.turns_used >= refreshed.turn_budget:
            return self._close_timeout(refreshed)
        if self._detect_mutual_wait(refreshed):
            return self._close_timeout(refreshed)
        return refreshed

    def get_transcript(
        self,
        channel_id: str,
        *,
        session_id: str | None = None,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> dict:
        channel = self._meetings.get_channel(channel_id)
        if channel is None:
            raise LookupError("meeting channel not found")
        if session_id is not None:
            task = self._tasks.get_task(channel.parent_task_id)
            if task is None or task.session_id != session_id:
                raise LookupError("meeting channel not found")
        effective_limit = limit or self._config.get_assistant_tasks_api_default_limit()
        messages = self._meetings.list_messages(
            channel_id,
            after_sequence=after_sequence,
            limit=effective_limit,
        )
        return {
            "channelId": channel.channel_id,
            "status": channel.status,
            "participants": [
                {"type": channel.participant_a_type, "id": channel.participant_a_id},
                {"type": channel.participant_b_type, "id": channel.participant_b_id},
            ],
            "turnsUsed": channel.turns_used,
            "turnBudget": channel.turn_budget,
            "messages": [
                {
                    "sequence": message.sequence,
                    "senderId": message.sender_id,
                    "content": safe_public_preview(message.content, key="content", max_chars=1000),
                    "createdAt": message.created_at.isoformat() if message.created_at else None,
                }
                for message in messages
            ],
            "nextAfterSequence": (
                messages[-1].sequence if messages and len(messages) == effective_limit else None
            ),
            "conclusion": channel.conclusion,
        }

    def close_expired_channels(self, now: datetime) -> int:
        closed = 0
        for channel in self._meetings.scan_expired_open_channels(now):
            if self._close_timeout(channel) is not None:
                closed += 1
        return closed

    def _close_timeout(self, channel):
        # close + adjudication 必须同一事务：否则 close 成功但 adjudication 失败时，
        # 会议停在 closed_timeout 却无裁定，任务不会进入 reviewing 状态。
        with self._atomic():
            closed = self._meetings.close_channel(
                channel.channel_id, status=MeetingChannelStatus.CLOSED_TIMEOUT
            )
            if closed is None:
                return None
            task = self._tasks.get_task(channel.parent_task_id)
            if task is not None:
                self._graph_service.create_parent_adjudication(
                    task_id=task.task_id,
                    delivered_status="stuck",
                    safe_summary="会议未在预算内产出结论，等待上级裁定。",
                )
        # emit 在事务外：DB 已提交但通知失败只影响 UI 时效性，不影响一致性。
        # task 复用事务内已读取的行（commit 后属性访问会 reload，但省一次独立 get_task）。
        if task is not None:
            emit_meeting_changed(
                self,
                task,
                channel,
                change_type="closed_timeout",
                status=MeetingChannelStatus.CLOSED_TIMEOUT,
            )
        return closed

    def _detect_mutual_wait(self, channel) -> bool:
        """检测双方是否陷入互等：最近 N 条消息（默认 4 条）均来自不同发送者且
        每条都包含等待/反问语义。满足条件时视为死锁，应关闭通道并交父侧裁定。

        N 由配置 ``assistant_tasks.meeting.mutual_wait_window`` 控制，默认 4。
        """
        window = self._config.get_assistant_tasks_meeting_mutual_wait_window()
        recent = self._meetings.list_messages(channel.channel_id, limit=window)
        if len(recent) < window:
            return False
        # 每条消息必须来自不同发送者（交替发言）且包含等待语义
        for msg in recent:
            if not _MUTUAL_WAIT_PATTERNS.search(msg.content or ""):
                return False
        # 确认双方都参与了最近 window 条消息（不是单方连续自言自语）
        senders = {(msg.sender_type, msg.sender_id) for msg in recent}
        return len(senders) >= 2

    def _add_meeting_edges(self, parent_task, *, participants: tuple[tuple[str, str], ...]) -> None:
        participant_tasks = {
            task.task_id
            for task in self._tasks.list_graph_tasks(parent_task.graph_id)
            for participant_type, participant_id in participants
            if task.task_id != parent_task.task_id
            and task.assignee_type == participant_type
            and task.assignee_id == participant_id
        }
        for participant_task_id in sorted(participant_tasks):
            self._tasks.add_edge(
                graph_id=parent_task.graph_id,
                source_task_id=parent_task.task_id,
                target_task_id=participant_task_id,
                edge_type="meeting_channel",
                propagation="message_only",
            )


def _participant_identity(payload: dict[str, Any]) -> tuple[str, str]:
    participant_type = str(payload.get("type") or "").strip()
    participant_id = str(payload.get("id") or "").strip()
    if participant_type not in {"ephemeral_subagent", "specialist"} or not participant_id:
        raise ValueError("meeting participant must be an assistant executor")
    return participant_type, participant_id


def _is_participant(channel, sender_type: str, sender_id: str) -> bool:
    identity = (sender_type, sender_id)
    return identity in {
        (channel.participant_a_type, channel.participant_a_id),
        (channel.participant_b_type, channel.participant_b_id),
    }

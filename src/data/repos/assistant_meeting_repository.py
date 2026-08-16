"""Repository for supervised Assistant meeting channels."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.data.models_sqlite import AssistantMeetingChannel, AssistantMeetingMessage
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class AssistantMeetingRepository(BaseRepository):
    def create_channel(
        self,
        *,
        graph_id: str,
        parent_task_id: str,
        supervisor_session_id: str,
        participant_a_type: str,
        participant_a_id: str,
        participant_b_type: str,
        participant_b_id: str,
        turn_budget: int,
        time_budget_seconds: int,
        channel_id: str | None = None,
    ) -> AssistantMeetingChannel:
        self.ensure_immediate_transaction()
        row = AssistantMeetingChannel(
            channel_id=channel_id or generate_id("mtg"),
            graph_id=graph_id,
            parent_task_id=parent_task_id,
            supervisor_session_id=supervisor_session_id,
            participant_a_type=participant_a_type,
            participant_a_id=participant_a_id,
            participant_b_type=participant_b_type,
            participant_b_id=participant_b_id,
            turn_budget=turn_budget,
            time_budget_seconds=time_budget_seconds,
        )
        return self._add_and_flush(row)

    def get_channel(self, channel_id: str) -> AssistantMeetingChannel | None:
        return self.session.get(AssistantMeetingChannel, channel_id)

    def list_open_channels(self) -> list[AssistantMeetingChannel]:
        return (
            self.session.query(AssistantMeetingChannel)
            .filter(AssistantMeetingChannel.status == "open")
            .order_by(AssistantMeetingChannel.created_at, AssistantMeetingChannel.channel_id)
            .all()
        )

    def scan_expired_open_channels(self, now: datetime) -> list[AssistantMeetingChannel]:
        """open 且已过期的频道（created_at + time_budget_seconds <= now）。

        与 scan_expired_claims / scan_expired 对齐：过期判定集中在 repository，
        service 只迭代结果，让各种过期扫描形态一致、便于发现。
        """
        return [
            channel
            for channel in self.list_open_channels()
            if (channel.created_at or now) + timedelta(seconds=channel.time_budget_seconds) <= now
        ]

    def add_message(
        self,
        *,
        channel_id: str,
        sender_type: str,
        sender_id: str,
        content: str,
        message_id: str | None = None,
    ) -> AssistantMeetingMessage:
        self.ensure_immediate_transaction()
        # 校验频道存在且处于 open 状态，防止向不存在/已关闭频道插入孤立消息
        channel = self.session.get(AssistantMeetingChannel, channel_id)
        if channel is None:
            raise ValueError(f"Meeting channel {channel_id} does not exist")
        if channel.status != "open":
            raise ValueError(f"Meeting channel {channel_id} is not open (status={channel.status})")
        last_sequence = (
            self.session.query(AssistantMeetingMessage.sequence)
            .filter(AssistantMeetingMessage.channel_id == channel_id)
            .order_by(AssistantMeetingMessage.sequence.desc())
            .first()
        )
        sequence = int(last_sequence[0]) + 1 if last_sequence else 1
        row = AssistantMeetingMessage(
            message_id=message_id or generate_id("msg"),
            channel_id=channel_id,
            sender_type=sender_type,
            sender_id=sender_id,
            content=content,
            sequence=sequence,
        )
        self.session.add(row)
        channel.turns_used += 1
        return self._update_and_flush(row)

    def list_messages(
        self,
        channel_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 50,
    ) -> list[AssistantMeetingMessage]:
        query = self.session.query(AssistantMeetingMessage).filter(
            AssistantMeetingMessage.channel_id == channel_id
        )
        if after_sequence is not None:
            query = query.filter(AssistantMeetingMessage.sequence > after_sequence)
        return query.order_by(AssistantMeetingMessage.sequence).limit(max(1, min(limit, 200))).all()

    def close_channel(
        self,
        channel_id: str,
        *,
        status: str,
        conclusion: str | None = None,
    ) -> AssistantMeetingChannel | None:
        self.ensure_immediate_transaction()
        row = self.session.get(AssistantMeetingChannel, channel_id)
        if row is None:
            return None
        # 已关闭的频道不可再次关闭（closed 即终态）
        if row.status != "open":
            return None
        row.status = status
        row.conclusion = conclusion
        row.closed_at = utc_now_naive()
        return self._update_and_flush(row)

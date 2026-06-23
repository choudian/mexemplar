"""Repository for persistent Assistant terminal-failure recovery state."""

from __future__ import annotations

import uuid
from datetime import datetime

from src.data.models_sqlite import AssistantRunFailure

from .base_repository import BaseRepository

_CURRENT_STATUSES = ("failed", "retrying")


class AssistantRunFailureRepository(BaseRepository):
    def get_by_id(self, failure_id: str) -> AssistantRunFailure | None:
        return (
            self.session.query(AssistantRunFailure)
            .filter(AssistantRunFailure.failure_id == failure_id)
            .first()
        )

    def get_current(self, session_id: str) -> AssistantRunFailure | None:
        return (
            self.session.query(AssistantRunFailure)
            .filter(
                AssistantRunFailure.session_id == session_id,
                AssistantRunFailure.status.in_(_CURRENT_STATUSES),
            )
            .order_by(AssistantRunFailure.updated_at.desc())
            .first()
        )

    def get_current_for_sequences(
        self,
        session_id: str,
        message_sequences: list[int],
    ) -> dict[int, AssistantRunFailure]:
        if not message_sequences:
            return {}
        rows = (
            self.session.query(AssistantRunFailure)
            .filter(
                AssistantRunFailure.session_id == session_id,
                AssistantRunFailure.message_sequence.in_(message_sequences),
                AssistantRunFailure.status.in_(_CURRENT_STATUSES),
            )
            .all()
        )
        return {row.message_sequence: row for row in rows}

    def record_failure(
        self,
        *,
        session_id: str,
        message_sequence: int,
        category: str,
        safe_message: str,
        safe_suggestion: str,
        internal_code: str | None,
        exception_type: str | None,
        source_failure_id: str | None = None,
    ) -> AssistantRunFailure:
        now = datetime.now()
        # 同一会话的 agent run 串行执行，不会并发 record_failure；即便极端情况下重复插入，
        # get_current 也按最新行兜底，无有害后果，因此不加并发守卫。
        row = (
            self.get_by_id(source_failure_id) if source_failure_id else self.get_current(session_id)
        )
        if row is not None and row.session_id == session_id:
            row.message_sequence = message_sequence
            row.category = category
            row.safe_message = safe_message
            row.safe_suggestion = safe_suggestion
            row.internal_code = internal_code
            row.exception_type = exception_type
            row.status = "failed"
            row.failed_at = now
            row.updated_at = now
            row.resolved_at = None
        else:
            row = AssistantRunFailure(
                failure_id=f"asf_{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                message_sequence=message_sequence,
                category=category,
                safe_message=safe_message,
                safe_suggestion=safe_suggestion,
                internal_code=internal_code,
                exception_type=exception_type,
                attempt_count=1,
                status="failed",
                created_at=now,
                updated_at=now,
                failed_at=now,
            )
            self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def claim_retry(self, session_id: str, message_sequence: int) -> AssistantRunFailure | None:
        # 原子条件 UPDATE：把“status 必须是 failed 且序列号匹配”写进 WHERE，由数据库
        # 保证并发重试只有一个成功（SQL 标准 CAS，不依赖 BEGIN IMMEDIATE 的手动时序）。
        # 两个并发请求在 SQLite 单写者下排队：第一个把 status 改成 retrying 后，第二个的
        # WHERE 已匹配不到，update 返回 0 行 → 返回 None，拒绝重复认领。
        now = datetime.now()
        claimed = (
            self.session.query(AssistantRunFailure)
            .filter(
                AssistantRunFailure.session_id == session_id,
                AssistantRunFailure.status == "failed",
                AssistantRunFailure.message_sequence == message_sequence,
            )
            .update(
                {
                    AssistantRunFailure.status: "retrying",
                    AssistantRunFailure.attempt_count: AssistantRunFailure.attempt_count + 1,
                    AssistantRunFailure.updated_at: now,
                    AssistantRunFailure.resolved_at: None,
                },
                synchronize_session=False,
            )
        )
        self.session.commit()
        if not claimed:
            return None
        return self.get_current(session_id)

    def restore_failed(self, failure_id: str) -> bool:
        row = self.get_by_id(failure_id)
        if row is None or row.status != "retrying":
            return False
        row.status = "failed"
        row.updated_at = datetime.now()
        self.session.commit()
        return True

    def resolve(self, failure_id: str) -> AssistantRunFailure | None:
        row = self.get_by_id(failure_id)
        if row is None or row.status == "resolved":
            return row
        now = datetime.now()
        row.status = "resolved"
        row.resolved_at = now
        row.updated_at = now
        self.session.commit()
        self.session.refresh(row)
        return row

    def resolve_current(self, session_id: str) -> AssistantRunFailure | None:
        row = self.get_current(session_id)
        if row is None:
            return None
        return self.resolve(row.failure_id)

    def recover_interrupted_retries(self) -> int:
        now = datetime.now()
        count = (
            self.session.query(AssistantRunFailure)
            .filter(AssistantRunFailure.status == "retrying")
            .update(
                {
                    AssistantRunFailure.status: "failed",
                    AssistantRunFailure.updated_at: now,
                    AssistantRunFailure.failed_at: now,
                },
                synchronize_session=False,
            )
        )
        self.session.commit()
        return int(count or 0)

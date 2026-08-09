"""助理过程可观测只读读模型（014-assistant-chat-transparency）。

由既有 Repository **只读**重建历史过程时间线与子任务权威列表——**无新表、无迁移、无物理删除**。
activity step 文本保留原文（仅截断）+ `redacted` 标记（UI 默认隐藏、双击查看，原文本就明文存于 messages 表）；
subagent task/lastOutput 仍走 009 脱敏。与实时事件口径一致。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from src.business.services.ui_event_safety_service import (
    DEFAULT_PUBLIC_TEXT_MAX_CHARS,
    DEFAULT_PUBLIC_TEXT_MAX_LEN,
    public_ui_event_text_with_flag,
    redact_public_ui_event_text,
)
from src.business.agents.config import subagent_label
from src.data.repositories import (
    MessageRepository,
    SessionRepository,
    WorkflowTransitionRepository,
)
from src.utils.helpers import walk_exception_chain

logger = logging.getLogger(__name__)

_TRANSIENT_TRANSCRIPT_LOOKUP_MARKERS = (
    "concurrent operations are not permitted",
    "provisioning a new connection",
)


@dataclass
class ActivityStep:
    kind: str  # reasoning | tool_call | tool_result
    seq: int
    text: str
    tool_name: Optional[str] = None
    # 命中敏感规则（命令/代码/密钥等）→ UI 默认隐藏、双击查看原文（方案 B）。
    redacted: bool = False


@dataclass
class TranscriptResult:
    steps: list[ActivityStep] = field(default_factory=list)
    # 该会话过程是否已被压缩/概要化（中间步骤可能不全）——供前端按规整概要渲染（FR-020/C2-E1）。
    compressed: bool = False


@dataclass
class SubagentSummary:
    subagent_id: str
    label: str
    task: str
    status: str  # running | done | suspended | failed
    last_output: Optional[str] = None
    turn_start_sequence: Optional[int] = None


def _redact(value: object) -> str:
    """脱敏文本/结构化字段：直接交给 009 脱敏服务——dict/list 递归按键名检测、字符串走 forbidden
    规则 + JSON 容器解析；命中敏感键/规则整体替换占位符，否则截断。

    注意：**不可在此处先 `str(value)`**——dict 的 Python repr 用单引号（`{'api_key': ...}`），既不
    匹配 `api_key=` 正则、也无法被 `json.loads` 解析，会绕过脱敏使密钥明文外泄进 transcript（C2-E2/E5）。
    """
    return redact_public_ui_event_text(
        "text",
        "" if value is None else value,
        max_preview_chars=DEFAULT_PUBLIC_TEXT_MAX_CHARS,
        max_len=DEFAULT_PUBLIC_TEXT_MAX_LEN,
    )


def _redact_with_flag(value: object) -> tuple[str, bool]:
    """activity 过程时间线专用：保留原文（仅截断）+ 返回敏感标记，供 UI 默认隐藏 + 双击查看。"""
    return public_ui_event_text_with_flag(
        "text",
        "" if value is None else value,
        max_preview_chars=DEFAULT_PUBLIC_TEXT_MAX_CHARS,
        max_len=DEFAULT_PUBLIC_TEXT_MAX_LEN,
    )


def _is_compression_marker(msg) -> bool:
    role = getattr(msg, "role", None)
    return (
        role == "summary"
        or getattr(msg, "message_type", "") == "summary"
        or bool(getattr(msg, "compressed_range", None))
    )


def _is_transient_transcript_lookup_error(exc: BaseException) -> bool:
    for node in walk_exception_chain(exc):
        text = str(node).lower()
        if any(marker in text for marker in _TRANSIENT_TRANSCRIPT_LOOKUP_MARKERS):
            return True
    return False


class AssistantObservability:
    """只读读模型：transcript 与子任务权威列表。"""

    def __init__(
        self,
        message_repo: MessageRepository | None = None,
        session_repo: SessionRepository | None = None,
        transition_repo: WorkflowTransitionRepository | None = None,
    ) -> None:
        self._message_repo = message_repo or MessageRepository()
        self._session_repo = session_repo or SessionRepository()
        self._transition_repo = transition_repo or WorkflowTransitionRepository()

    def build_transcript(
        self,
        session_id: str,
        *,
        after_sequence: int | None = None,
        before_sequence: int | None = None,
    ) -> TranscriptResult:
        """由 MessageRepository 的中间 assistant（含 tool_calls）与 tool 结果消息重建过程时间线。

        kind=reasoning 仅从【带 tool_calls 的中间消息】重建（与实时口径一致，C2-E4）；
        最终无工具调用的回复不进时间线；命中既有压缩痕迹（006「之前的对话内容」summary）即标记 compressed。
        """
        sid = (session_id or "").strip()
        if not sid:
            return TranscriptResult()
        try:
            messages = self._message_repo.get_all(sid)
        except Exception as exc:
            if not _is_transient_transcript_lookup_error(exc):
                logger.error("assistant transcript lookup failed: session=%s error=%s", sid, exc)
                raise
            logger.warning(
                "assistant transcript lookup transient failure; retrying once: session=%s "
                "error_type=%s",
                sid,
                type(exc).__name__,
            )
            # SQLite WAL 锁释放通常 <10ms；10ms 睡眠足够且减少调用方阻塞。
            time.sleep(0.01)
            try:
                messages = self._message_repo.get_all(sid)
            except Exception as retry_exc:
                if _is_transient_transcript_lookup_error(retry_exc):
                    logger.warning(
                        "assistant transcript lookup transient failure after retry; "
                        "returning empty transcript: session=%s error_type=%s",
                        sid,
                        type(retry_exc).__name__,
                    )
                    return TranscriptResult()
                logger.error(
                    "assistant transcript lookup failed after transient retry: "
                    "session=%s error=%s",
                    sid,
                    retry_exc,
                )
                raise
        steps: list[ActivityStep] = []
        seq = 0
        compressed = False
        for msg in messages:
            msg_seq = int(getattr(msg, "sequence", 0) or 0)
            if after_sequence is not None and msg_seq <= after_sequence:
                continue
            if before_sequence is not None and msg_seq >= before_sequence:
                continue
            if _is_compression_marker(msg):
                compressed = True
                continue
            if getattr(msg, "is_archived", False):
                # 物理保留但已沉淀/归档：步骤可能不全，标记 compressed（仍尽量重建已存明细）
                compressed = True
            role = getattr(msg, "role", None)
            if role == "assistant":
                raw_tc = getattr(msg, "tool_calls", None)
                if not raw_tc:
                    continue  # 最终回复，不进时间线
                content = getattr(msg, "content", None)
                if content:
                    seq += 1
                    reason_text, reason_redacted = _redact_with_flag(content)
                    steps.append(
                        ActivityStep(
                            kind="reasoning", seq=seq, text=reason_text, redacted=reason_redacted
                        )
                    )
                try:
                    parsed = json.loads(raw_tc)
                except (ValueError, TypeError):
                    continue
                for tc in parsed if isinstance(parsed, list) else []:
                    if not isinstance(tc, dict):
                        continue
                    seq += 1
                    call_text, call_redacted = _redact_with_flag(tc.get("args", {}))
                    steps.append(
                        ActivityStep(
                            kind="tool_call",
                            seq=seq,
                            tool_name=tc.get("name"),
                            text=call_text,
                            redacted=call_redacted,
                        )
                    )
            elif role == "tool":
                seq += 1
                result_text, result_redacted = _redact_with_flag(getattr(msg, "content", ""))
                steps.append(
                    ActivityStep(
                        kind="tool_result",
                        seq=seq,
                        tool_name=getattr(msg, "tool_name", None),
                        text=result_text,
                        redacted=result_redacted,
                    )
                )
        return TranscriptResult(steps=steps, compressed=compressed)

    def build_subagent_list(self, parent_session_id: str) -> list[SubagentSummary]:
        """由委派流转（WorkflowTransitionRepository）+ 子会话状态（SessionRepository）重建权威子任务列表。

        list 来自 assistant_delegation_started（from=父）→ to_session_id 即子任务会话；
        status 取子会话权威状态（active→running / suspended→suspended / completed→done / failed→failed）；
        task/lastOutput 文本走 009 脱敏。
        """
        pid = (parent_session_id or "").strip()
        if not pid:
            return []
        try:
            transitions = self._transition_repo.list_by_session(pid)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "subagent list transition lookup failed: parent_session=%s error=%s", pid, exc
            )
            raise

        # 保留首次委派顺序
        child_ids: list[str] = []
        agent_types: dict[str, str] = {}
        turn_start_sequences: dict[str, int | None] = {}
        try:
            parent_messages = self._message_repo.get_all(pid)
        except Exception as exc:
            logger.error(
                "subagent list parent message lookup failed: parent_session=%s error=%s", pid, exc
            )
            raise
        for tr in transitions:
            if (
                getattr(tr, "event_type", "") == "assistant_delegation_started"
                and getattr(tr, "from_session_id", None) == pid
            ):
                child = getattr(tr, "to_session_id", None)
                if not child or child in agent_types:
                    continue
                child_ids.append(child)
                agent_types[child] = _delegation_agent_type(getattr(tr, "payload", None))
                turn_start_sequences[child] = _find_turn_start_sequence(
                    parent_messages,
                    getattr(tr, "created_at", None),
                )

        # 批量重建子任务明细（状态/任务/最后产出），把逐子任务查询收敛为固定批量查询
        try:
            sessions_by_id = {
                getattr(s, "session_id", None): s for s in self._session_repo.get_by_ids(child_ids)
            }
            tasks_by_id = self._message_repo.get_first_user_messages(child_ids)
            last_outputs_by_id = self._message_repo.get_latest_assistant_texts(child_ids)
        except Exception as exc:
            logger.error("subagent list detail lookup failed: parent_session=%s error=%s", pid, exc)
            raise

        # "在不在跑"查 attempt 表（有租约/唯一索引保证），session.status 作 fallback
        # （同步委派建 attempt 前，或极少数无 attempt 的场景）。
        attempt_statuses = _batch_attempt_statuses(child_ids)

        items: list[SubagentSummary] = []
        for child in child_ids:
            session = sessions_by_id.get(child)
            attempt_status = attempt_statuses.get(child)
            status = _map_subagent_status(
                getattr(session, "status", None) if session else None,
                attempt_status=attempt_status,
            )
            items.append(
                SubagentSummary(
                    subagent_id=child,
                    label=subagent_label(agent_types.get(child)),
                    task=_redact(tasks_by_id.get(child) or ""),
                    status=status,
                    last_output=_redact(last_outputs_by_id.get(child)) or None,
                    turn_start_sequence=turn_start_sequences.get(child),
                )
            )
        return items

    def find_subagent_summary(
        self,
        parent_session_id: str,
        subagent_id: str,
    ) -> SubagentSummary | None:
        """按父会话与子任务 ID 返回权威卡片摘要。"""
        sid = (subagent_id or "").strip()
        if not sid:
            return None
        return next(
            (
                item
                for item in self.build_subagent_list(parent_session_id)
                if item.subagent_id == sid
            ),
            None,
        )

    def count_subagent_return_transitions(self, parent_session_id: str, subagent_id: str) -> int:
        """统计子任务返回父会话的完成/失败/暂停/续跑标记，用于判断 continue_subagent 是否实际发生。"""
        pid = (parent_session_id or "").strip()
        sid = (subagent_id or "").strip()
        if not pid or not sid:
            return 0
        try:
            transitions = self._transition_repo.list_by_session(pid)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(
                "subagent transition count lookup failed: parent_session=%s subagent=%s error=%s",
                pid,
                sid,
                exc,
            )
            raise
        return sum(
            1
            for tr in transitions
            if getattr(tr, "from_session_id", None) == sid
            and getattr(tr, "to_session_id", None) == pid
            and getattr(tr, "event_type", "")
            in {
                "assistant_delegation_completed",
                "assistant_delegation_failed",
                "assistant_delegation_paused",
                "assistant_delegation_resumed",
            }
        )

    def continue_subagent_started(
        self,
        parent_session_id: str,
        subagent_id: str,
        baseline_return_transition_count: int,
    ) -> bool:
        """判断一次 continue_subagent 是否实际发生：返回标记增多或子任务已离开 suspended。

        与 count_subagent_return_transitions 的标记口径同处一层，避免适配层各自重派生该业务事实。
        """
        if (
            self.count_subagent_return_transitions(parent_session_id, subagent_id)
            > baseline_return_transition_count
        ):
            return True
        summary = self.find_subagent_summary(parent_session_id, subagent_id)
        return summary is not None and summary.status != "suspended"


def _delegation_agent_type(payload: object) -> str:
    if not payload:
        return ""
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
        return str(data.get("agent_type") or "") if isinstance(data, dict) else ""
    except (ValueError, TypeError):
        return ""


def _map_subagent_status(
    session_status: Optional[str],
    *,
    attempt_status: Optional[str] = None,
) -> str:
    """把执行体状态映射为 observability 公开状态串。

    优先用 attempt.status（可靠信息源）；无 attempt 时回退到 session.status
    （同步委派建 attempt 前的过渡期，或极少数无 attempt 场景）。
    """
    if attempt_status is not None:
        mapping = {
            "starting": "running",
            "running": "running",
            "paused": "suspended",
            "succeeded": "done",
            "failed": "failed",
            "cancelled": "failed",
            "fenced": "failed",
        }
        return mapping.get(attempt_status, "running")
    # fallback：无 attempt 时读 session.status
    mapping = {
        "active": "running",
        "suspended": "suspended",
        "completed": "done",
        "failed": "failed",
    }
    return mapping.get(session_status or "", "running")


def _batch_attempt_statuses(child_ids: list[str]) -> dict[str, str]:
    """批量查子会话最新 attempt status，返回 {session_id: status}。

    查询失败时返回空 dict（调用方回退到 session.status）。
    """
    if not child_ids:
        return {}
    try:
        from src.data.repos import AssistantTaskAttemptRepository

        with AssistantTaskAttemptRepository() as attempts:
            return attempts.latest_statuses_for_sessions(child_ids)
    except Exception:
        logger.debug("attempt status batch lookup failed", exc_info=True)
        return {}


def _find_turn_start_sequence(messages: list, transition_created_at) -> int | None:
    user_messages = [
        msg
        for msg in messages
        if getattr(msg, "role", None) == "user"
        and getattr(msg, "content", None)
        and getattr(msg, "sequence", None) is not None
    ]
    if not user_messages:
        return None
    if transition_created_at is None:
        return int(getattr(user_messages[-1], "sequence", 0) or 0) or None

    candidates = [
        msg
        for msg in user_messages
        if getattr(msg, "created_at", None) is None
        or getattr(msg, "created_at", None) <= transition_created_at
    ]
    chosen = candidates[-1] if candidates else user_messages[-1]
    return int(getattr(chosen, "sequence", 0) or 0) or None

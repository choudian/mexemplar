"""结构化多选澄清机制（主助理 ask_user_question 工具专用，线程安全）。

设计对标 builtin_general_tools 的高危确认机制（request_id + threading.Event + lock +
first-decision-wins），但**完全独立**：独立 pending 表、独立信号、独立终态集，绝不与高危
确认链路共用状态或审计日志（FR-020）。

全部内存态：进程内 dict + threading 原语，无任何 SQLite/DuckDB 持久化、无迁移、无配置项
（CC-001）。sidecar 重启后自然失效。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

# 默认 5 分钟超时（模块常量，非用户可调，符合"无新增配置项"）。
CLARIFICATION_TIMEOUT_S: float = 300.0
OTHER_TEXT_MAX_CHARS: int = 1000
_MIN_QUESTIONS = 1
_MAX_QUESTIONS = 4
_MIN_OPTIONS = 2
_MAX_OPTIONS = 4

# 终态集合（FR-005）。pending 为初始态；unavailable 不创建 pending，直接由 handler 返回。
ClarificationStatus = Literal[
    "pending", "answered", "cancelled", "timeout", "stopped", "shutdown", "unavailable"
]
ClarificationDecision = Literal["submit", "cancel"]


class ClarificationValidationError(ValueError):
    """工具入参或决策提交非法（前者返回 error_json，后者 API 返回 422，均不创建/不结算）。"""


# =============================================================================
# 数据模型（内存态）
# =============================================================================


@dataclass(frozen=True)
class NormalizedOption:
    option_id: str
    label: str
    description: Optional[str] = None
    preview: Optional[str] = None


@dataclass(frozen=True)
class NormalizedQuestion:
    question_id: str
    question: str
    header: str
    multi_select: bool
    options: list[NormalizedOption]


@dataclass(frozen=True)
class ResolvedAnswer:
    question: str
    selected_labels: list[str]
    other_text: Optional[str]


@dataclass
class PendingClarification:
    request_id: str
    session_id: str
    questions: list[NormalizedQuestion]
    created_at: float
    event: threading.Event
    status: ClarificationStatus = "pending"
    answers: list[ResolvedAnswer] = field(default_factory=list)


# =============================================================================
# 模块级状态
# =============================================================================

_clarification_signal: Any = None  # 需实现 emit_requested(request_id) / emit_resolved(request_id)
_pending_clarifications: dict[str, PendingClarification] = {}
_clarification_lock = threading.Lock()


def register_clarification_signal(signal: Any) -> None:
    """注入跨线程澄清信号（由 desktop adapter 在初始化时调用）。"""
    global _clarification_signal
    _clarification_signal = signal


def reset_clarification_state_for_tests() -> None:
    """测试用：清空 pending 与信号。"""
    global _clarification_signal
    with _clarification_lock:
        _pending_clarifications.clear()
    _clarification_signal = None


# =============================================================================
# 输入校验与规范化
# =============================================================================


def _coerce_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def validate_and_normalize_questions(questions_input: Any) -> list[NormalizedQuestion]:
    """校验模型给的 questions 数组并生成稳定 ID。非法抛 ClarificationValidationError。

    后端生成 question_id=q{i+1}、option_id=q{i+1}o{j+1}，忽略模型可能提供的任何 ID（FR-004）。
    """
    if not isinstance(questions_input, list) or not (
        _MIN_QUESTIONS <= len(questions_input) <= _MAX_QUESTIONS
    ):
        raise ClarificationValidationError(f"问题数量必须为 {_MIN_QUESTIONS}-{_MAX_QUESTIONS} 个")

    normalized: list[NormalizedQuestion] = []
    seen_questions: set[str] = set()
    for i, raw_q in enumerate(questions_input):
        if not isinstance(raw_q, dict):
            raise ClarificationValidationError("每个问题必须是对象")
        question_text = _coerce_str(raw_q.get("question"))
        header = _coerce_str(raw_q.get("header"))
        if not question_text:
            raise ClarificationValidationError("问题文本不能为空")
        if not header:
            raise ClarificationValidationError("问题短标题不能为空")
        if question_text in seen_questions:
            raise ClarificationValidationError("同一批次问题文本不得重复")
        seen_questions.add(question_text)

        raw_options = raw_q.get("options")
        if not isinstance(raw_options, list) or not (
            _MIN_OPTIONS <= len(raw_options) <= _MAX_OPTIONS
        ):
            raise ClarificationValidationError(f"每题选项必须为 {_MIN_OPTIONS}-{_MAX_OPTIONS} 个")

        options: list[NormalizedOption] = []
        seen_labels: set[str] = set()
        for j, raw_o in enumerate(raw_options):
            if not isinstance(raw_o, dict):
                raise ClarificationValidationError("每个选项必须是对象")
            label = _coerce_str(raw_o.get("label"))
            if not label:
                raise ClarificationValidationError("选项标签不能为空")
            if label in seen_labels:
                raise ClarificationValidationError("同一问题选项标签不得重复")
            seen_labels.add(label)
            description = _coerce_str(raw_o.get("description")) or None
            preview = _coerce_str(raw_o.get("preview")) or None
            options.append(
                NormalizedOption(
                    option_id=f"q{i + 1}o{j + 1}",
                    label=label,
                    description=description,
                    preview=preview,
                )
            )

        multi_select = bool(raw_q.get("multiSelect", False))
        normalized.append(
            NormalizedQuestion(
                question_id=f"q{i + 1}",
                question=question_text,
                header=header,
                multi_select=multi_select,
                options=options,
            )
        )
    return normalized


# =============================================================================
# 发起澄清（阻塞，由工具 handler 在 worker 线程调用）
# =============================================================================


def ask_user_question(questions_input: Any, session_id: str) -> dict[str, Any]:
    """创建 pending → emit requested → 阻塞等用户决策 → 按终态返回结果（FR-007）。

    校验失败抛 ClarificationValidationError（不创建 pending）。signal 未注册返回 unavailable。
    """
    questions = validate_and_normalize_questions(questions_input)

    if _clarification_signal is None:
        logger.warning("[clarification] 澄清信号未注册，返回 unavailable")
        return {"status": "unavailable", "answers": []}

    request_id = f"clr_{uuid.uuid4().hex[:12]}"
    event = threading.Event()
    pending = PendingClarification(
        request_id=request_id,
        session_id=(session_id or "").strip(),
        questions=questions,
        created_at=time.monotonic(),
        event=event,
    )
    with _clarification_lock:
        _pending_clarifications[request_id] = pending

    try:
        _clarification_signal.emit_requested(request_id)
        completed = event.wait(timeout=CLARIFICATION_TIMEOUT_S)
    except Exception:
        # emit 异常：清理 pending，不悬挂 worker，如实失败
        with _clarification_lock:
            _pending_clarifications.pop(request_id, None)
        logger.error("[clarification] 发起澄清失败: request=%s", request_id, exc_info=True)
        raise

    if not completed:
        _settle(request_id, "timeout")

    with _clarification_lock:
        final = _pending_clarifications.pop(request_id, None)

    if final is None:
        return {"status": "timeout", "answers": []}
    return _result_payload(final)


def _result_payload(pending: PendingClarification) -> dict[str, Any]:
    answers = [
        {
            "question": a.question,
            "selectedLabels": list(a.selected_labels),
            "otherText": a.other_text,
        }
        for a in pending.answers
    ]
    return {"status": pending.status, "answers": answers}


# =============================================================================
# 终态结算（first-decision-wins）
# =============================================================================


def _settle(
    request_id: str,
    status: ClarificationStatus,
    answers: Optional[list[ResolvedAnswer]] = None,
) -> bool:
    """把一个 pending 结算为终态并唤醒 worker。已结算（event 已 set）则幂等忽略。

    返回是否由本次调用真正结算。resolved 事件在锁外发出，避免持锁 emit。
    """
    with _clarification_lock:
        pending = _pending_clarifications.get(request_id)
        if pending is None or pending.event.is_set():
            return False
        pending.status = status
        pending.answers = answers or []
        pending.event.set()
    _emit_resolved_safe(request_id)
    return True


def _emit_resolved_safe(request_id: str) -> None:
    signal = _clarification_signal
    if signal is None:
        return
    try:
        signal.emit_resolved(request_id)
    except Exception:
        logger.warning(
            "[clarification] resolved 事件发送失败: request=%s", request_id, exc_info=True
        )


def submit_decision(
    session_id: str,
    request_id: str,
    decision: ClarificationDecision,
    answers_input: Any = None,
) -> dict[str, Any]:
    """处理用户决策（submit/cancel）。

    - 归属错配 → LookupError（API 映射 404，不泄漏存在性）。
    - 已结算/过期/重复 → 幂等返回当前终态，accepted=False。
    - submit 校验失败 → ClarificationValidationError（API 映射 422，不结算）。
    """
    sid = (session_id or "").strip()
    with _clarification_lock:
        pending = _pending_clarifications.get(request_id)
        if pending is None or pending.session_id != sid:
            raise LookupError("clarification not found")
        already_settled = pending.event.is_set()
        current_status = pending.status
        questions = pending.questions

    if already_settled:
        return {"requestId": request_id, "status": current_status, "accepted": False}

    if decision == "cancel":
        settled = _settle(request_id, "cancelled")
        status = "cancelled" if settled else _current_status(request_id, current_status)
        return {"requestId": request_id, "status": status, "accepted": settled}

    if decision != "submit":
        raise ClarificationValidationError("decision 必须是 submit 或 cancel")

    resolved = _validate_and_build_answers(questions, answers_input)
    settled = _settle(request_id, "answered", resolved)
    if not settled:
        return {
            "requestId": request_id,
            "status": _current_status(request_id, current_status),
            "accepted": False,
        }
    return {"requestId": request_id, "status": "answered", "accepted": True}


def _current_status(request_id: str, fallback: ClarificationStatus) -> ClarificationStatus:
    with _clarification_lock:
        pending = _pending_clarifications.get(request_id)
        return pending.status if pending is not None else fallback


def _validate_and_build_answers(
    questions: list[NormalizedQuestion],
    answers_input: Any,
) -> list[ResolvedAnswer]:
    """校验提交答案并映射 selectedOptionIds→selectedLabels。非法抛 ClarificationValidationError。"""
    if not isinstance(answers_input, list):
        raise ClarificationValidationError("answers 必须是数组")
    by_qid = {a.get("questionId"): a for a in answers_input if isinstance(a, dict)}
    if len(by_qid) != len(answers_input):
        raise ClarificationValidationError("answers 含非法或重复的 questionId")

    resolved: list[ResolvedAnswer] = []
    for q in questions:
        ans = by_qid.get(q.question_id)
        if ans is None:
            raise ClarificationValidationError(f"问题 {q.question_id} 缺少答案")

        selected_ids = ans.get("selectedOptionIds") or []
        if not isinstance(selected_ids, list) or not all(isinstance(x, str) for x in selected_ids):
            raise ClarificationValidationError("selectedOptionIds 必须是字符串数组")

        valid_ids = {o.option_id: o.label for o in q.options}
        unknown = [x for x in selected_ids if x not in valid_ids]
        if unknown:
            raise ClarificationValidationError(f"问题 {q.question_id} 含非法选项 ID")
        # 去重保持顺序
        seen: set[str] = set()
        ordered_ids = [x for x in selected_ids if not (x in seen or seen.add(x))]

        other_text_raw = ans.get("otherText")
        other_text = other_text_raw.strip() if isinstance(other_text_raw, str) else ""
        if len(other_text) > OTHER_TEXT_MAX_CHARS:
            raise ClarificationValidationError(f"其他文本不得超过 {OTHER_TEXT_MAX_CHARS} 字符")

        has_other = bool(other_text)
        if not q.multi_select:
            # 单选：恰好一个选项 或 一段其他文本（二选一，不可全空）
            if has_other and ordered_ids:
                raise ClarificationValidationError(
                    f"单选问题 {q.question_id} 不能同时选选项与填其他"
                )
            if len(ordered_ids) > 1:
                raise ClarificationValidationError(f"单选问题 {q.question_id} 只能选一个选项")
            if not ordered_ids and not has_other:
                raise ClarificationValidationError(f"问题 {q.question_id} 必须作答")
        else:
            # 多选：选项与其他可组合，但不可全空
            if not ordered_ids and not has_other:
                raise ClarificationValidationError(f"问题 {q.question_id} 必须作答")

        resolved.append(
            ResolvedAnswer(
                question=q.question,
                selected_labels=[valid_ids[x] for x in ordered_ids],
                other_text=other_text or None,
            )
        )
    return resolved


def settle_clarifications_for_session(session_id: str, status: ClarificationStatus) -> list[str]:
    """结算属于指定会话、仍 pending 的澄清（停止当前回合用，status=stopped）。"""
    sid = (session_id or "").strip()
    if not sid:
        return []
    with _clarification_lock:
        request_ids = [
            rid
            for rid, p in _pending_clarifications.items()
            if not p.event.is_set() and p.session_id == sid
        ]
    settled = [rid for rid in request_ids if _settle(rid, status)]
    return settled


def settle_all_clarifications(status: ClarificationStatus) -> list[str]:
    """结算所有仍 pending 的澄清（应用关闭用，status=shutdown）。"""
    with _clarification_lock:
        request_ids = [rid for rid, p in _pending_clarifications.items() if not p.event.is_set()]
    return [rid for rid in request_ids if _settle(rid, status)]


# =============================================================================
# 只读 getter（供 desktop adapter 构建事件/快照）
# =============================================================================


def get_pending(request_id: str) -> Optional[PendingClarification]:
    with _clarification_lock:
        return _pending_clarifications.get(request_id)


def get_pending_for_session(session_id: str) -> Optional[PendingClarification]:
    """返回该会话当前仍 pending（未结算）的澄清，供 pending 快照接口使用。"""
    sid = (session_id or "").strip()
    if not sid:
        return None
    with _clarification_lock:
        for p in _pending_clarifications.values():
            if p.session_id == sid and not p.event.is_set():
                return p
    return None


def get_remaining_timeout_ms(request_id: str) -> Optional[int]:
    with _clarification_lock:
        pending = _pending_clarifications.get(request_id)
        if pending is None:
            return None
        if pending.event.is_set():
            return 0
        created_at = pending.created_at
    elapsed_ms = int((time.monotonic() - created_at) * 1000)
    return int(CLARIFICATION_TIMEOUT_S * 1000) - elapsed_ms

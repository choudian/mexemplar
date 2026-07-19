"""创建确认卡协议（033 US1）。

独立 pending dict + 独立 Lock + first-decision-wins + ``expires_at``。完全独立于 019
的 ``clarification_manager``（不复用其后端协议）：本卡由主助理 ``create_scheduled_task``
工具触发，承载「核对解析结果 + 勾选免确认 + 取消」，经独立事件 ``scheduling.confirmation_*``
通知前端。

内存态（与 019 一致）：sidecar 重启丢失 pending 卡 = 用户重说一句，安全可接受；超时 =
fail-closed 不创建（FR-006）。``request_id`` 前缀 ``scf_``（``ID_PREFIX_SCHEDULING_CONFIRMATION``）。
"""

from __future__ import annotations

import copy
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal, Optional

from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

SchedulingConfirmationStatus = Literal[
    "pending", "confirmed", "cancelled", "timeout", "stopped", "shutdown"
]
SchedulingDecision = Literal["confirm", "cancel"]
FailClosedSettlementStatus = Literal["timeout", "stopped", "shutdown"]

_PENDING: dict[str, "_PendingConfirmation"] = {}
_LOCK = threading.Lock()


@dataclass
class _PendingConfirmation:
    request_id: str
    session_id: str
    draft: dict[str, Any]
    unattended_auto_approve: bool
    expires_at: datetime
    status: SchedulingConfirmationStatus = "pending"
    # 结果任务投影（confirm 落库后填，供 submit_decision 返回）
    created_task: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = field(default_factory=dict)


def _new_request_id() -> str:
    return f"scf_{uuid.uuid4().hex[:12]}"


def _resolve_timeout_seconds() -> int:
    """确认卡超时（走 UnifiedConfigManager，bounded [30, 3600]，默认 300）。"""
    from src.data.unified_config import get_unified_config

    return get_unified_config().get_scheduler_confirmation_timeout_seconds()


def _expires_at_now_plus(timeout_seconds: int) -> datetime:
    return utc_now_naive() + _timedelta_seconds(timeout_seconds)


def _timedelta_seconds(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)


def create(draft: dict[str, Any], session_id: str) -> str:
    """创建 pending 确认卡，emit ``scheduling_confirmation_requested``。

    Args:
        draft: 草稿（含 ``scheduleDescription`` / ``next_fire_at`` 等试算字段；payload 投影
            时只暴露核对所需的安全子集）。
        session_id: 触发创建的主助理会话 id（用户正在对话的那个）。

    Returns:
        新 ``request_id``。
    """
    request_id = _new_request_id()
    timeout = _resolve_timeout_seconds()
    pending = _PendingConfirmation(
        request_id=request_id,
        session_id=(session_id or "").strip(),
        # 调用方仍可能复用或修改原 dict；pending 必须冻结创建时语义，尤其不能让
        # 后续嵌套 schedule_payload 变更绕过用户看过的确认内容。
        draft=copy.deepcopy(draft),
        unattended_auto_approve=False,
        expires_at=_expires_at_now_plus(timeout),
    )
    with _LOCK:
        _PENDING[request_id] = pending
    try:
        _emit_requested(pending)
    except Exception:
        # 请求卡未成功发布时，用户没有任何安全方式作出决定；必须撤销 pending，
        # 不能留下一个可被迟到 REST 请求确认的隐形任务。
        with _LOCK:
            current = _PENDING.get(request_id)
            if current is pending and current.status == "pending":
                current.status = "stopped"
                _PENDING.pop(request_id, None)
        raise
    return request_id


def submit_decision(
    request_id: str,
    decision: SchedulingDecision,
    edited_draft: dict[str, Any] | None = None,
    unattended_auto_approve: bool = False,
    *,
    service_factory=None,
) -> dict[str, Any] | None:
    """提交决策（first-decision-wins）。

    - 已结算 / 不存在 → 返回 None（调用方映射 404，不泄漏存在性）。
    - ``confirm`` → 只把 edited 的公开 ``title`` / ``instruction`` 合并进后端原 draft，
      再经 ``SchedulerService.create_from_draft`` 落库，emit
      ``scheduling_confirmation_resolved(confirmed)``，返回创建的任务投影。
    - ``cancel`` → 不落库，emit ``scheduling_confirmation_resolved(cancelled)``，返回 ``{}``。

    ``unattended_auto_approve`` 作为位置或关键字参数均可；router 层建议按位置传入以
    避免 snake_case 字面量进入 router 源码（CC-005 guard test 静态断言）。

    ``service_factory``：可选 ``Callable[[], SchedulerService]``，默认 ``SchedulerService()``。
    """
    timed_out: _PendingConfirmation | None = None
    with _LOCK:
        pending = _PENDING.get(request_id)
        if pending is None or pending.status != "pending":
            return None
        # 过期裁定必须和 first-decision-wins 共用同一把锁。即使前端倒计时失效或
        # 调用方直接请求 REST，expires_at 之后也绝不能创建任务（FR-006）。
        if pending.expires_at <= utc_now_naive():
            pending.status = "timeout"
            timed_out = pending
            draft_for_create = pending.draft
        else:
            draft_for_create = (
                _merge_edited_public_draft(pending.draft, edited_draft)
                if decision == "confirm"
                else pending.draft
            )
            pending.status = "confirmed" if decision == "confirm" else "cancelled"
        unattended_flag = bool(unattended_auto_approve)

    if timed_out is not None:
        _emit_resolved(timed_out, "timeout")
        _remove_terminal(timed_out)
        return None

    if decision == "confirm":
        settlement_after_failure: SchedulingConfirmationStatus | None = None
        try:
            service = _make_service(service_factory)
            try:
                task = service.create_from_draft(
                    draft_for_create, unattended_auto_approve=unattended_flag
                )
            finally:
                _close_service(service)
        except Exception:
            # 落库失败通常回滚为 pending；若创建期间 stop/shutdown/timeout 已到达，
            # 则兑现其 fail-closed 结算，不能把已停止会话的确认卡重新复活。
            with _LOCK:
                rollback = _PENDING.get(request_id)
                if rollback is not None and rollback.status == "confirmed":
                    settlement_after_failure = rollback.extra.pop(
                        "settlement_after_create_failure",
                        None,
                    )
                    rollback.status = settlement_after_failure or "pending"
            if settlement_after_failure is not None:
                _emit_resolved(pending, settlement_after_failure)
                _remove_terminal(pending)
            raise
        with _LOCK:
            pending.created_task = task
            pending.extra.pop("settlement_after_create_failure", None)
        _emit_resolved(pending, "confirmed")
        _remove_terminal(pending)
        return task

    # cancel
    _emit_resolved(pending, "cancelled")
    _remove_terminal(pending)
    return {}


def list_pending(session_id: str | None = None) -> list[dict[str, Any]]:
    """SSE 重连恢复：返回 pending 卡的可渲染安全投影。

    ``session_id`` 为空时返回全部 pending。确认卡挂在全局 AppShell，启动恢复阶段尚未必
    选中原会话，因此不能用空字符串把所有卡过滤掉。草稿只投影用户本来已在
    ``scheduling.confirmation_requested`` 事件中看到的五个字段，不暴露内部
    ``schedule_payload`` / ``next_fire_at``。
    """
    sid = (session_id or "").strip()
    with _LOCK:
        items = [
            p
            for p in _PENDING.values()
            if p.status == "pending" and (not sid or p.session_id == sid)
        ]
    return [_pending_snapshot(p) for p in items]


def expire_due() -> list[str]:
    """扫描超时 pending，逐个 fail-closed 拒绝（不创建）。

    由 SchedulerWorker 每轮顺便调用，也可由独立 ticker 驱动。
    """
    now = utc_now_naive()
    return _settle_matching("timeout", lambda pending: pending.expires_at <= now)


def settle_all_for_shutdown() -> list[str]:
    """sidecar 关闭：把所有仍 pending 的确认卡结算为 ``shutdown``（fail-closed 不创建）。"""
    return _settle_matching("shutdown", lambda _pending: True)


def settle_for_session_stopped(session_id: str) -> list[str]:
    """用户停止当前主助理回合时，结算该会话全部 scheduling confirmation。

    停止与确认提交通过 ``_LOCK`` 竞争，first-decision-wins：先提交成功的保持原结果；
    先停止的卡进入 ``stopped``，后续 REST confirm 返回未接受且绝不落库。
    """
    sid = (session_id or "").strip()
    if not sid:
        return []
    return _settle_matching("stopped", lambda pending: pending.session_id == sid)


def _settle_matching(
    status: FailClosedSettlementStatus,
    predicate: Callable[[_PendingConfirmation], bool],
) -> list[str]:
    """以同一并发顺序结算匹配卡：快照 → 二次校验 → 延迟或 emit/remove。"""
    with _LOCK:
        candidate_ids = [
            pending.request_id
            for pending in _PENDING.values()
            if predicate(pending) and _is_settleable(pending)
        ]
    settled: list[str] = []
    for request_id in candidate_ids:
        deferred = False
        with _LOCK:
            current = _PENDING.get(request_id)
            if current is None or not predicate(current) or not _is_settleable(current):
                continue
            if current.status == "pending":
                current.status = status
            else:
                _defer_settlement_after_create_failure(current, status)
                deferred = True
        if not deferred:
            _emit_resolved(current, status)
            _remove_terminal(current)
        settled.append(current.request_id)
    return settled


def _is_settleable(pending: _PendingConfirmation) -> bool:
    return pending.status == "pending" or (
        pending.status == "confirmed" and pending.created_task is None
    )


def reset_state_for_tests() -> None:
    """测试用：清空 pending 表。"""
    with _LOCK:
        _PENDING.clear()


# =============================================================================
# 内部：事件 emit + 快照投影
# =============================================================================


def _pending_snapshot(p: _PendingConfirmation) -> dict[str, Any]:
    """pending 列表的可渲染投影（仅含确认卡已经公开的草稿字段）。"""
    return {
        "requestId": p.request_id,
        "sessionId": p.session_id,
        "draft": _public_draft(p.draft),
        "unattendedAutoApprove": p.unattended_auto_approve,
        "expiresAt": p.expires_at.isoformat(),
        "status": "pending",
    }


def _remove_terminal(pending: _PendingConfirmation) -> None:
    """终态卡从内存表移除；迟到决策仍按“不存在”fail-closed。

    pending 只用于短期 first-decision-wins，不是审计存储。保留 confirmed/cancelled/
    timeout/stopped/shutdown 条目会让长寿命 sidecar 随历史确认次数无界增长。
    """
    with _LOCK:
        current = _PENDING.get(pending.request_id)
        if current is pending and current.status != "pending":
            _PENDING.pop(pending.request_id, None)


def _defer_settlement_after_create_failure(
    pending: _PendingConfirmation,
    status: SchedulingConfirmationStatus,
) -> None:
    """记住确认落库失败后要兑现的 first-arrival fail-closed 终态。

    ``confirmed`` 在这里是“确认请求已抢到槽、落库进行中”。停止、超时或 shutdown
    不能撤销已经成功的创建；但若创建失败，它们也不能因为刚好撞上进行中窗口而丢失。
    """
    pending.extra.setdefault("settlement_after_create_failure", status)


def _public_draft(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(draft.get("title") or ""),
        "scheduleDescription": str(draft.get("scheduleDescription") or ""),
        "instruction": str(draft.get("instruction") or ""),
        "scheduleKind": str(draft.get("schedule_kind") or ""),
        "sourceType": str(draft.get("source_type") or ""),
    }


def _merge_edited_public_draft(
    original: dict[str, Any],
    edited: dict[str, Any] | None,
) -> dict[str, Any]:
    """只接受确认卡允许编辑的 title/instruction，保留后端权威调度字段。

    前端 DTO 使用 camelCase 且有意不返回 ``schedule_payload``。若直接以 edited draft
    替换内部 draft，不但真实 UI confirm 会缺字段失败，还会允许调用方篡改来源/调度规则。
    """
    merged = dict(original)
    if edited is None:
        return merged
    if not isinstance(edited, dict):
        raise ValueError("edited_draft must be an object")
    for key in ("title", "instruction"):
        if key in edited:
            value = str(edited.get(key) or "").strip()
            if not value:
                raise ValueError(f"{key} must not be empty")
            merged[key] = value
    return merged


def _emit_requested(p: _PendingConfirmation) -> None:
    from src.utils.events import emit

    try:
        emit(
            "scheduling_confirmation_requested",
            None,
            request_id=p.request_id,
            session_id=p.session_id,
            draft=p.draft,
            unattended_auto_approve=p.unattended_auto_approve,
            expires_at=p.expires_at.isoformat(),
        )
    except Exception:
        logger.exception(
            "scheduling_confirmation: emit requested failed for %s",
            p.request_id,
        )
        raise


def _emit_resolved(p: _PendingConfirmation, status: SchedulingConfirmationStatus) -> None:
    from src.utils.events import emit

    try:
        emit(
            "scheduling_confirmation_resolved",
            None,
            request_id=p.request_id,
            session_id=p.session_id,
            status=status,
        )
    except Exception:
        logger.warning(
            "scheduling_confirmation: emit resolved failed for %s", p.request_id, exc_info=True
        )


def _make_service(service_factory):
    if service_factory is not None:
        return service_factory()
    from src.business.scheduling.scheduler_service import SchedulerService

    return SchedulerService()


def _close_service(service) -> None:
    close = getattr(service, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("scheduling_confirmation: service close failed", exc_info=True)


# =============================================================================
# 模块级单例风格（仿 clarification_manager / get_mcp_server_service）
# =============================================================================


class SchedulingConfirmationManager:
    """Thin facade 把模块函数包成可注入的 manager（测试与 desktop 注入复用）。"""

    def create(self, draft: dict[str, Any], session_id: str) -> str:
        return create(draft, session_id)

    def submit_decision(
        self,
        request_id: str,
        decision: SchedulingDecision,
        edited_draft: dict[str, Any] | None = None,
        unattended_auto_approve: bool = False,
        *,
        service_factory=None,
    ) -> dict[str, Any] | None:
        return submit_decision(
            request_id,
            decision,
            edited_draft,
            unattended_auto_approve,
            service_factory=service_factory,
        )

    def list_pending(self, session_id: str | None = None) -> list[dict[str, Any]]:
        return list_pending(session_id)

    def expire_due(self) -> list[str]:
        return expire_due()

    def settle_all_for_shutdown(self) -> list[str]:
        return settle_all_for_shutdown()

    def settle_for_session_stopped(self, session_id: str) -> list[str]:
        return settle_for_session_stopped(session_id)


_manager: SchedulingConfirmationManager | None = None


def get_scheduling_confirmation_manager() -> SchedulingConfirmationManager:
    """模块级单例（desktop lifespan 启动时取一次，业务代码共享）。"""
    global _manager
    if _manager is None:
        _manager = SchedulingConfirmationManager()
    return _manager

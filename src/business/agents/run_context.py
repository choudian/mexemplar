"""Agent 运行上下文与可中断取消注册表（014-assistant-chat-transparency）。

纯进程内、会话级内存原语，**不写配置/SQLite/DuckDB**（与"免确认/会话级状态"同纪律）。

⚠️ 承重不变量（E1）：助理走 100% 调度，子代理 / 专员在**同一 worker 线程内同步**跑子
loop（调用栈 `父 loop → 工具 handler → 子 loop.run`）。ContextVar 沿同线程同步调用栈自动
传播——子 loop `get_current()` 读到的是**父助理那一份** `CancelToken`，故停止一次即父子皆停
（深度取消）。一旦委派改走线程 / 异步执行，ContextVar 不再传播，深度取消失效，必须重审取消
机制——该不变量由 `tests/guardrails` 的同线程门卫测试守护。
"""

from __future__ import annotations

import contextvars
import logging
import threading
from dataclasses import dataclass
from typing import Iterable, Optional

from src.execution.cancellation import (
    CancelReason,
    CancelToken,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunContext:
    """一次 Agent 运行的取消上下文（存入 ContextVar，沿同步调用栈传播）。"""

    root_session_id: str
    cancel_token: CancelToken
    generation: int
    run_id: str
    cancel_keys: tuple[str, ...] = ()

    @property
    def cancel_event(self) -> CancelToken:
        """014 compatibility alias while callers migrate to ``cancel_token``."""
        return self.cancel_token


@dataclass
class _SessionCancel:
    token: CancelToken
    generation: int
    run_id: str
    cancel_keys: tuple[str, ...] = ()


_run_context: contextvars.ContextVar[Optional[RunContext]] = contextvars.ContextVar(
    "assistant_run_context", default=None
)

# 进程内 session_id → CancelToken 注册表，由停止端点按会话查找并 cancel。
_lock = threading.Lock()
_registry: dict[str, _SessionCancel] = {}
# 额外取消键 → 当前运行事件。统一任务派发跨线程运行，ContextVar 不会从主助理线程传播；
# worker 用 graph/task/attempt key 显式注册，graph stop 可精准 set 当前图的事件。
_key_registry: dict[str, set[CancelToken]] = {}
# 待停止集合：停止早于 begin() 登记 Event 时记录意图，begin 命中即按取消起步（C2-E3）。
_pending_cancel: dict[str, CancelReason] = {}
# 代际计数器：每次运行 +1，使陈旧 set / end 无法影响复用同一 session 的新一轮运行（E2）。
_generation_counter = 0
# 活动事件 seq：按 root_session_id 单调递增，主助理与其子代理步骤共享排序（前端按 seq 交织）。
_activity_seq: dict[str, int] = {}
# 单回合活动事件上限：防极端长回合刷爆前端 store（E4）。超限后不再 emit。
MAX_ACTIVITY_EVENTS_PER_RUN = 500


def _require_session_id(session_id: str | None) -> str:
    """清洗并校验 session_id；空/空白时抛 ValueError。"""
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id must not be empty")
    return sid


def _run_id_for_generation(generation: int) -> str:
    return f"run-{generation}"


def begin(root_session_id: str, cancel_keys: Iterable[str] | None = None) -> RunContext:
    """在 worker 线程入口登记一次运行的取消上下文。

    返回的 RunContext 同时写入 ContextVar——同线程同步派出的子 loop 会自动继承。
    """
    global _generation_counter
    sid = _require_session_id(root_session_id)
    token = CancelToken()
    keys = tuple(dict.fromkeys(str(key).strip() for key in (cancel_keys or ()) if str(key).strip()))
    with _lock:
        _generation_counter += 1
        generation = _generation_counter
        # 早停竞态（C2-E3）：停止意图早于本次 begin 登记时，回合启动即按取消起步。
        if sid in _pending_cancel:
            reason = _pending_cancel.pop(sid)
            token.cancel(reason)
            logger.info("[run_context] 早到的停止意图命中，回合启动即取消: %s", sid)
        # 代际 token（E2）：每次运行配新 generation；end() 只清除同代条目。陈旧 set 作用在
        # 旧 event 上，而新一轮从 ContextVar 读到的是新 event，故不会被误取消。
        run_id = _run_id_for_generation(generation)
        _registry[sid] = _SessionCancel(
            token=token,
            generation=generation,
            run_id=run_id,
            cancel_keys=keys,
        )
        for key in keys:
            _key_registry.setdefault(key, set()).add(token)
    ctx = RunContext(
        root_session_id=sid,
        cancel_token=token,
        generation=generation,
        run_id=run_id,
        cancel_keys=keys,
    )
    _run_context.set(ctx)
    return ctx


def end() -> None:
    """运行结束清理：移除注册表中本代条目并清空 ContextVar。"""
    ctx = _run_context.get()
    if ctx is not None:
        with _lock:
            current = _registry.get(ctx.root_session_id)
            # 仅清除"本次运行"的条目；陈旧 end 不误删新一轮（E2）。
            if current is not None and current.generation == ctx.generation:
                _registry.pop(ctx.root_session_id, None)
                _activity_seq.pop(ctx.root_session_id, None)
            for key in ctx.cancel_keys:
                events = _key_registry.get(key)
                if events is None:
                    continue
                events.discard(ctx.cancel_token)
                if not events:
                    _key_registry.pop(key, None)
    _run_context.set(None)


def next_activity_seq() -> Optional[int]:
    """为当前运行的活动事件取下一个单调递增 seq；非可观测运行（ContextVar 空）返回 None。"""
    ctx = _run_context.get()
    if ctx is None:
        return None
    with _lock:
        nxt = _activity_seq.get(ctx.root_session_id, 0) + 1
        _activity_seq[ctx.root_session_id] = nxt
        return nxt


def get_current() -> Optional[RunContext]:
    """返回当前上下文的运行上下文；非助理流程从未 begin → None（取消检查恒 False，零行为变化）。"""
    return _run_context.get()


def request_cancel(
    session_id: str,
    expected_run_id: str | None = None,
    *,
    reason: CancelReason = CancelReason.USER_CANCEL,
) -> bool:
    """对指定会话发出取消信号（停止端点调用）。

    若该会话当前有登记的运行 → set 其 cancel_event，返回 True。
    若尚无登记（运行未启动或已结束）→ 返回 False；由 runtime 决定是否记为待停止。
    expected_run_id 非空时，只取消同一代运行，避免旧停止请求迟到后误停新一轮。
    """
    sid = _require_session_id(session_id)
    expected = (expected_run_id or "").strip()
    with _lock:
        entry = _registry.get(sid)
        if entry is None:
            return False
        if expected and entry.run_id != expected:
            return False
        token = entry.token
    token.cancel(reason)
    return True


def request_cancel_key(
    cancel_key: str,
    *,
    reason: CancelReason = CancelReason.USER_CANCEL,
) -> bool:
    """Cancel all current runs registered under a graph/task/attempt key."""
    key = str(cancel_key or "").strip()
    if not key:
        return False
    with _lock:
        tokens = tuple(_key_registry.get(key, ()))
    for token in tokens:
        token.cancel(reason)
    return bool(tokens)


def mark_pending_cancel(
    session_id: str,
    *,
    reason: CancelReason = CancelReason.USER_CANCEL,
) -> None:
    """记录"待停止"意图，由下一次 begin() 命中即取消（覆盖停止早于 begin 登记的早停竞态 C2-E3）。

    仅应在 runtime 确认该会话确有 worker 已派发但尚未登记时调用，避免污染未来无关运行。
    """
    sid = _require_session_id(session_id)
    with _lock:
        _pending_cancel.setdefault(sid, CancelReason(reason))


def is_cancel_requested(session_id: str) -> bool:
    """只读查询某会话当前是否已被请求取消（诊断/测试用）。"""
    sid = _require_session_id(session_id)
    with _lock:
        entry = _registry.get(sid)
        return bool(entry and entry.token.is_set())


def reset_for_tests() -> None:
    """清空全部内存状态（仅测试使用）。"""
    global _generation_counter
    with _lock:
        _registry.clear()
        _key_registry.clear()
        _pending_cancel.clear()
        _activity_seq.clear()
        _generation_counter = 0
    _run_context.set(None)

"""Parent-side reentry sink：dispatcher worker → 主助理续跑的受控回流通道。

不通过 blinker（constitution 原则 I「事件只通知不调度」）：``ParentReentrySink`` 是
``TaskDispatcher`` 构造期显式注入的回调对象，作用域限于 dispatcher 线程池 → 调用方
（AssistantRuntime）之间。子任务 attempt 完成并建好父侧裁定后，dispatcher 调
``sink.dispatch``，sink 据此决定是否 kick 一个续跑 worker 让主助理基于回流结果续跑
（FR-004 非阻塞回流重入）。

本类只做"按 session 的回流队列 + 唤醒协调"，通过注入的 callable 与上层 runtime 解耦，
不 import desktop_api / AssistantRuntime，因此可安全驻留在 business 层。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class ParentReentrySink:
    """受控回流队列 + 唤醒协调。

    - ``dispatch(payload)``：dispatcher worker 线程调用。按 ``payload["sessionId"]`` 入队；
      若该 session 当前无活跃 assistant worker，kick 一个续跑 worker。
    - ``drain(session_id)``：续跑 worker 首轮调用，取走并清空该 session 的全部待消费回流。
    - ``has_pending(session_id)``：worker 退出前的 tail-kick 检查，防续跑中新回流丢失。
    """

    def __init__(
        self,
        *,
        has_active_worker: Callable[[str], bool],
        kick_reentry_run: Callable[[str, str], bool],
    ) -> None:
        self._has_active_worker = has_active_worker
        self._kick_reentry_run = kick_reentry_run
        self._lock = threading.Lock()
        self._pending: dict[str, list[dict]] = {}

    def dispatch(self, payload: dict) -> None:
        session_id = payload.get("sessionId")
        graph_id = payload.get("graphId")
        if not session_id or not graph_id:
            # 缺 session/graph 的回流（task 行已不存在）无法 kick 续跑；丢弃并记录。
            logger.warning(
                "[reentry] drop payload without session/graph: task=%s",
                payload.get("taskId"),
            )
            return
        with self._lock:
            self._pending.setdefault(session_id, []).append(payload)
            # 锁内决定是否需要 kick：避免多个 dispatcher worker 同时看到"无活跃 worker"
            # 而重复 kick。kick_reentry_run 自身也 first-wins，双保险。
            needs_kick = not self._has_active_worker(session_id)
        if needs_kick:
            kicked = self._kick_reentry_run(session_id, graph_id)
            if not kicked:
                # kick 返回 False=已有活跃 worker（first-wins）；回流留队列，由该 worker drain。
                logger.debug("[reentry] kick skipped (active worker) session=%s", session_id)

    def drain(self, session_id: str) -> list[dict]:
        with self._lock:
            return self._pending.pop(session_id, [])

    def has_pending(self, session_id: str) -> bool:
        with self._lock:
            return bool(self._pending.get(session_id))

    def notify_graph_complete(self, graph_id: str, session_id: str) -> None:
        """024: 全图终态 → 经 dispatch 通道 kick 续跑，让主助理 drain briefing 裁定/汇报。

        复用既有回流队列与唤醒协调（不新增通道）。graph 级去重：若该图已有未消费的
        ``graph_completed`` 条目（drain 前），不再重复入队——避免含失败图 root 不收口时，
        重复 ``_advance`` 触发堆积永不消化的完成条目、反复唤醒主助理并污染 briefing。
        ``drain`` 清空后允许再次通知（如主助理裁定 returned 后图重跑再次全终态）。
        """
        if not session_id or not graph_id:
            logger.debug(
                "[reentry] notify_graph_complete skipped: missing session/graph"
            )
            return
        with self._lock:
            pending = self._pending.setdefault(session_id, [])
            if any(
                e.get("event") == "graph_completed" and e.get("graphId") == graph_id
                for e in pending
            ):
                # 该图已有未消费的完成通知，不重复入队（drain 后清除，允许下次再通知）
                return
            pending.append(
                {
                    "sessionId": session_id,
                    "graphId": graph_id,
                    "event": "graph_completed",
                    # 中性文案：全成功/含失败均适用；权威状态以 briefing 的
                    # _render_graph_progress 据 snapshot 实时渲染为准。
                    "safeSummary": "任务图已进入终态，请根据图进度向用户汇报或裁定后续。",
                }
            )
            needs_kick = not self._has_active_worker(session_id)
        if needs_kick:
            kicked = self._kick_reentry_run(session_id, graph_id)
            if not kicked:
                logger.debug("[reentry] kick skipped (active worker) session=%s", session_id)

    def re_enqueue(self, session_id: str, entries: list[dict]) -> None:
        """把 drain 取走的回流重新入队（run_agent 异常时调用，防条目永久丢失）。

        仅重新入队，不触发 kick——调用方（续跑 worker）负责在 except 后跳过本次
        tail-kick，避免同一失败立即重试的死循环；条目留待下次 dispatch/新消息处理。
        """
        if not entries:
            return
        with self._lock:
            self._pending.setdefault(session_id, []).extend(entries)

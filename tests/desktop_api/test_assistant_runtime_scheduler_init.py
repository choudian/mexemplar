"""C3：scheduler 装配失败必须可观测（ERROR + 后果），不得静默继续（硬规则⑥）。

dispatcher 构造失败时进程级 GraphScheduler 单例不会注册，之后 build/mutate_task_graph
与 recovery 的 get_graph_scheduler() 全返回 None，图建好后节点不推进、主助理收不到回流，
形成前端无提示的静默卡死。装配期是唯一集中入口，必须 ERROR 级暴露。
"""

from __future__ import annotations

import logging

from src.desktop_api.assistant_runtime import AssistantRuntime


class _BadDispatcherOrchestrator:
    """模拟 dispatcher 装配抛错的 orchestrator。"""

    def _get_task_dispatcher(self):
        raise RuntimeError("dispatcher boom")


def test_ensure_task_scheduler_logs_error_when_dispatcher_fails(caplog):
    runtime = AssistantRuntime.__new__(AssistantRuntime)  # 跳过重装配，只测方法
    with caplog.at_level(logging.ERROR, logger="src.desktop_api.assistant_runtime"):
        # 不得抛——装配失败要让 runtime 继续提供其余能力（对话等）
        runtime._ensure_task_scheduler_for_orchestrator(_BadDispatcherOrchestrator())

    assert any(
        r.levelno == logging.ERROR and "scheduler" in r.message.lower()
        for r in caplog.records
    ), "scheduler 装配失败必须记 ERROR 并说明后果，而非静默 warning"

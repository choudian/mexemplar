"""Background worker unit tests for task collaboration recovery cycle."""

from datetime import datetime, timezone

import pytest

from src.business.task_collaboration.background_worker import TaskCollaborationBackgroundWorker
from src.business.task_collaboration.graph_scheduler import set_graph_scheduler
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import AssistantTaskAttemptRepository, AssistantTaskRepository
from src.utils.timezone import utc_now_naive


def test_recovery_cycle_returns_all_four_counts(in_memory_db):
    worker = TaskCollaborationBackgroundWorker()
    counts = worker.run_recovery_cycle(now=datetime.now(tz=timezone.utc))
    assert "fenced_attempts" in counts
    assert "expired_claims" in counts
    assert "closed_channels" in counts
    assert "expired_questions" in counts


_JOB_FUNCS = {
    "fenced_attempts": "_fence_expired_attempts",
    "expired_claims": "_expire_claims",
    "closed_channels": "_close_expired_channels",
    "expired_questions": "_expire_stale_questions",
}


@pytest.mark.parametrize("failing_job", list(_JOB_FUNCS))
def test_recovery_cycle_isolates_each_failing_job(in_memory_db, monkeypatch, failing_job):
    """一个恢复 job 失败不得阻断其余 job。

    给四个 job 都挂日志 wrapper、仅目标 job 抛错；断言四个 job 全部被调用（失败者没有把
    后续 job 拦下来——这才是隔离的真正含义），失败者计 0，其余 job 的计数 key 仍在。
    旧测试只断言失败 job 自己被调用 + 计 0，没验证其余 job 仍运行，等于没测隔离。
    """
    from src.business.task_collaboration import background_worker as bw_module

    call_log: list[str] = []

    def make_wrapper(job_key: str, original, should_fail: bool):
        def wrapper(now, *args, **kwargs):
            call_log.append(job_key)
            if should_fail:
                raise RuntimeError(f"simulated failure in {job_key}")
            return original(now)

        return wrapper

    for job_key, func_name in _JOB_FUNCS.items():
        original = getattr(bw_module, func_name)
        monkeypatch.setattr(
            bw_module,
            func_name,
            make_wrapper(job_key, original, should_fail=(job_key == failing_job)),
        )

    worker = TaskCollaborationBackgroundWorker()
    counts = worker.run_recovery_cycle(now=datetime.now(tz=timezone.utc))

    # 四个 job 全部被调用：失败者没有阻断其余（真正的隔离断言）
    assert sorted(call_log) == sorted(_JOB_FUNCS), call_log
    # 失败 job 被隔离后计 0，其余 job 计数 key 仍在
    assert counts[failing_job] == 0
    for job_key in _JOB_FUNCS:
        assert job_key in counts


def test_expired_attempt_requeues_graph_task_and_notifies_scheduler(in_memory_db):
    """FR-008: lease 过期的未完成图节点必须退回可重派状态并触发 scheduler 重扫。"""

    session_id = "sess_requeue_expired_attempt"
    with TaskCollaborationService() as svc:
        result = svc.build_task_graph(
            session_id=session_id,
            nodes=[{"nodeId": "n1", "title": "会过期的节点", "description": "需要自动重派"}],
        )
        graph_id = result["graphId"]
        task_id = result["nodeTaskIds"]["n1"]
        svc.update_task_status(task_id=task_id, status="running")

    with AssistantTaskAttemptRepository() as attempts:
        attempts.start_attempt(
            task_id=task_id,
            executor_type="ephemeral_subagent",
            executor_id=task_id,
            lease_owner="test",
            lease_expires_at=utc_now_naive(),
        )

    recovered: list[tuple[str, str]] = []

    class _Scheduler:
        def on_executor_recovered(self, graph_id_arg: str, task_id_arg: str) -> None:
            recovered.append((graph_id_arg, task_id_arg))

    set_graph_scheduler(_Scheduler())
    try:
        counts = TaskCollaborationBackgroundWorker().run_recovery_cycle(now=utc_now_naive())
    finally:
        set_graph_scheduler(None)

    assert counts["fenced_attempts"] == 1
    with AssistantTaskRepository() as tasks:
        task = tasks.get_task(task_id)
        assert task.status == "pending_dispatch"
        assert task.suspend_reason is None
    assert recovered == [(graph_id, task_id)]


# ---------------------------------------------------------------------------
# unified_dispatch / proposal recovery 解耦（026 review HIGH-2）
# ---------------------------------------------------------------------------


class _ProposalDispatchFakeConfig:
    """Only the two toggles that drive the worker dispatch decision."""

    def __init__(self, *, unified_dispatch: bool, proposals: bool) -> None:
        self._unified_dispatch = unified_dispatch
        self._proposals = proposals

    def get_assistant_tasks_unified_dispatch_enabled(self) -> bool:
        return self._unified_dispatch

    def get_self_improvement_proposals_enabled(self) -> bool:
        return self._proposals


def test_worker_logs_error_when_proposals_enabled_but_dispatch_disabled(caplog):
    """启动自检:proposals 开 + unified_dispatch 关 → error 级警告。

    proposal 实施依赖 GraphScheduler,而调度器装配门控于 unified_dispatch
    (orchestrator.py:493)。误配时批准的提案无法推进至终态(kick 始终 unavailable),
    会在 in_progress 挂死——必须留下醒目可观测痕迹,否则用户无从知晓为何提案不动。
    """
    import logging

    worker = TaskCollaborationBackgroundWorker(
        config=_ProposalDispatchFakeConfig(unified_dispatch=False, proposals=True)
    )
    with caplog.at_level(
        logging.ERROR,
        logger="src.business.task_collaboration.background_worker",
    ):
        worker._warn_on_proposal_dispatch_misconfig()
    assert any(
        "unified_dispatch" in r.getMessage() and r.levelno >= logging.ERROR
        for r in caplog.records
    )


@pytest.mark.parametrize(
    "unified_dispatch,proposals",
    [(True, False), (False, False), (True, True)],
)
def test_worker_no_misconfig_warning_when_dispatch_and_proposals_aligned(
    caplog, unified_dispatch, proposals
):
    """非「proposals 开 + unified_dispatch 关」组合不自检告警。"""
    import logging

    worker = TaskCollaborationBackgroundWorker(
        config=_ProposalDispatchFakeConfig(
            unified_dispatch=unified_dispatch, proposals=proposals
        )
    )
    with caplog.at_level(
        logging.ERROR,
        logger="src.business.task_collaboration.background_worker",
    ):
        worker._warn_on_proposal_dispatch_misconfig()
    assert not any(
        "unified_dispatch" in r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.ERROR
    )


def test_recovery_tick_runs_proposal_recovery_when_dispatch_disabled_but_proposals_enabled(
    in_memory_db, monkeypatch
):
    """unified_dispatch 关 + proposals 开:proposal recovery 仍须跑,不得静默跳过。

    proposal recovery 是确定性的、不依赖 dispatcher;task collaboration recovery 才随
    unified_dispatch 开关。否则已批准提案会因调度器未装配而永久挂在 in_progress,
    无终态回报（FR-011「不静默丢任务」恢复语义）。
    """
    from src.business.task_collaboration import background_worker as bw_module

    worker = TaskCollaborationBackgroundWorker(
        config=_ProposalDispatchFakeConfig(unified_dispatch=False, proposals=True)
    )
    cycle_calls: list[dict] = []
    monkeypatch.setattr(
        worker, "run_recovery_cycle", lambda **kw: cycle_calls.append(kw) or {}
    )
    proposal_calls: list = []
    monkeypatch.setattr(
        bw_module,
        "_run_self_improvement_proposal_cycle",
        lambda now: proposal_calls.append(now) or 0,
    )

    worker._run_recovery_tick()

    assert cycle_calls == [], "task collaboration recovery must not run when dispatch is off"
    assert len(proposal_calls) == 1, "proposal recovery must still run"


def test_recovery_tick_runs_full_cycle_when_dispatch_enabled(in_memory_db, monkeypatch):
    """unified_dispatch 开:跑完整 run_recovery_cycle(内含 proposal job),不额外单跑。"""
    from src.business.task_collaboration import background_worker as bw_module

    worker = TaskCollaborationBackgroundWorker(
        config=_ProposalDispatchFakeConfig(unified_dispatch=True, proposals=True)
    )
    cycle_calls: list[dict] = []
    monkeypatch.setattr(
        worker, "run_recovery_cycle", lambda **kw: cycle_calls.append(kw) or {}
    )
    proposal_calls: list = []
    monkeypatch.setattr(
        bw_module,
        "_run_self_improvement_proposal_cycle",
        lambda now: proposal_calls.append(now) or 0,
    )

    worker._run_recovery_tick()

    assert len(cycle_calls) == 1
    assert proposal_calls == []

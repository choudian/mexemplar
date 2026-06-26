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

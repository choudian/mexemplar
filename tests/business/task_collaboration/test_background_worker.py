"""Background worker unit tests for task collaboration recovery cycle."""

from datetime import datetime, timezone

import pytest

from src.business.task_collaboration.background_worker import TaskCollaborationBackgroundWorker


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
        def wrapper(now):
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

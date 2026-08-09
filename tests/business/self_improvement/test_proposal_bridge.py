"""Tests for approved proposal -> task graph bridge."""

from __future__ import annotations

import json
import threading
from datetime import timedelta
from uuid import uuid4

from src.business.self_improvement import proposal_bridge
from src.business.self_improvement.proposal_bridge import (
    SELF_IMPROVEMENT_SESSION_PREFIX,
    SchedulerKickResult,
    run_proposal_recovery_cycle,
    trigger_implementation,
)
from src.business.task_collaboration.background_worker import (
    TaskCollaborationBackgroundWorker,
)
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.assistant_task_attempt_repository import AssistantTaskAttemptRepository
from src.data.repos.assistant_task_adjudication_repository import (
    AssistantTaskAdjudicationRepository,
)
from src.data.repos.assistant_task_repository import AssistantTaskRepository
from src.data.repos.improvement_proposal_repository import ImprovementProposalRepository
from src.utils.timezone import utc_now_naive


def _seed_approved_proposal(supplement: str = "") -> str:
    with ImprovementProposalRepository() as repo:
        row = repo.create(
            source_review_id=f"rev_bridge_{uuid4().hex}",
            finding_index=0,
            severity="med",
            finding_type="robustness",
            what="重复解析大型输出",
            evidence="同一输出被解析两次",
            suggestion="缓存解析结果",
        )
        assert row is not None
        approved = repo.approve(row.id, supplement=supplement)
        assert approved is not None
        return row.id


def _record_structured_test_result(task_id: str, *, passed: bool = True) -> None:
    with AssistantTaskAttemptRepository() as attempts:
        attempt = attempts.start_attempt(
            task_id=task_id,
            executor_type="ephemeral_subagent",
            executor_id=f"exec_{task_id}",
            lease_owner="test",
            lease_expires_at=utc_now_naive() + timedelta(minutes=5),
        )
        assert attempt is not None
        completed = attempts.complete_if_current(
            attempt_id=attempt.attempt_id,
            fence_token=attempt.fence_token,
            result_ref=json.dumps(
                {"tests_passed": passed, "summary": "pytest passed" if passed else "pytest failed"},
                ensure_ascii=False,
            ),
        )
        assert completed is not None


def test_parse_test_result_ref_treats_false_string_as_failure() -> None:
    parsed = proposal_bridge._parse_test_result_ref(
        json.dumps({"tests_passed": "false", "summary": "pytest failed"})
    )

    assert parsed is not None
    assert parsed["known"] is True
    assert parsed["tests_passed"] is False


def test_parse_test_result_ref_treats_unknown_tests_passed_as_unknown() -> None:
    parsed = proposal_bridge._parse_test_result_ref(
        json.dumps({"tests_passed": "maybe", "summary": "ambiguous"})
    )

    assert parsed is not None
    assert parsed["known"] is False
    assert parsed["tests_passed"] is False


def test_trigger_implementation_builds_valid_graph_contract(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    proposal_id = _seed_approved_proposal("先处理缓存层")
    captured: dict = {}
    worktree_path = tmp_path / ".worktrees" / "improvement" / proposal_id

    monkeypatch.setattr(
        proposal_bridge,
        "create_worktree",
        lambda proposal_id: (worktree_path, f"improvement/{proposal_id}"),
    )
    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("started"),
    )

    def fake_build_task_graph(self, *, session_id, nodes, dependencies, user_message_sequence=None):
        captured.update(
            {
                "session_id": session_id,
                "nodes": nodes,
                "dependencies": dependencies,
                "user_message_sequence": user_message_sequence,
            }
        )
        return {"graphId": "tg_bridge"}

    monkeypatch.setattr(TaskCollaborationService, "build_task_graph", fake_build_task_graph)

    trigger_implementation(proposal_id)

    assert captured["session_id"] == f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}"
    assert captured["dependencies"] == [
        {"from": f"{proposal_id}_plan", "to": f"{proposal_id}_implement"},
        {"from": f"{proposal_id}_implement", "to": f"{proposal_id}_test"},
    ]
    assert all(isinstance(node["capabilityScope"], list) for node in captured["nodes"])
    assert captured["nodes"][1]["workspaceRoot"] == str(worktree_path)
    assert "先处理缓存层" in captured["nodes"][1]["description"]

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "in_progress"
        assert row.graph_id == "tg_bridge"
        assert row.worktree_path == str(worktree_path)
        assert row.branch_name == f"improvement/{proposal_id}"


def test_trigger_implementation_cleans_up_when_mark_in_progress_cas_lost(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """mark_in_progress CAS 返回 None（并发抢占/状态已变）时，必须 cancel 孤儿 graph
    + mark_failed proposal + 删 worktree。

    Regression (026 C4): row is None 分支曾只删 worktree，已建的 task graph 成孤儿、
    proposal 仍 approved，被 run_proposal_recovery_cycle 重入再建 worktree+graph 循环。
    """
    proposal_id = _seed_approved_proposal()
    worktree_path = tmp_path / ".worktrees" / "improvement" / proposal_id
    monkeypatch.setattr(
        proposal_bridge,
        "create_worktree",
        lambda pid: (worktree_path, f"improvement/{pid}"),
    )
    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("started"),
    )
    monkeypatch.setattr(
        TaskCollaborationService,
        "build_task_graph",
        lambda self, **kw: {"graphId": "tg_orphan"},
    )

    cancelled: list[str] = []
    monkeypatch.setattr(
        TaskCollaborationService,
        "cancel_graph",
        lambda self, *, session_id, graph_id, expected_graph_version=None: cancelled.append(
            graph_id
        )
        or 1,
    )

    # 强制 mark_in_progress 返回 None（模拟 CAS 失败）
    monkeypatch.setattr(
        ImprovementProposalRepository,
        "mark_in_progress",
        lambda self, *a, **kw: None,
    )

    trigger_implementation(proposal_id)

    assert "tg_orphan" in cancelled
    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "failed"


def test_start_graph_uses_graph_scheduler_singleton(monkeypatch) -> None:
    started: list[str] = []

    class FakeScheduler:
        def start_graph(self, graph_id: str) -> None:
            started.append(graph_id)

    monkeypatch.setattr(
        "src.business.task_collaboration.graph_scheduler.get_graph_scheduler",
        lambda: FakeScheduler(),
    )

    result = proposal_bridge._start_graph("tg_runtime")
    assert result.status == "started"
    assert started == ["tg_runtime"]


def test_start_graph_returns_unavailable_when_scheduler_is_none(monkeypatch) -> None:
    """FR-011: scheduler singleton not yet assembled → graceful 'unavailable'."""
    monkeypatch.setattr(
        "src.business.task_collaboration.graph_scheduler.get_graph_scheduler",
        lambda: None,
    )

    result = proposal_bridge._start_graph("tg_unavailable")

    assert result.status == "unavailable"
    assert result.safe_error is None


def test_start_graph_distinguishes_scheduler_exception(monkeypatch) -> None:
    class BrokenScheduler:
        def start_graph(self, graph_id: str) -> None:
            raise RuntimeError("scheduler exploded at C:\\Users\\pan\\secret.env")

    monkeypatch.setattr(
        "src.business.task_collaboration.graph_scheduler.get_graph_scheduler",
        lambda: BrokenScheduler(),
    )

    result = proposal_bridge._start_graph("tg_runtime")

    assert result.status == "failed"
    assert result.safe_error
    assert "C:\\Users" not in result.safe_error
    assert ".env" not in result.safe_error


def test_trigger_implementation_marks_failed_when_scheduler_start_fails(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    proposal_id = _seed_approved_proposal()
    worktree_path = tmp_path / ".worktrees" / "improvement" / proposal_id
    monkeypatch.setattr(
        proposal_bridge,
        "create_worktree",
        lambda pid: (worktree_path, f"improvement/{pid}"),
    )
    monkeypatch.setattr(
        TaskCollaborationService,
        "build_task_graph",
        lambda self, **kw: {"graphId": "tg_scheduler_failed"},
    )
    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult(
            "failed",
            "scheduler failed without leaking C:\\Users path",
        ),
    )

    trigger_implementation(proposal_id)

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "failed"
        assert "C:\\Users" not in (row.error or "")


def test_trigger_implementation_cleans_up_when_mark_in_progress_raises(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    proposal_id = _seed_approved_proposal()
    worktree_path = tmp_path / ".worktrees" / "improvement" / proposal_id
    removed: list[str] = []
    cancelled: list[str] = []

    monkeypatch.setattr(
        proposal_bridge,
        "create_worktree",
        lambda pid: (worktree_path, f"improvement/{pid}"),
    )
    monkeypatch.setattr(
        TaskCollaborationService,
        "build_task_graph",
        lambda self, **kw: {"graphId": "tg_raises"},
    )
    monkeypatch.setattr(
        TaskCollaborationService,
        "cancel_graph",
        lambda self, *, session_id, graph_id, expected_graph_version=None: cancelled.append(
            graph_id
        )
        or 1,
    )
    monkeypatch.setattr(proposal_bridge, "remove_worktree", lambda path: removed.append(str(path)))

    def raise_mark_in_progress(self, *args, **kwargs):
        raise RuntimeError("db failed at C:\\Users\\pan\\secret.env")

    monkeypatch.setattr(
        ImprovementProposalRepository,
        "mark_in_progress",
        raise_mark_in_progress,
    )

    trigger_implementation(proposal_id)

    assert cancelled == ["tg_raises"]
    assert removed == [str(worktree_path)]
    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "failed"
        assert "C:\\Users" not in (row.error or "")
        assert ".env" not in (row.error or "")


def test_trigger_implementation_logs_original_exception_when_mark_in_progress_fails(
    in_memory_db,
    tmp_path,
    monkeypatch,
    caplog,
) -> None:
    """失败路径必须留服务端诊断(026 review HIGH-1):inner except 不得吞掉原始异常。

    公开 error 字段经脱敏只暴露安全投影,但原始异常类型/traceback 必须经 exc_info 进入
    服务端日志,否则一次偶发失败 6 个月后无从排查(tests reviewer 指出 L279 仅断言脱敏、
    未断言 caplog)。
    """
    import logging as _logging

    proposal_id = _seed_approved_proposal()
    worktree_path = tmp_path / ".worktrees" / "improvement" / proposal_id
    monkeypatch.setattr(
        proposal_bridge,
        "create_worktree",
        lambda pid: (worktree_path, f"improvement/{pid}"),
    )
    monkeypatch.setattr(
        TaskCollaborationService,
        "build_task_graph",
        lambda self, **kw: {"graphId": "tg_log"},
    )
    monkeypatch.setattr(
        TaskCollaborationService,
        "cancel_graph",
        lambda self, *, session_id, graph_id, expected_graph_version=None: 1,
    )
    monkeypatch.setattr(proposal_bridge, "remove_worktree", lambda path: None)

    def raise_mark_in_progress(self, *args, **kwargs):
        raise RuntimeError("db failed at C:\\Users\\pan\\secret.env")

    monkeypatch.setattr(
        ImprovementProposalRepository,
        "mark_in_progress",
        raise_mark_in_progress,
    )

    with caplog.at_level(_logging.WARNING, logger="src.business.self_improvement.proposal_bridge"):
        trigger_implementation(proposal_id)

    assert any(
        record.exc_info and "db failed" in str(record.exc_info[1]) for record in caplog.records
    ), "implementation failure must log the original exception via exc_info"


def test_structured_test_result_summary_is_sanitized() -> None:
    parsed = proposal_bridge._parse_test_result_ref(
        json.dumps(
            {
                "tests_passed": True,
                "summary": "ok with sk-abcdefghijklmnopqrstuvwxyz at C:\\Users\\pan\\secret.env",
            }
        )
    )

    assert parsed is not None
    assert parsed["tests_passed"] is True
    assert "sk-abcdefgh" not in parsed["summary"]
    assert "C:\\Users" not in parsed["summary"]
    assert ".env" not in parsed["summary"]


def test_safe_public_text_fallback_never_returns_raw_text(monkeypatch) -> None:
    from src.business.self_improvement import proposal_service

    def broken_sanitizer(_text):
        raise RuntimeError("sanitizer unavailable")

    monkeypatch.setattr(proposal_service, "sanitize_proposal_public_text", broken_sanitizer)

    text = proposal_bridge._safe_public_text(
        "raw provider error sk-abcdefghijklmnopqrstuvwxyz at C:\\Users\\pan\\secret.env"
    )

    assert text == "详情不可用"
    assert "sk-" not in text
    assert "C:\\Users" not in text


def test_recovery_marks_terminal_success_graph_done(in_memory_db, tmp_path, monkeypatch) -> None:
    proposal_id = _seed_approved_proposal()
    graph_id = TaskCollaborationService().build_task_graph(
        session_id=f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}",
        nodes=[
            {
                "nodeId": "plan",
                "title": "规划改进：缓存",
                "description": "plan",
                "capabilityScope": ["read_file"],
                "workspaceRoot": str(tmp_path),
            },
            {
                "nodeId": "test",
                "title": "验证改进：缓存",
                "description": "test",
                "capabilityScope": ["exec"],
                "workspaceRoot": str(tmp_path),
            },
        ],
        dependencies=[{"from": "plan", "to": "test"}],
    )["graphId"]
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            proposal_id,
            graph_id=graph_id,
            worktree_path=str(tmp_path),
            branch_name=f"improvement/{proposal_id}",
        )
        assert row is not None

    tasks = AssistantTaskRepository().list_graph_tasks(graph_id)
    service = TaskCollaborationService()
    for task in tasks:
        if task.parent_task_id is not None:
            if task.title.startswith("验证改进"):
                _record_structured_test_result(task.task_id, passed=True)
            service.update_task_status(task_id=task.task_id, status="done")

    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )

    assert run_proposal_recovery_cycle() >= 1

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "done"
    assert row.result_tests_passed is True
    assert "tests_passed=True" in (row.result_summary or "")


def test_recovery_fails_completed_test_node_without_structured_result(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    proposal_id = _seed_approved_proposal()
    graph_id = TaskCollaborationService().build_task_graph(
        session_id=f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}",
        nodes=[
            {
                "nodeId": "test",
                "title": "验证改进：缓存",
                "description": "test",
                "capabilityScope": ["exec"],
                "workspaceRoot": str(tmp_path),
            },
        ],
    )["graphId"]
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            proposal_id,
            graph_id=graph_id,
            worktree_path=str(tmp_path),
            branch_name=f"improvement/{proposal_id}",
        )
        assert row is not None

    tasks = AssistantTaskRepository().list_graph_tasks(graph_id)
    service = TaskCollaborationService()
    for task in tasks:
        if task.parent_task_id is not None:
            service.update_task_status(task_id=task.task_id, status="done")

    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )

    assert run_proposal_recovery_cycle() >= 1

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "failed"
        assert row.result_tests_passed is None
        assert row.error == "test node completed without structured test result"


def test_trigger_implementation_serialises_concurrent_approved_proposals(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    first_id = _seed_approved_proposal()
    second_id = _seed_approved_proposal()
    created_worktrees: list[str] = []

    def fake_create_worktree(proposal_id):
        created_worktrees.append(proposal_id)
        return (
            tmp_path / ".worktrees" / "improvement" / proposal_id,
            f"improvement/{proposal_id}",
        )

    def fake_build_task_graph(self, *, session_id, nodes, dependencies, user_message_sequence=None):
        return {"graphId": f"tg_{len(created_worktrees)}"}

    monkeypatch.setattr(proposal_bridge, "create_worktree", fake_create_worktree)
    monkeypatch.setattr(TaskCollaborationService, "build_task_graph", fake_build_task_graph)
    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("started"),
    )

    threads = [
        threading.Thread(target=trigger_implementation, args=(first_id,)),
        threading.Thread(target=trigger_implementation, args=(second_id,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    with ImprovementProposalRepository() as repo:
        rows = repo.list_by_status("in_progress")
        approved = repo.list_by_status("approved")

    assert len(rows) == 1
    assert len(approved) == 1
    assert len(created_worktrees) == 1


def test_background_worker_runs_self_improvement_proposal_job(
    in_memory_db,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.background_worker._run_self_improvement_proposal_cycle",
        lambda now: 2,
    )

    result = TaskCollaborationBackgroundWorker().run_recovery_cycle()

    assert result["self_improvement_proposals"] == 2


# ---------------------------------------------------------------------------
# C5a: _prune_retained_worktrees (FR-019)
# ---------------------------------------------------------------------------


def test_recovery_prunes_stale_worktrees_beyond_retention_limit(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """FR-019: worktree retention — oldest worktrees are pruned when count > max."""
    # Create 3 done proposals with worktrees, retention_max=2
    proposal_ids = []
    for i in range(3):
        pid = _seed_approved_proposal()
        with ImprovementProposalRepository() as repo:
            row = repo.mark_in_progress(
                pid,
                graph_id=f"tg_prune_{i}",
                worktree_path=str(tmp_path / ".worktrees" / "improvement" / pid),
                branch_name=f"improvement/{pid}",
            )
            assert row is not None
            repo.mark_done(pid, tests_passed=True, summary="done")
        proposal_ids.append(pid)

    # Mock remove_worktree to track which worktrees get pruned
    removed_worktrees: list[str] = []
    monkeypatch.setattr(
        proposal_bridge,
        "remove_worktree",
        lambda path: removed_worktrees.append(str(path)),
    )
    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )
    # Set retention max to 2 (keep 2 newest, prune 1 oldest)
    _fake_config = type(
        "C",
        (),
        {"get_self_improvement_proposals_worktree_retention_max": lambda self: 2},
    )
    monkeypatch.setattr(
        "src.data.unified_config.get_unified_config",
        lambda: _fake_config(),
    )

    handled = run_proposal_recovery_cycle()

    # At least 1 worktree should have been pruned (the oldest)
    assert handled >= 1
    assert len(removed_worktrees) >= 1
    # The pruned worktree's proposal should have worktree_path cleared
    with ImprovementProposalRepository() as repo:
        pruned = repo.get_by_id(proposal_ids[0])
        assert pruned is not None
        assert pruned.worktree_path is None


def test_recovery_prune_worktree_fallback_on_config_failure(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """Config getter raises → defaults to keep=10, no crash."""
    # Create 1 done proposal with worktree
    pid = _seed_approved_proposal()
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            pid,
            graph_id="tg_config_fail",
            worktree_path=str(tmp_path / ".worktrees" / "improvement" / pid),
            branch_name=f"improvement/{pid}",
        )
        assert row is not None
        repo.mark_done(pid, tests_passed=True, summary="done")

    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )
    monkeypatch.setattr(
        "src.data.unified_config.get_unified_config",
        lambda: (_ for _ in ()).throw(RuntimeError("config broken")),
    )

    # Should not crash; with default keep=10, no pruning happens
    handled = run_proposal_recovery_cycle()
    assert handled >= 0


# ---------------------------------------------------------------------------
# C5b: _kick_next_approved_if_idle (FR-018)
# ---------------------------------------------------------------------------


def test_recovery_kicks_next_approved_after_in_progress_completes(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """FR-018: When an in_progress proposal reaches terminal state, the oldest
    approved proposal should be auto-triggered by the recovery cycle."""
    first_id = _seed_approved_proposal("first")
    second_id = _seed_approved_proposal("second")

    # First proposal: approved → in_progress → done
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            first_id,
            graph_id="tg_first",
            worktree_path=str(tmp_path / ".worktrees" / "improvement" / first_id),
            branch_name=f"improvement/{first_id}",
        )
        assert row is not None
        repo.mark_done(first_id, tests_passed=True, summary="done")

    # Mock trigger_implementation to capture which proposal gets auto-triggered
    triggered_ids: list[str] = []
    monkeypatch.setattr(
        proposal_bridge,
        "trigger_implementation",
        lambda pid: triggered_ids.append(pid),
    )
    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )
    monkeypatch.setattr(
        proposal_bridge,
        "remove_worktree",
        lambda path: None,
    )
    monkeypatch.setattr(
        "src.data.unified_config.get_unified_config",
        lambda: type(
            "C", (), {"get_self_improvement_proposals_worktree_retention_max": lambda self: 100}
        )(),
    )

    run_proposal_recovery_cycle()

    # The second (still approved) proposal should have been triggered
    assert second_id in triggered_ids


def test_recovery_does_not_kick_approved_when_in_progress_exists(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """FR-018: If there is already an in_progress proposal, no approved proposal
    should be auto-triggered."""
    first_id = _seed_approved_proposal()
    second_id = _seed_approved_proposal()

    # First proposal stays in_progress (no real graph created)
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            first_id,
            graph_id="tg_active",
            worktree_path=str(tmp_path / ".worktrees" / "improvement" / first_id),
            branch_name=f"improvement/{first_id}",
        )
        assert row is not None

    triggered_ids: list[str] = []
    monkeypatch.setattr(
        proposal_bridge,
        "trigger_implementation",
        lambda pid: triggered_ids.append(pid),
    )
    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )
    # Mock write-back to return False (graph still running, not terminal)
    monkeypatch.setattr(
        proposal_bridge,
        "_write_back_terminal_graph",
        lambda proposal: False,
    )

    run_proposal_recovery_cycle()

    # No approved proposal should be triggered while one is in_progress
    assert second_id not in triggered_ids


# ---------------------------------------------------------------------------
# C5c: UI event contract — changeType enum alignment
# ---------------------------------------------------------------------------


def test_emit_changed_uses_registered_change_types(
    in_memory_db,
    monkeypatch,
) -> None:
    """Bridge must only emit changeType values declared in UI Event Registry."""
    from src.desktop_api.ui_events import UI_EVENT_REGISTRY

    # Find the registered changeType enum for improvement_proposal.changed
    registration = UI_EVENT_REGISTRY.get("improvement_proposal.changed")
    assert (
        registration is not None
    ), "improvement_proposal.changed must be registered in UI Event Registry"

    # Extract allowed changeType values from payload_enum_values
    allowed_change_types: set[str] = set()
    for field_name, values in registration.payload_enum_values:
        if field_name == "changeType":
            allowed_change_types = values
            break

    assert allowed_change_types, "changeType must have enum values in registration"

    # Verify all _emit_changed call sites use only registered change types
    expected_change_types = {"created", "approved", "rejected", "in_progress", "done", "failed"}
    assert expected_change_types.issubset(
        allowed_change_types
    ), f"Bridge emits changeTypes {expected_change_types} but registry only allows {allowed_change_types}"


def test_recovery_fails_in_progress_proposal_without_graph_id(
    in_memory_db,
    monkeypatch,
) -> None:
    """in_progress proposal with graph_id=None → marked failed (recovery path)."""
    pid = _seed_approved_proposal()
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            pid,
            graph_id=None,
            worktree_path=None,
            branch_name=None,
        )
        assert row is not None

    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )

    assert run_proposal_recovery_cycle() >= 1

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(pid)
        assert row is not None
        assert row.status == "failed"


# ---------------------------------------------------------------------------
# create_worktree 失败路径(026 tests C1):ProposalWorkspaceError catch 分支
# ---------------------------------------------------------------------------


def test_trigger_implementation_marks_failed_when_create_worktree_dirty(
    in_memory_db,
    monkeypatch,
) -> None:
    """create_worktree 抛 ProposalWorkspaceDirty(脏残留)→ proposal 标 failed,
    error 非空,不建 task graph,无 worktree 残留。

    Regression coverage (tests C1):_trigger_implementation_inner 的
    ``except ProposalWorkspaceError`` 分支此前零覆盖 —— 所有 bridge 测试都把
    create_worktree monkeypatch 成成功。命中 CLAUDE.md「静默失败路径必须补测试」。
    """
    from src.business.self_improvement.proposal_workspace import ProposalWorkspaceDirty

    proposal_id = _seed_approved_proposal()

    built_graphs: list[dict] = []
    monkeypatch.setattr(
        proposal_bridge,
        "create_worktree",
        lambda pid: (_ for _ in ()).throw(ProposalWorkspaceDirty("worktree 路径已存在")),
    )
    monkeypatch.setattr(
        TaskCollaborationService,
        "build_task_graph",
        lambda self, **kw: built_graphs.append(kw) or {"graphId": "should_not_be_built"},
    )

    trigger_implementation(proposal_id)

    # create_worktree 在 build_task_graph 之前失败,不得建图
    assert built_graphs == []
    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "failed"
        assert row.error  # 失败原因非空
        assert "已存在" in row.error  # 原始诊断经脱敏后仍保留
        assert row.graph_id is None  # 没建图
        assert row.worktree_path is None  # 无 worktree 残留


def test_trigger_implementation_marks_failed_when_create_worktree_git_error(
    in_memory_db,
    monkeypatch,
) -> None:
    """create_worktree 抛 ProposalWorkspaceError(git 命令失败,非脏)→ 同样标 failed。"""
    from src.business.self_improvement.proposal_workspace import ProposalWorkspaceError

    proposal_id = _seed_approved_proposal()
    monkeypatch.setattr(
        proposal_bridge,
        "create_worktree",
        lambda pid: (_ for _ in ()).throw(ProposalWorkspaceError("git worktree add 失败")),
    )
    monkeypatch.setattr(
        TaskCollaborationService,
        "build_task_graph",
        lambda self, **kw: {"graphId": "should_not_be_built"},
    )

    trigger_implementation(proposal_id)

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "failed"
        assert row.error


# ---------------------------------------------------------------------------
# 实施失败写回语义分支(026 tests I1):tests_passed=False / 节点 failed
# ---------------------------------------------------------------------------


def test_recovery_fails_when_test_node_reports_failing_tests(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """test 节点 completed 且有结构化结果,但 tests_passed=False → proposal failed,
    error='test node reported failing tests'。

    Regression coverage (tests I1):此语义分支(明确报告失败)此前未覆盖,
    命中 SC-006 命门 —— 不得把失败测试当成功标 done。"""
    proposal_id = _seed_approved_proposal()
    graph_id = TaskCollaborationService().build_task_graph(
        session_id=f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}",
        nodes=[
            {
                "nodeId": "plan",
                "title": "规划改进：缓存",
                "description": "plan",
                "capabilityScope": ["read_file"],
                "workspaceRoot": str(tmp_path),
            },
            {
                "nodeId": "test",
                "title": "验证改进：缓存",
                "description": "test",
                "capabilityScope": ["exec"],
                "workspaceRoot": str(tmp_path),
            },
        ],
        dependencies=[{"from": "plan", "to": "test"}],
    )["graphId"]
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            proposal_id,
            graph_id=graph_id,
            worktree_path=str(tmp_path),
            branch_name=f"improvement/{proposal_id}",
        )
        assert row is not None

    tasks = AssistantTaskRepository().list_graph_tasks(graph_id)
    service = TaskCollaborationService()
    for task in tasks:
        if task.parent_task_id is not None:
            if task.title.startswith("验证改进"):
                _record_structured_test_result(task.task_id, passed=False)
            service.update_task_status(task_id=task.task_id, status="done")

    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )

    assert run_proposal_recovery_cycle() >= 1

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "failed"
        assert row.result_tests_passed is False
        assert row.error == "test node reported failing tests"


def test_recovery_fails_when_implementation_node_abandoned(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """执行节点 status=abandoned(非全 completed)→ proposal failed,
    error='implementation task graph finished with abandoned or cancelled nodes'。

    两个 failed 是两个状态机：任务节点被**放弃**，导致这个**提案**的实施结果是失败。

    Regression coverage (tests I1):此分支(图终态含 abandoned/cancelled)此前未覆盖。"""
    proposal_id = _seed_approved_proposal()
    graph_id = TaskCollaborationService().build_task_graph(
        session_id=f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}",
        nodes=[
            {
                "nodeId": "plan",
                "title": "规划改进：缓存",
                "description": "plan",
                "capabilityScope": ["read_file"],
                "workspaceRoot": str(tmp_path),
            },
            {
                "nodeId": "implement",
                "title": "实施改进：缓存",
                "description": "implement",
                "capabilityScope": ["write_file"],
                "workspaceRoot": str(tmp_path),
            },
        ],
        dependencies=[{"from": "plan", "to": "implement"}],
    )["graphId"]
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            proposal_id,
            graph_id=graph_id,
            worktree_path=str(tmp_path),
            branch_name=f"improvement/{proposal_id}",
        )
        assert row is not None

    tasks = AssistantTaskRepository().list_graph_tasks(graph_id)
    service = TaskCollaborationService()
    for task in tasks:
        if task.parent_task_id is not None:
            status = "abandoned" if task.title.startswith("实施") else "done"
            service.update_task_status(task_id=task.task_id, status=status)

    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )

    assert run_proposal_recovery_cycle() >= 1

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "failed"
        assert row.result_tests_passed is None
        assert row.error == "implementation task graph finished with abandoned or cancelled nodes"


def test_recovery_identifies_test_node_by_graph_structure_not_title(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """测试节点按图结构（叶子节点）识别，不依赖标题前缀（026 I3）。

    Regression: ``_write_back_terminal_graph`` 曾用 ``task.title.startswith("验证改进")``
    找测试节点；标题文案一改（本地化、改写）就漏识别，把已通过的提案误标
    ``failed("test node completed without structured test result")``。修复后用
    出度为 0 的执行节点（叶子）定位测试节点，与文案解耦。
    """
    proposal_id = _seed_approved_proposal()
    graph_id = TaskCollaborationService().build_task_graph(
        session_id=f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}",
        nodes=[
            {
                "nodeId": "plan",
                "title": "规划改进：缓存",
                "description": "plan",
                "capabilityScope": ["read_file"],
                "workspaceRoot": str(tmp_path),
            },
            {
                "nodeId": "implement",
                "title": "实施改进：缓存",
                "description": "implement",
                "capabilityScope": ["write_file"],
                "workspaceRoot": str(tmp_path),
            },
            {
                # 故意不用"验证改进"前缀 —— 必须靠图结构（叶子）识别而非标题
                "nodeId": "test",
                "title": "Run pytest suite",
                "description": "test",
                "capabilityScope": ["exec"],
                "workspaceRoot": str(tmp_path),
            },
        ],
        dependencies=[
            {"from": "plan", "to": "implement"},
            {"from": "implement", "to": "test"},
        ],
    )["graphId"]
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            proposal_id,
            graph_id=graph_id,
            worktree_path=str(tmp_path),
            branch_name=f"improvement/{proposal_id}",
        )
        assert row is not None

    tasks = AssistantTaskRepository().list_graph_tasks(graph_id)
    service = TaskCollaborationService()
    for task in tasks:
        if task.parent_task_id is None:
            continue
        if task.title == "Run pytest suite":  # 夹具知道测试节点 title
            _record_structured_test_result(task.task_id, passed=True)
        service.update_task_status(task_id=task.task_id, status="done")

    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )

    assert run_proposal_recovery_cycle() >= 1

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "done"
    assert row.result_tests_passed is True


def test_exec_envelope_result_coerces_bool_exit_code() -> None:
    """exec envelope 的 exitCode 布尔值必须强转 int 再判 passed（026 I3 fallback 覆盖）。

    ``exitCode: true`` (bool) → int(True)=1，非 0 → passed=False。此前 exec envelope
    解析路径（fallback 第 3 级）零覆盖。
    """
    result = proposal_bridge._exec_envelope_result(
        {"tool": "exec", "payload": {"exitCode": True}, "outcome": "success"}
    )
    assert result is not None
    assert result["known"] is True
    assert result["tests_passed"] is False
    assert "exitCode=1" in result["summary"]


def test_exec_envelope_result_zero_exit_passed() -> None:
    result = proposal_bridge._exec_envelope_result(
        {"tool": "exec", "payload": {"exitCode": 0}, "outcome": "success"}
    )
    assert result is not None
    assert result["tests_passed"] is True


def test_exec_envelope_result_non_exec_returns_none() -> None:
    result = proposal_bridge._exec_envelope_result(
        {"tool": "read_file", "payload": {"exitCode": 0}, "outcome": "success"}
    )
    assert result is None


def test_parse_test_result_ref_extracts_exec_envelope() -> None:
    """result_ref 直接是 exec envelope 时应解析出 passed/failed（026 I3 fallback 覆盖）。"""
    passed = proposal_bridge._parse_test_result_ref(
        json.dumps({"tool": "exec", "payload": {"exitCode": 0}, "outcome": "success"})
    )
    assert passed is not None
    assert passed["known"] is True
    assert passed["tests_passed"] is True

    failed = proposal_bridge._parse_test_result_ref(
        json.dumps({"tool": "exec", "payload": {"exitCode": 2}, "outcome": "error"})
    )
    assert failed is not None
    assert failed["tests_passed"] is False


def test_recovery_started_branch_kicks_once_and_auto_decides_pending_adjudication(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    """kick.status=='started' 分支也必须裁定 proposal 图的 pending adjudication。

    self-improvement 图没有真实父助理；executor 回流后产生的 pending adjudication
    必须由 proposal recovery 自动接受，否则下游节点不会解锁，proposal 会卡在
    ``in_progress``。同时 started 分支仍只 kick 一次，不进 phase 2 二次 kick。
    """
    proposal_id = _seed_approved_proposal()
    graph_id = TaskCollaborationService().build_task_graph(
        session_id=f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}",
        nodes=[
            {
                "nodeId": "plan",
                "title": "规划改进：缓存",
                "description": "plan",
                "capabilityScope": ["read_file"],
                "workspaceRoot": str(tmp_path),
            },
            {
                "nodeId": "implement",
                "title": "实施改进：缓存",
                "description": "implement",
                "capabilityScope": ["write_file"],
                "workspaceRoot": str(tmp_path),
            },
            {
                "nodeId": "test",
                "title": "验证改进：缓存",
                "description": "test",
                "capabilityScope": ["exec"],
                "workspaceRoot": str(tmp_path),
            },
        ],
        dependencies=[
            {"from": "plan", "to": "implement"},
            {"from": "implement", "to": "test"},
        ],
    )["graphId"]
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            proposal_id,
            graph_id=graph_id,
            worktree_path=str(tmp_path),
            branch_name=f"improvement/{proposal_id}",
        )
        assert row is not None

    tasks = AssistantTaskRepository().list_graph_tasks(graph_id)
    implement_task_id = next(task.task_id for task in tasks if task.title.startswith("实施改进"))
    with AssistantTaskAdjudicationRepository() as repo:
        repo.create_pending(
            task_id=implement_task_id,
            graph_id=graph_id,
            parent_session_id=f"{SELF_IMPROVEMENT_SESSION_PREFIX}{proposal_id}",
            delivered_status="done",
            safe_summary="implementation completed",
        )

    service = TaskCollaborationService()
    for task in tasks:
        if task.parent_task_id is None:
            continue
        if task.title.startswith("实施改进"):
            continue
        if task.title.startswith("验证改进"):
            _record_structured_test_result(task.task_id, passed=True)
        service.update_task_status(task_id=task.task_id, status="done")

    kick_calls: list[str] = []

    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: (kick_calls.append(graph_id), SchedulerKickResult("started"))[1],
    )

    assert run_proposal_recovery_cycle() >= 1

    assert kick_calls.count(graph_id) == 1, f"started 分支应只 kick 一次，实际 {kick_calls}"

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "done"
    assert row.result_tests_passed is True

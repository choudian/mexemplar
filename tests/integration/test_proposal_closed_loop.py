"""Closed-loop integration for self-improvement proposal implementation."""

from __future__ import annotations

import json
from datetime import timedelta

from src.business.self_improvement import proposal_bridge
from src.business.self_improvement.proposal_bridge import SchedulerKickResult
from src.business.self_improvement.proposal_bridge import (
    run_proposal_recovery_cycle,
    trigger_implementation,
)
from src.business.self_improvement.proposal_service import ProposalService
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.assistant_task_attempt_repository import AssistantTaskAttemptRepository
from src.data.repos.assistant_task_repository import AssistantTaskRepository
from src.data.repos.improvement_proposal_repository import ImprovementProposalRepository
from src.utils.timezone import utc_now_naive


def test_approved_proposal_builds_graph_and_recovery_writes_done(
    in_memory_db,
    tmp_path,
    monkeypatch,
) -> None:
    svc = ProposalService()
    created = svc.generate_from_review(
        "rev_closed_loop",
        [
            {
                "type": "robustness",
                "what": "测试闭环未回写",
                "evidence": "任务图完成后 proposal 仍 in_progress",
                "severity": "med",
                "suggestion": "增加后台回写 job",
                "worth_changing": True,
            }
        ],
    )
    assert created == 1
    proposal_id = svc.list_proposals()[0]["id"]
    approved = svc.approve(proposal_id, supplement="只验证最小闭环")
    assert approved is not None

    worktree_path = tmp_path / ".worktrees" / "improvement" / proposal_id
    monkeypatch.setattr(
        proposal_bridge,
        "create_worktree",
        lambda proposal_id: (worktree_path, f"improvement/{proposal_id}"),
    )
    monkeypatch.setattr(
        proposal_bridge,
        "_start_graph",
        lambda graph_id: SchedulerKickResult("unavailable"),
    )

    trigger_implementation(proposal_id)

    with ImprovementProposalRepository() as repo:
        row = repo.get_by_id(proposal_id)
        assert row is not None
        assert row.status == "in_progress"
        assert row.graph_id is not None
        graph_id = row.graph_id

    with AssistantTaskRepository() as task_repo:
        tasks = task_repo.list_graph_tasks(graph_id)
    graph_service = TaskCollaborationService()
    for task in tasks:
        if task.parent_task_id is not None:
            if task.title.startswith("验证改进"):
                with AssistantTaskAttemptRepository() as attempts:
                    attempt = attempts.start_attempt(
                        task_id=task.task_id,
                        executor_type="ephemeral_subagent",
                        executor_id=f"exec_{task.task_id}",
                        lease_owner="test",
                        lease_expires_at=utc_now_naive() + timedelta(minutes=5),
                    )
                    assert attempt is not None
                    completed = attempts.complete_if_current(
                        attempt_id=attempt.attempt_id,
                        fence_token=attempt.fence_token,
                        result_ref=json.dumps(
                            {"tests_passed": True, "summary": "pytest passed"},
                            ensure_ascii=False,
                        ),
                    )
                    assert completed is not None
            graph_service.update_task_status(task_id=task.task_id, status="done")

    assert run_proposal_recovery_cycle() >= 1

    proposal = svc.get_proposal(proposal_id)
    assert proposal is not None
    assert proposal["status"] == "done"
    assert proposal["resultTestsPassed"] is True
    assert "tests_passed=True" in (proposal["resultSummary"] or "")

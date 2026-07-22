"""Tests for external coding agent tool handlers."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.tools.external_coding_tools import create_external_coding_tools
from src.business.external_coding.cli_adapters import CliExternalCodingAdapter
from src.business.external_coding.models import CodingPhase, ExternalCodingTool


class _CommandConfig:
    def get_external_coding_claude_command(self):
        return "claude"

    def get_external_coding_codex_command(self):
        return "codex"

    def get_external_coding_claude_effort(self):
        return "max"

    def get_external_coding_codex_reasoning_effort(self):
        return "xhigh"


def _tools(bound_task_id: str | None = "tsk_bound"):
    return {
        tool.name: tool
        for tool in create_external_coding_tools(
            session_id="sess_test", bound_task_id=bound_task_id
        )
    }


def _mock_service_response(method_name: str, return_value: dict | None = None):
    """Patch ExternalCodingSessionService so method_name returns return_value."""
    mock_service = MagicMock()
    getattr(mock_service, method_name).return_value = return_value or {}
    mock_service.__enter__ = MagicMock(return_value=mock_service)
    mock_service.__exit__ = MagicMock(return_value=False)
    return mock_service


def test_start_external_coding_session_requires_bound_owner() -> None:
    tools = _tools(bound_task_id=None)
    result = tools["start_external_coding_session"].handler(
        ownerType="task",
        ownerId="",
        objective="do work",
    )
    payload = json.loads(result)
    assert payload["success"] is False
    assert "bound task" in payload["message"]


def test_start_external_coding_session_success() -> None:
    expected = {"codingSessionId": "ecs_001", "status": "planning"}
    mock = _mock_service_response("start_session", expected)
    with patch(
        "src.business.agents.tools.external_coding_tools.ExternalCodingSessionService",
        return_value=mock,
    ):
        tools = _tools()
        result = tools["start_external_coding_session"].handler(
            ownerType="task",
            ownerId="tsk_bound",
            objective="implement feature",
            targetWorktreePath="E:/target-repository",
        )
    payload = json.loads(result)
    assert payload["codingSessionId"] == "ecs_001"
    assert payload["status"] == "planning"
    mock.start_session.assert_called_once()
    assert mock.start_session.call_args.kwargs["owner_id"] == "tsk_bound"
    assert mock.start_session.call_args.kwargs["target_worktree_path"] == "E:/target-repository"


def test_start_external_coding_session_rejects_bound_owner_override() -> None:
    tools = _tools()

    result = tools["start_external_coding_session"].handler(
        ownerType="task",
        ownerId="tsk_other",
        objective="do work",
    )

    payload = json.loads(result)
    assert payload["success"] is False
    assert "bound task" in payload["message"]


def test_decide_external_coding_plan_approved() -> None:
    expected = {"codingSessionId": "ecs_001", "status": "plan_approved"}
    mock = _mock_service_response("decide_plan", expected)
    with patch(
        "src.business.agents.tools.external_coding_tools.ExternalCodingSessionService",
        return_value=mock,
    ):
        tools = _tools()
        result = tools["decide_external_coding_plan"].handler(
            codingSessionId="ecs_001",
            decision="approved",
        )
    payload = json.loads(result)
    assert payload["codingSessionId"] == "ecs_001"
    mock.decide_plan.assert_called_once_with(
        coding_session_id="ecs_001",
        decision="approved",
        decided_by="agent",
        feedback="",
    )
    mock.require_owner.assert_called_once_with("ecs_001", owner_type="task", owner_id="tsk_bound")


def test_decide_external_coding_plan_rejected() -> None:
    expected = {"codingSessionId": "ecs_001", "status": "plan_rejected"}
    mock = _mock_service_response("decide_plan", expected)
    with patch(
        "src.business.agents.tools.external_coding_tools.ExternalCodingSessionService",
        return_value=mock,
    ):
        tools = _tools()
        result = tools["decide_external_coding_plan"].handler(
            codingSessionId="ecs_001",
            decision="rejected",
            feedback="plan too vague",
        )
    payload = json.loads(result)
    assert payload["codingSessionId"] == "ecs_001"
    mock.decide_plan.assert_called_once_with(
        coding_session_id="ecs_001",
        decision="rejected",
        decided_by="agent",
        feedback="plan too vague",
    )


def test_resume_external_coding_session() -> None:
    expected = {"codingSessionId": "ecs_001", "status": "implementing"}
    mock = _mock_service_response("resume_session", expected)
    with patch(
        "src.business.agents.tools.external_coding_tools.ExternalCodingSessionService",
        return_value=mock,
    ):
        tools = _tools()
        result = tools["resume_external_coding_session"].handler(
            codingSessionId="ecs_001",
            instruction="continue with plan",
            phase="implement",
        )
    payload = json.loads(result)
    assert payload["codingSessionId"] == "ecs_001"
    mock.resume_session.assert_called_once_with(
        coding_session_id="ecs_001",
        instruction="continue with plan",
        phase="implement",
    )


def test_record_external_coding_review_outcome() -> None:
    expected = {
        "codingSessionId": "ecs_001",
        "reviewRecommended": False,
        "reviewSkippedReason": None,
    }
    mock = _mock_service_response("record_review_outcome", expected)
    with patch(
        "src.business.agents.tools.external_coding_tools.ExternalCodingSessionService",
        return_value=mock,
    ):
        tools = _tools()
        result = tools["record_external_coding_review_outcome"].handler(
            codingSessionId="ecs_001",
            independentlyReviewed=True,
            independentlyTested=True,
        )

    payload = json.loads(result)
    assert payload["reviewRecommended"] is False
    mock.require_owner.assert_called_once_with(
        "ecs_001",
        owner_type="task",
        owner_id="tsk_bound",
    )
    mock.record_review_outcome.assert_called_once_with(
        coding_session_id="ecs_001",
        independently_reviewed=True,
        independently_tested=True,
        skipped_reason="",
    )


def test_abandon_external_coding_session() -> None:
    expected = {"codingSessionId": "ecs_001", "status": "abandoned"}
    mock = _mock_service_response("abandon_session", expected)
    with patch(
        "src.business.agents.tools.external_coding_tools.ExternalCodingSessionService",
        return_value=mock,
    ):
        tools = _tools()
        result = tools["abandon_external_coding_session"].handler(
            codingSessionId="ecs_001",
            reason="wrong direction",
        )
    payload = json.loads(result)
    assert payload["codingSessionId"] == "ecs_001"
    mock.abandon_session.assert_called_once_with(
        coding_session_id="ecs_001",
        reason="wrong direction",
    )


def test_inspect_external_coding_session() -> None:
    expected = {"codingSessionId": "ecs_001", "status": "plan_ready"}
    mock = _mock_service_response("refresh_session", expected)
    with patch(
        "src.business.agents.tools.external_coding_tools.ExternalCodingSessionService",
        return_value=mock,
    ):
        tools = _tools()
        result = tools["inspect_external_coding_session"].handler(
            codingSessionId="ecs_001",
        )
    payload = json.loads(result)
    assert payload["codingSessionId"] == "ecs_001"
    mock.refresh_session.assert_called_once_with("ecs_001")
    mock.require_owner.assert_called_once_with("ecs_001", owner_type="task", owner_id="tsk_bound")
    assert tools["inspect_external_coding_session"].has_side_effects is True


def test_session_actions_fail_closed_without_bound_owner() -> None:
    tools = _tools(bound_task_id=None)

    result = tools["inspect_external_coding_session"].handler(codingSessionId="ecs_001")

    payload = json.loads(result)
    assert payload["success"] is False
    assert "bound task" in payload["message"]


def test_confirm_external_coding_rollback_requires_user_for_reset_hard() -> None:
    """reset_hard strategy must be confirmed by user, not agent."""
    mock = _mock_service_response("confirm_rollback")
    mock.confirm_rollback.side_effect = ValueError("reset_hard rollback requires user confirmation")
    with patch(
        "src.business.agents.tools.external_coding_tools.ExternalCodingSessionService",
        return_value=mock,
    ):
        tools = _tools()
        result = tools["confirm_external_coding_rollback"].handler(
            codingSessionId="ecs_001",
            rollbackId="ecr_001",
            confirmedBy="agent",
        )
    payload = json.loads(result)
    assert payload["success"] is False


def test_merge_analysis_tool_is_declared_side_effecting() -> None:
    assert _tools()["analyze_external_coding_merge"].has_side_effects is True


@pytest.mark.parametrize(
    ("phase", "external_session_ref"),
    [
        (CodingPhase.PLAN, None),
        (CodingPhase.IMPLEMENT, None),
        (CodingPhase.IMPLEMENT, "existing-session"),
    ],
    ids=["plan", "implement", "resume"],
)
def test_external_cli_commands_deliver_the_prompt_file_instruction(
    tmp_path: Path,
    phase: CodingPhase,
    external_session_ref: str | None,
) -> None:
    adapter = CliExternalCodingAdapter(config=_CommandConfig())
    prompt_path = tmp_path / f"{phase.value}-prompt.md"

    codex = adapter._build_command(
        ExternalCodingTool.CODEX_CLI,
        phase,
        prompt_path,
        external_session_ref=external_session_ref,
    )
    claude = adapter._build_command(
        ExternalCodingTool.CLAUDE_CODE,
        phase,
        prompt_path,
        external_session_ref=external_session_ref,
    )

    codex_instruction = codex[-1]
    assert not codex_instruction.startswith("@")
    assert codex_instruction.startswith(f"Follow the instructions in this file: {prompt_path}.")
    assert "complete requested phase artifact" in codex_instruction
    assert f"@{prompt_path}" in claude

"""Proposal source inspector evidence package tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.business.agents.config import AgentType
from src.business.orchestration.agent.tool_registry import ToolRegistry
from src.business.self_improvement.proposal_service import ProposalService
from src.business.self_improvement.proposal_source_inspector import (
    ProposalSourceForbidden,
    ProposalSourceInspector,
)
from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager
from src.data.models_sqlite import Message, Session
from src.data.repos.execution_review_repository import ExecutionReviewRepository
from src.data.repos.improvement_proposal_repository import ImprovementProposalRepository
from src.data.repos.tool_output_repository import ToolOutputRepository
from src.data.repositories import MessageRepository, SessionRepository


_FINDING = {
    "type": "效率",
    "what": "重复抓取同一 URL",
    "evidence": "两次读取同一页面",
    "severity": "med",
    "suggestion": "增加请求级缓存",
    "worth_changing": True,
}


def _seed_source() -> tuple[str, str, str]:
    source_session_id = "ast_source_session"
    SessionRepository().create(
        Session(
            session_id=source_session_id,
            agent_type=AgentType.ASSISTANT.value,
            status="active",
            title="来源会话",
        )
    )
    messages = MessageRepository()
    messages.create(
        Message(
            message_id="msg_user_1",
            session_id=source_session_id,
            sequence=1,
            role="user",
            content="请分析这个页面，后面可能会重复抓取同一 URL。",
        )
    )
    messages.create(
        Message(
            message_id="msg_assistant_2",
            session_id=source_session_id,
            sequence=2,
            role="assistant",
            content="我会检查页面，并留意重复抓取。",
            tool_calls=json.dumps(
                [{"id": "call_1", "function": {"name": "read_file", "arguments": "{\"path\":\"a\"}"}}],
                ensure_ascii=False,
            ),
        )
    )
    messages.create(
        Message(
            message_id="msg_tool_3",
            session_id=source_session_id,
            sequence=3,
            role="tool",
            tool_name="read_file",
            content=json.dumps({"outcome": "success", "limits": {"visibleChars": 2400}}),
        )
    )

    with ExecutionReviewRepository() as repo:
        review_id = repo.enqueue(source_session_id)
        repo.save_result(review_id, "发现重复抓取风险", [_FINDING], "test-model")

    with ImprovementProposalRepository() as repo:
        row = repo.create(
            source_review_id=review_id,
            finding_index=0,
            severity="med",
            finding_type="效率",
            what=_FINDING["what"],
            evidence=_FINDING["evidence"],
            suggestion=_FINDING["suggestion"],
        )
        assert row is not None
        return row.id, review_id, source_session_id


class _DynamicManagerCache:
    def get_or_create_dynamic_manager(self, session_id, allowed_ids, allowed_composition_ids=None):
        return DynamicToolManager(
            allowed_tool_ids=allowed_ids,
            allowed_composition_ids=allowed_composition_ids,
        )


def _tool_registry() -> ToolRegistry:
    return ToolRegistry(
        session_store=SimpleNamespace(get_session=lambda _session_id: None),
        dynamic_manager_cache=_DynamicManagerCache(),
        delegation_orchestrator=SimpleNamespace(
            delegate_to_subagent=lambda **_: {},
            continue_subagent=lambda **_: {},
            inspect_subagent=lambda **_: {},
            delegate_to_specialist=lambda **_: {},
            run_sync_ephemeral_subagent=lambda **_: {},
        ),
        resolve_recording_mode=lambda _workflow_id: "browser",
        redispatch_answered_task=lambda _task_id: False,
    )


def _tool_names(factory) -> set[str]:
    return {tool.name for tool in factory()}


def test_overview_returns_deterministic_source_package(in_memory_db):
    proposal_id, review_id, source_session_id = _seed_source()

    package = ProposalSourceInspector().inspect(proposal_id, view="overview")

    assert package["proposalId"] == proposal_id
    assert package["source"]["sourceReviewId"] == review_id
    assert package["source"]["turnSessionId"] == source_session_id
    assert package["review"]["verdict"] == "发现重复抓取风险"
    assert package["review"]["findingCount"] == 1
    assert any(item["kind"] == "review_finding" for item in package["evidence"])
    assert any(item["anchor"].get("sequence") == 1 for item in package["evidence"])


def test_messages_view_paginates_and_truncates_tool_preview(in_memory_db):
    proposal_id, _, _ = _seed_source()

    first = ProposalSourceInspector().inspect(proposal_id, view="messages", limit=2)
    second = ProposalSourceInspector().inspect(
        proposal_id,
        view="messages",
        cursor=first["page"]["nextCursor"],
        limit=2,
    )

    assert [item["sequence"] for item in first["items"]] == [1, 2]
    assert first["page"]["hasMore"] is True
    assert [item["sequence"] for item in second["items"]] == [3]
    assert second["items"][0]["role"] == "tool"
    assert len(second["items"][0]["excerpt"]) <= 500


def test_prompt_view_rebuilds_review_prompt_and_payload(in_memory_db):
    proposal_id, _, _ = _seed_source()

    package = ProposalSourceInspector().inspect(proposal_id, view="prompt")

    assert package["view"] == "prompt"
    assert "独立的执行复盘审查员" in package["prompt"]["system"]
    assert "read_file" in package["prompt"]["userPayload"]
    assert package["prompt"]["tools"][0]["name"] == "load_tool_output"


def test_timeline_view_pairs_tool_calls_and_results(in_memory_db):
    proposal_id, _, _ = _seed_source()

    package = ProposalSourceInspector().inspect(proposal_id, view="timeline")

    assert package["view"] == "timeline"
    assert any(item["type"] == "tool_call" and item["toolName"] == "read_file" for item in package["timeline"])
    assert any(item["type"] == "tool_result" and item["resultSize"] == 2400 for item in package["timeline"])


def test_tool_output_view_loads_only_referenced_source_output(in_memory_db):
    proposal_id, _, source_session_id = _seed_source()
    model = ToolOutputRepository().create_reference(
        session_id=source_session_id,
        tool_name="read_file",
        tool_call_id="call_1",
        kind="text",
        data="alpha\nbeta\ngamma",
        workspace_root=None,
        content_type="text/plain",
    )
    MessageRepository().update_content(
        "msg_tool_3",
        json.dumps(
            {
                "outcome": "success",
                "limits": {"visibleChars": 2400},
                "references": [{"referenceId": model.reference_id}],
            },
            ensure_ascii=False,
        ),
    )

    package = ProposalSourceInspector().inspect(
        proposal_id,
        view="tool_output",
        reference_id=model.reference_id,
        max_bytes=8,
    )

    assert package["view"] == "tool_output"
    assert package["reference"]["referenceId"] == model.reference_id
    assert package["content"] == "alpha\nbe"
    assert package["page"]["hasMore"] is True
    assert package["page"]["nextOffset"] == 8


def test_discussion_permission_is_enforced(in_memory_db):
    proposal_id, _, _ = _seed_source()
    discussion = ProposalService().get_or_create_discussion_session(proposal_id)

    allowed = ProposalSourceInspector().inspect(
        None,
        view="overview",
        discussion_session_id=discussion["sessionId"],
        enforce_discussion=True,
    )
    assert allowed["proposalId"] == proposal_id

    with pytest.raises(ProposalSourceForbidden):
        ProposalSourceInspector().inspect(
            proposal_id,
            view="overview",
            discussion_session_id="ast_wrong_session",
            enforce_discussion=True,
        )


def test_inspect_tool_only_visible_for_bound_discussion_session(in_memory_db):
    proposal_id, _, _ = _seed_source()
    discussion = ProposalService().get_or_create_discussion_session(proposal_id)
    registry = _tool_registry()

    assert "inspect_proposal_source" not in _tool_names(registry.build_assistant_tools("ast_plain"))
    assert "inspect_proposal_source" in _tool_names(
        registry.build_assistant_tools(discussion["sessionId"])
    )

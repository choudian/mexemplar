"""014 US3/US4: 助理过程只读读模型（observability）行为契约。"""

import json
import uuid

import pytest

from src.business.agents.config import AgentType
from src.business.agents.observability import AssistantObservability
from src.business.memory.context_manager import ContextManager


def _new_session(agent_type: AgentType, workflow_id: str | None = None) -> str:
    from src.business.orchestration.agent.agent_session_store import AgentSessionStore
    from src.data.repositories import (
        MessageRepository,
        SessionRepository,
        WorkflowTransitionRepository,
    )

    store = AgentSessionStore(
        session_repo=SessionRepository(),
        message_repo=MessageRepository(),
        transition_repo=WorkflowTransitionRepository(),
    )
    return store.create_session(workflow_id or f"wf-{uuid.uuid4().hex[:8]}", agent_type)


def test_build_transcript_reconstructs_steps_excluding_final_reply(mock_config, in_memory_db):
    sid = _new_session(AgentType.ASSISTANT)
    ctx = ContextManager(sid, mock_config)
    ctx.save_message(role="system", content="sys")
    ctx.save_user_message("做事")
    ctx.save_assistant_message(
        content="我想想", tool_calls=json.dumps([{"id": "c1", "name": "noop", "args": {"q": "x"}}])
    )
    ctx.save_tool_result(tool_call_id="c1", tool_name="noop", content="结果OK")
    ctx.save_assistant_message(content="完成回复", tool_calls=None)

    result = AssistantObservability().build_transcript(sid)
    kinds = [(s.kind, s.tool_name) for s in result.steps]
    assert ("reasoning", None) in kinds
    assert ("tool_call", "noop") in kinds
    assert ("tool_result", "noop") in kinds
    assert result.compressed is False
    # 最终无工具调用的回复不进时间线
    assert all("完成回复" not in s.text for s in result.steps)


def test_build_transcript_flags_sensitive_json_tool_payloads(mock_config, in_memory_db):
    sid = _new_session(AgentType.ASSISTANT)
    ctx = ContextManager(sid, mock_config)
    ctx.save_message(role="system", content="sys")
    ctx.save_user_message("做事")
    ctx.save_assistant_message(
        content="",
        tool_calls=json.dumps(
            [
                {
                    "id": "c1",
                    "name": "noop",
                    "args": {"api_key": "sk-secret-12345", "query": "hello"},
                }
            ]
        ),
    )
    ctx.save_tool_result(
        tool_call_id="c1",
        tool_name="noop",
        content=json.dumps({"password": "pw-secret", "ok": True}),
    )

    result = AssistantObservability().build_transcript(sid)

    by_kind = {step.kind: step for step in result.steps}
    # 方案 B：保留原文 + 标记 redacted（UI 默认隐藏、双击查看）
    assert by_kind["tool_call"].redacted is True
    assert by_kind["tool_result"].redacted is True
    assert "sk-secret" in by_kind["tool_call"].text
    assert "pw-secret" in by_kind["tool_result"].text


def test_build_transcript_flags_compressed_history(mock_config, in_memory_db):
    sid = _new_session(AgentType.ASSISTANT)
    ctx = ContextManager(sid, mock_config)
    ctx.save_message(role="system", content="sys")
    ctx.save_message(role="summary", content="之前的对话内容（已压缩概要）")
    result = AssistantObservability().build_transcript(sid)
    assert result.compressed is True


def test_subagent_read_model_propagates_repository_failures():
    class BrokenTransitionRepo:
        def list_by_session(self, parent_session_id: str):
            raise RuntimeError("repository unavailable")

    observability = AssistantObservability(transition_repo=BrokenTransitionRepo())

    with pytest.raises(RuntimeError, match="repository unavailable"):
        observability.build_subagent_list("parent")
    with pytest.raises(RuntimeError, match="repository unavailable"):
        observability.count_subagent_return_transitions("parent", "child")


def test_build_subagent_list_from_transitions_and_session_status(mock_config, in_memory_db):
    from src.business.orchestration.agent.agent_session_store import AgentSessionStore
    from src.data.repositories import (
        MessageRepository,
        SessionRepository,
        WorkflowTransitionRepository,
    )

    store = AgentSessionStore(
        session_repo=SessionRepository(),
        message_repo=MessageRepository(),
        transition_repo=WorkflowTransitionRepository(),
    )
    parent = store.create_session("wf-parent", AgentType.ASSISTANT)
    child = store.create_session("dlg_x", AgentType.EPHEMERAL_SUBAGENT)
    cctx = ContextManager(child, mock_config)
    cctx.save_user_message("主助理委派给你的任务如下：\n\n检索报表")
    cctx.save_assistant_message(content="已完成检索，结果如下", tool_calls=None)
    cctx.update_session_status("suspended")
    store.record_transition(
        "dlg_x",
        event_type="assistant_delegation_started",
        from_session_id=parent,
        to_session_id=child,
        payload=json.dumps({"agent_type": "ephemeral_subagent"}, ensure_ascii=False),
    )

    items = AssistantObservability().build_subagent_list(parent)
    assert len(items) == 1
    assert items[0].subagent_id == child
    assert items[0].status == "suspended"  # 子会话权威状态
    assert items[0].label == "子助手"
    assert "检索报表" in items[0].task
    assert items[0].last_output and "已完成检索" in items[0].last_output  # 批量重建最后产出


def test_continue_subagent_started_uses_return_transition_count():
    """续跑判定下沉到读模型：返回标记超过基线即视为已发生（不再由适配层重派生）。"""

    class _Tr:
        def __init__(self, event_type: str) -> None:
            self.event_type = event_type
            self.from_session_id = "child"
            self.to_session_id = "parent"

    class FakeTransitionRepo:
        def list_by_session(self, parent_session_id: str):
            return [_Tr("assistant_delegation_resumed")]

    class FakeMessageRepo:
        def get_all(self, session_id: str):
            return []

        def get_first_user_messages(self, session_ids):
            return {}

        def get_latest_assistant_texts(self, session_ids):
            return {}

    class FakeSessionRepo:
        def get_by_ids(self, session_ids):
            return []

    observability = AssistantObservability(
        message_repo=FakeMessageRepo(),
        session_repo=FakeSessionRepo(),
        transition_repo=FakeTransitionRepo(),
    )
    # 基线为 0、现有 1 条返回标记 → 已发生
    assert observability.continue_subagent_started("parent", "child", 0) is True
    # 基线已等于当前标记数、且无委派 started 记录（summary 缺失）→ 未发生
    assert observability.continue_subagent_started("parent", "child", 1) is False

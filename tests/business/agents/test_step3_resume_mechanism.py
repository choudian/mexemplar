"""③ 第一阶段：续跑机制本身做对（修变身+扩权）的行为测试。

续跑从"调 continue_subagent（变身+扩权）"改成"走 _run_specialist/_run_ephemeral
+ resume_session_id"。第一阶段不改任何触发者，只修机制本身。
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.config import AgentResult, AgentType, ResultType
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.business.orchestration.agent.task_executor_adapter import (
    TaskExecutorAdapter,
    _resume_info_from_checkpoint,
)
from src.data.models_sqlite import Message, Session as SessionModel
from src.data.repos import (
    AssistantTaskAttemptRepository,
    AssistantTaskRepository,
    MessageRepository,
    SessionRepository,
)
from src.data.repos.base_repository import generate_id
from src.utils.timezone import utc_now_naive


@pytest.fixture
def orch(mock_config, in_memory_db):
    """Orchestrator with mocked LLM client + config."""
    return AgentOrchestrator(MagicMock(), mock_config)


def _patch_loop(orch):
    """Mock AgentLoop + tool building so _run_delegated_executor runs without LLM."""
    patches = [
        patch("src.business.orchestration.agent.orchestrator.AgentLoop"),
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
        patch.object(orch, "_record_delegation_signal"),
    ]
    started = [p.start() for p in patches]
    loop_cls = started[0]
    loop_cls.return_value.run.return_value = AgentResult(result_type=ResultType.COMPLETED)
    return patches, loop_cls


def _seed_session(session_id: str, *, agent_type: str = "ephemeral_subagent") -> str:
    """Create a session row for resume reuse."""
    SessionRepository().create(
        SessionModel(
            session_id=session_id,
            workflow_id=f"dlg_test_{session_id}",
            agent_type=agent_type,
            status="suspended",
        )
    )
    return session_id


# ---------------------------------------------------------------------------
# Checkpoint parser
# ---------------------------------------------------------------------------


class TestResumeInfoFromCheckpoint:
    def test_parses_session_id_and_budget(self):
        info = _resume_info_from_checkpoint(
            json.dumps({"subagent_id": "sess_abc", "iteration_budget": 20})
        )
        assert info == {"session_id": "sess_abc", "iteration_budget": 20}

    def test_parses_executor_session_id_key(self):
        info = _resume_info_from_checkpoint(
            json.dumps({"executor_session_id": "sess_xyz"})
        )
        assert info == {"session_id": "sess_xyz", "iteration_budget": None}

    def test_none_for_empty(self):
        assert _resume_info_from_checkpoint(None) is None
        assert _resume_info_from_checkpoint("") is None

    def test_none_for_non_json(self):
        assert _resume_info_from_checkpoint("not json") is None

    def test_none_for_no_session_key(self):
        assert _resume_info_from_checkpoint(json.dumps({"foo": "bar"})) is None

    def test_budget_none_for_invalid(self):
        info = _resume_info_from_checkpoint(
            json.dumps({"subagent_id": "s", "iteration_budget": "not_a_number"})
        )
        assert info == {"session_id": "s", "iteration_budget": None}


# ---------------------------------------------------------------------------
# resume_session_id 复用会话（不变身）
# ---------------------------------------------------------------------------


class TestResumeReusesSession:
    def test_resume_does_not_create_new_session(self, orch):
        """续跑时传入 resume_session_id → 复用已有会话，不建新会话。"""
        resume_sid = "sess_resume_test"
        _seed_session(resume_sid)
        patches, _ = _patch_loop(orch)
        try:
            result = orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                parent_session_id="ast_parent",
                task="续跑",
                resume_session_id=resume_sid,
            )
        finally:
            for p in patches:
                p.stop()

        assert result["executor_session_id"] == resume_sid

    def test_no_resume_creates_new_session(self, orch):
        """无 resume_session_id → 建新会话（现有行为不变）。"""
        patches, _ = _patch_loop(orch)
        try:
            result = orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                parent_session_id="ast_parent",
                task="首次",
            )
        finally:
            for p in patches:
                p.stop()

        # 新建的 session_id 不应等于任何已存在的
        assert result["executor_session_id"]
        assert result["executor_session_id"] != "ast_parent"

    def test_resume_nonexistent_session_returns_failure(self, orch):
        """resume_session_id 不存在 → 返回明确失败，不静默开新会话。"""
        patches, _ = _patch_loop(orch)
        try:
            result = orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                parent_session_id="ast_parent",
                task="续跑",
                resume_session_id="sess_does_not_exist",
            )
        finally:
            for p in patches:
                p.stop()

        assert result["success"] is False
        assert "不存在" in result["message"]


# ---------------------------------------------------------------------------
# iteration_budget 追加轮数
# ---------------------------------------------------------------------------


class TestIterationBudget:
    def test_iteration_budget_passed_to_get_loop(self, orch):
        """iteration_budget 透传到 _get_loop，max_iterations = 默认 + budget。"""
        resume_sid = "sess_budget_test"
        _seed_session(resume_sid)
        patches, loop_cls = _patch_loop(orch)
        try:
            orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                parent_session_id="ast_parent",
                task="加预算续跑",
                resume_session_id=resume_sid,
                iteration_budget=20,
            )
        finally:
            for p in patches:
                p.stop()

        # AgentLoop(config, llm, unified_config) — 检查 config.max_iterations
        config_arg = loop_cls.call_args[0][0]
        assert config_arg.max_iterations == 70  # 50 (ephemeral default) + 20

    def test_no_budget_uses_default(self, orch):
        """无 iteration_budget → max_iterations = 默认值。"""
        patches, loop_cls = _patch_loop(orch)
        try:
            orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                parent_session_id="ast_parent",
                task="默认",
            )
        finally:
            for p in patches:
                p.stop()

        config_arg = loop_cls.call_args[0][0]
        assert config_arg.max_iterations == 50  # ephemeral default


# ---------------------------------------------------------------------------
# 水位线：交付物只取 baseline 之后
# ---------------------------------------------------------------------------


class TestBaselineWatermark:
    def test_extract_uses_after_sequence(self, orch):
        """_extract_latest_assistant_text 传 after_sequence=baseline。"""
        session_id = "sess_watermark"
        _seed_session(session_id)

        patches, _ = _patch_loop(orch)
        # Mock message_repo 来追踪 after_sequence 参数
        with patch.object(
            orch._message_repo,
            "get_latest_assistant_text",
            return_value="本轮的输出",
        ) as mock_extract:
            with patch.object(
                orch._message_repo, "get_next_sequence", return_value=10
            ):
                try:
                    orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                        parent_session_id="ast_parent",
                        task="水位线测试",
                    )
                finally:
                    for p in patches:
                        p.stop()

            # 验证 get_latest_assistant_text 被调时传了 after_sequence=9（get_next_sequence-1）
            mock_extract.assert_called_once()
            call_kwargs = mock_extract.call_args
            assert call_kwargs[1].get("after_sequence") == 9


# ---------------------------------------------------------------------------
# _continue_subagent 仍可调用（契约门卫：第一阶段没误伤主助理工具路径）
# ---------------------------------------------------------------------------


class TestContinueSubagentStillCallable:
    def test_continue_subagent_method_exists_and_runs(self, orch):
        """_continue_subagent 仍可被调用——第一阶段没断主助理 continue_subagent 工具路径。"""
        assert hasattr(orch, "_continue_subagent")
        # 调一个不存在的 subagent，验证它返回失败 dict（不抛异常、不崩）
        result = orch._continue_subagent(
            parent_session_id="ast_parent",
            subagent_id="sess_nonexistent_for_continue",
        )
        assert isinstance(result, dict)
        assert result.get("success") is False


# ---------------------------------------------------------------------------
# TaskExecutorAdapter：__call__ 解析 checkpoint 并传 resume_session_id
# ---------------------------------------------------------------------------


class TestTaskExecutorAdapterResume:
    def test_call_with_checkpoint_passes_resume_session_id(self, orch):
        """__call__ 从 checkpoint_ref 解析出 resume_session_id 并传给 _run_ephemeral。"""
        task_id = generate_id("tsk")
        attempt_id = generate_id("att")
        resume_sid = "sess_adapter_resume"
        checkpoint_ref = json.dumps(
            {"subagent_id": resume_sid, "iteration_budget": 15}
        )

        AssistantTaskRepository().create_task(
            graph_id="tg_adapter",
            session_id="ast_adapter",
            task_id=task_id,
            title="adapter test",
            description="d",
            owner_session_id="ast_adapter",
            status="running",
            assignee_type="ephemeral_subagent",
        )
        AssistantTaskAttemptRepository().start_attempt(
            task_id=task_id,
            executor_type="ephemeral_subagent",
            executor_id=task_id,
            lease_owner="test",
            lease_expires_at=utc_now_naive() + timedelta(hours=1),
            attempt_id=attempt_id,
            checkpoint_ref=checkpoint_ref,
        )

        adapter = TaskExecutorAdapter(orch)
        captured = {}

        def _capture_run(self_adapter, orchestrator, task, parent, whitelist, **kw):
            captured["resume_session_id"] = kw.get("resume_session_id")
            captured["iteration_budget"] = kw.get("iteration_budget")
            return {"success": True, "result_text": "done", "executor_session_id": resume_sid}

        with patch.object(TaskExecutorAdapter, "_run_ephemeral", _capture_run):
            outcome = adapter(attempt_id)

        assert captured["resume_session_id"] == resume_sid
        assert captured["iteration_budget"] == 15
        assert outcome.get("safe_summary")


# ---------------------------------------------------------------------------
# Review Finding 1（硬）：旧路径删除门卫（Constitution IV）
# ---------------------------------------------------------------------------


class TestOldResumePathRemoved:
    """Constitution IV：架构接线替换 MUST 有门卫测试证明旧路径已移除。"""

    def test_try_resume_from_checkpoint_method_deleted(self):
        """_try_resume_from_checkpoint 已从 TaskExecutorAdapter 物理删除。"""
        assert not hasattr(TaskExecutorAdapter, "_try_resume_from_checkpoint")

    def test_call_does_not_dispatch_to_continue_subagent(self, orch):
        """__call__ 不再走 continue_subagent（变身扩权旧路径）。

        即便 checkpoint_ref 里有 subagent_id，__call__ 也应走 _run_ephemeral/_run_specialist，
        不碰 continue_subagent。
        """
        task_id = generate_id("tsk")
        attempt_id = generate_id("att")
        checkpoint_ref = json.dumps({"subagent_id": "sess_old_path"})

        AssistantTaskRepository().create_task(
            graph_id="tg_old_path",
            session_id="ast_old",
            task_id=task_id,
            title="old path guard",
            description="d",
            owner_session_id="ast_old",
            status="running",
            assignee_type="ephemeral_subagent",
        )
        AssistantTaskAttemptRepository().start_attempt(
            task_id=task_id,
            executor_type="ephemeral_subagent",
            executor_id=task_id,
            lease_owner="test",
            lease_expires_at=utc_now_naive() + timedelta(hours=1),
            attempt_id=attempt_id,
            checkpoint_ref=checkpoint_ref,
        )

        adapter = TaskExecutorAdapter(orch)

        # Spy on continue_subagent — 如果被调，证明旧路径还活着。
        with patch.object(
            orch.delegation_orchestrator,
            "continue_subagent",
            side_effect=AssertionError("continue_subagent should not be called"),
        ):
            with patch.object(
                TaskExecutorAdapter,
                "_run_ephemeral",
                return_value={"success": True, "result_text": "ok"},
            ):
                adapter(attempt_id)


# ---------------------------------------------------------------------------
# Review Finding 2：workflow_id 复用断言（spec §1.1 line 73）
# ---------------------------------------------------------------------------


class TestWorkflowIdReuse:
    def test_resume_reuses_original_workflow_id(self, orch):
        """续跑时 workflow_id 从被复用的 session 记录读出，不新生成。"""
        resume_sid = "sess_wf_reuse"
        original_workflow_id = "dlg_original_wf_001"
        SessionRepository().create(
            SessionModel(
                session_id=resume_sid,
                workflow_id=original_workflow_id,
                agent_type="ephemeral_subagent",
                status="suspended",
            )
        )
        patches, _ = _patch_loop(orch)
        try:
            result = orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                parent_session_id="ast_parent",
                task="续跑",
                resume_session_id=resume_sid,
            )
        finally:
            for p in patches:
                p.stop()

        assert result["workflow_id"] == original_workflow_id


# ---------------------------------------------------------------------------
# Review Finding 3：身份/工具不变量（spec 验收表 122-123）
# ---------------------------------------------------------------------------


class TestIdentityAndToolInvariance:
    def test_resume_preserves_agent_type_for_specialist(self, orch):
        """专员续跑后 agent_type 仍是 SPECIALIST（不变身成 EPHEMERAL）。"""
        resume_sid = "sess_specialist_identity"
        SessionRepository().create(
            SessionModel(
                session_id=resume_sid,
                workflow_id="dlg_identity",
                agent_type="specialist",
                status="suspended",
            )
        )
        patches, loop_cls = _patch_loop(orch)
        # Specialist path needs equipped-skills snapshot + prompt builder mocked
        patches.append(patch.object(orch, "_specialist_equipped_skills_snapshot", return_value=[]))
        patches[-1].start()
        patches.append(patch.object(orch, "_build_specialist_prompt", return_value="spec prompt"))
        patches[-1].start()
        # Also mock _extract_methodology_equipment_snapshot to avoid prompt parsing
        patches.append(patch.object(orch, "_extract_methodology_equipment_snapshot", return_value=""))
        try:
            orch.delegation_orchestrator.run_specialist_via_delegated_executor(
                parent_session_id="ast_parent",
                specialist=MagicMock(
                    specialist_id="sp_test",
                    tool_whitelist="[]",
                    composition_ids="[]",
                    role_kind="executor",
                    is_active=1,
                ),
                task="专员续跑",
                resume_session_id=resume_sid,
            )
        finally:
            for p in patches:
                p.stop()

        config_arg = loop_cls.call_args[0][0]
        assert config_arg.agent_type == AgentType.SPECIALIST

    def test_resume_preserves_agent_type_for_ephemeral(self, orch):
        """临时子代理续跑后 agent_type 仍是 EPHEMERAL_SUBAGENT。"""
        resume_sid = "sess_ephemeral_identity"
        _seed_session(resume_sid)
        patches, loop_cls = _patch_loop(orch)
        try:
            orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                parent_session_id="ast_parent",
                task="临时续跑",
                resume_session_id=resume_sid,
            )
        finally:
            for p in patches:
                p.stop()

        config_arg = loop_cls.call_args[0][0]
        assert config_arg.agent_type == AgentType.EPHEMERAL_SUBAGENT

    def test_resume_preserves_tool_whitelist(self, orch):
        """续跑时 tool_whitelist 仍从调用方传入（不退化成 None/全池）。

        _resolve_user_tool_ids 被 patch 成返回空集，但关键在于调用它时传的
        tool_whitelist 参数值——续跑和首次执行应传同一个值。
        """
        resume_sid = "sess_whitelist"
        _seed_session(resume_sid)
        captured_whitelists = []

        patches, _ = _patch_loop(orch)
        # _patch_loop already patches _resolve_user_tool_ids to return set().
        # Override it AFTER _patch_loop to capture the tool_whitelist argument.
        capture_patch = patch.object(
            orch,
            "_resolve_user_tool_ids",
            lambda parent_session_id=None, tool_whitelist=None: (
                captured_whitelists.append(tool_whitelist) or set()
            ),
        )
        capture_patch.start()
        patches.append(capture_patch)
        try:
            orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                parent_session_id="ast_parent",
                task="工具集不变",
                tool_whitelist=["read_file", "search_content"],
                resume_session_id=resume_sid,
            )
        finally:
            for p in patches:
                p.stop()

        # 续跑时传入的 tool_whitelist 应与调用方指定的一致（不被 None 替代）
        assert ["read_file", "search_content"] in captured_whitelists


# ---------------------------------------------------------------------------
# Review Finding 4：水位线真实排除测试（seed 水位线前消息，断言被排除）
# ---------------------------------------------------------------------------


class TestWatermarkExclusion:
    def test_pre_watermark_messages_excluded_from_result(self, orch):
        """水位线之前的 assistant 消息不进入本轮交付物。

        seed 一条 'role=assistant, content=上一轮' 的消息（sequence=1），
        mock get_next_sequence 返回 2（baseline=1），然后 mock
        get_latest_assistant_text 验证 after_sequence=1 被传入——
        意味着 sequence=1 的旧消息被排除。
        """
        session_id = "sess_watermark_exclude"
        _seed_session(session_id)
        # Seed 一条真实的 assistant 消息（模拟上一轮产物）
        with MessageRepository() as repo:
            repo.create(
                Message(
                    message_id="msg_old",
                    session_id=session_id,
                    sequence=1,
                    role="assistant",
                    content="上一轮的输出，不应被取到",
                )
            )

        patches, _ = _patch_loop(orch)
        with patch.object(
            orch._message_repo, "get_next_sequence", return_value=2
        ):
            with patch.object(
                orch._message_repo,
                "get_latest_assistant_text",
                return_value="本轮的输出",
            ) as mock_extract:
                try:
                    orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                        parent_session_id="ast_parent",
                        task="水位线排除",
                    )
                finally:
                    for p in patches:
                        p.stop()

                # after_sequence=1（baseline = get_next_sequence-1 = 1）
                # sequence > 1 会排除 seed 的 sequence=1 旧消息
                mock_extract.assert_called_once()
                assert mock_extract.call_args[1].get("after_sequence") == 1

    def test_real_message_after_watermark_returned(self, orch):
        """水位线之后的真实 assistant 消息能被取到（端到端验证，不全 mock）。

        用 resume_session_id 复用带历史消息的会话。seed 两条 assistant 消息：
        sequence=1（旧）、sequence=3（新）。mock get_next_sequence 返回 2（baseline=1），
        不 mock get_latest_assistant_text，验证真实查询返回 sequence=3 的消息、排除 sequence=1。
        """
        session_id = "sess_watermark_real"
        _seed_session(session_id)
        with MessageRepository() as repo:
            repo.create(
                Message(
                    message_id="msg_old_real",
                    session_id=session_id,
                    sequence=1,
                    role="assistant",
                    content="旧消息",
                )
            )
            repo.create(
                Message(
                    message_id="msg_new_real",
                    session_id=session_id,
                    sequence=3,
                    role="assistant",
                    content="新消息",
                )
            )

        patches, _ = _patch_loop(orch)
        with patch.object(orch._message_repo, "get_next_sequence", return_value=2):
            try:
                result = orch.delegation_orchestrator.run_ephemeral_via_delegated_executor(
                    parent_session_id="ast_parent",
                    task="真实水位线",
                    resume_session_id=session_id,
                )
            finally:
                for p in patches:
                    p.stop()

        # 交付物应是"新消息"（sequence=3 > baseline=1），不是"旧消息"（sequence=1）
        assert result.get("result_text") == "新消息"

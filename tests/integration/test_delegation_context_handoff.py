"""
032 T008/T009/T010: 委派上下文交接链路集成测试。

- T008 同步链路:handler(带下标) → DelegationOrchestrator.delegate_to_subagent(simple)
  → run_ephemeral_via_delegated_executor → 执行体 user_input 含"补充上下文"段与
  展开块原文(逐字);执行体工具面不暴露 context_message_indexes。
- T009 异步链路:complex 委派落库的 task.description 已是展开全文,无下标残留。
- T010 快照消亡:落库任务脱离委派轮(无快照 contextvar)经 TaskExecutorAdapter
  执行,执行体输入仍含全文。
"""

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.config import AgentType
from src.business.agents.delegation_context import (
    EXPANDED_CONTEXT_HEADER,
    EXPANDED_CONTEXT_PROVENANCE_MARKER,
    get_llm_messages_snapshot,
    use_llm_messages_snapshot,
)
from src.business.orchestration.agent.orchestrator import AgentOrchestrator

PLAN_TEXT = "方案全文：第一步准备环境…第二步部署服务…第三步验证回滚…"

SNAPSHOT = [
    {"role": "system", "content": "你是助理。"},
    {"role": "user", "content": "给我出一个部署方案"},
    {"role": "assistant", "content": PLAN_TEXT},
    {"role": "user", "content": "把这个方案写到 docs/plan.md"},
]


def _patch_max_chars(value: int = 30000):
    config = MagicMock()
    config.get_agent_tools_delegation_context_expansion_max_chars.return_value = value
    return patch(
        "src.business.agents.delegation_context.get_unified_config",
        return_value=config,
    )


@pytest.fixture
def orch(mock_config, in_memory_db):
    return AgentOrchestrator(MagicMock(), mock_config)


@pytest.fixture(autouse=True)
def _bypass_user_task_validation(monkeypatch):
    """这些测试验证委派上下文透传，不关心 taskId 校验。"""
    monkeypatch.setattr(
        "src.business.orchestration.agent.delegation_orchestrator._validate_user_task_id",
        lambda _uid: None,
    )


def _parent_session(orch) -> str:
    return orch._session_store.create_session(f"wf-{uuid.uuid4().hex[:8]}", AgentType.ASSISTANT)


def _subagent_handler(orch, parent_sid):
    from src.business.agents.tools.assistant_tools import (
        create_delegate_to_subagent_handler,
    )

    return create_delegate_to_subagent_handler(
        parent_sid,
        dispatch_callback=lambda **kw: orch.delegation_orchestrator.delegate_to_subagent(**kw),
    )


def _specialist_handler(orch, parent_sid):
    from src.business.agents.tools.assistant_tools import (
        create_delegate_to_specialist_handler,
    )

    return create_delegate_to_specialist_handler(
        parent_sid,
        dispatch_callback=lambda **kw: orch.delegation_orchestrator.delegate_to_specialist(**kw),
    )


class TestSyncChainCarriesExpandedContext:
    def test_executor_user_input_contains_plan_verbatim(self, orch):
        parent_sid = _parent_session(orch)
        captured: dict = {}

        def capture_executor(**kwargs):
            captured.update(kwargs)
            return {"success": True, "result_text": "done"}

        orch._run_delegated_executor = capture_executor
        handler = _subagent_handler(orch, parent_sid)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            result = handler(
                task_description="把方案写到 docs/plan.md",
                execution_context="目标路径 docs/plan.md",
                context_message_indexes=[3],
                complexity="simple",
            )

        assert json.loads(result)["success"] is True
        user_input = captured["user_input"]
        assert "补充上下文" in user_input
        assert EXPANDED_CONTEXT_HEADER in user_input
        assert PLAN_TEXT in user_input  # 逐字保真
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER not in user_input
        assert captured["agent_type"] == AgentType.EPHEMERAL_SUBAGENT

    def test_executor_preserves_exact_assistant_and_tool_message_content(self, orch):
        parent_sid = _parent_session(orch)
        captured: dict = {}
        assistant_content = "line  \nend\t "
        tool_content = '{"status":"ok"}\n  '
        snapshot = [
            {"role": "system", "content": "你是助理。"},
            {"role": "assistant", "content": assistant_content},
            {"role": "tool", "content": tool_content},
        ]

        def capture_executor(**kwargs):
            captured.update(kwargs)
            return {"success": True, "result_text": "done"}

        orch._run_delegated_executor = capture_executor
        handler = _subagent_handler(orch, parent_sid)

        with use_llm_messages_snapshot(snapshot), _patch_max_chars():
            result = handler(
                task_description="保存原文",
                context_message_indexes=[2, 3],
                complexity="simple",
            )

        assert json.loads(result)["success"] is True
        expected_block = (
            f"{EXPANDED_CONTEXT_HEADER}\n"
            f"--- 消息 #2（assistant）---\n{assistant_content}\n"
            f"--- 消息 #3（tool）---\n{tool_content}"
        )
        assert expected_block in captured["user_input"]
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER not in captured["user_input"]

    def test_invalid_index_fails_closed_without_child_session(self, orch):
        parent_sid = _parent_session(orch)
        executor = MagicMock()
        orch._run_delegated_executor = executor
        handler = _subagent_handler(orch, parent_sid)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            result = handler(
                task_description="写文件",
                context_message_indexes=[99],
                complexity="simple",
            )

        assert json.loads(result)["success"] is False
        executor.assert_not_called()

    def test_executor_toolset_does_not_expose_context_indexes_surface(self, orch):
        """执行体是纯接收方:其工具面不含 context_message_indexes 参数"""
        parent_sid = _parent_session(orch)
        factory = orch._build_delegated_executor_tools(
            None,
            agent_type=AgentType.EPHEMERAL_SUBAGENT.value,
            executor_id="exec-032",
            parent_session_id=parent_sid,
        )
        tools = factory()
        assert tools, "执行体工具集不应为空"
        for tool in tools:
            params = json.dumps(tool.schema, ensure_ascii=False)
            assert "context_message_indexes" not in params, tool.name

    def test_executor_cannot_load_parent_message_by_id(self, orch):
        """即使执行体拿到父消息 ID，load_reference 也必须按会话归属拒绝。"""
        from src.business.memory.context_manager import ContextManager

        parent_sid = _parent_session(orch)
        parent_context = ContextManager(parent_sid, orch._config)
        parent_message = parent_context.save_assistant_message("父会话方案原文")
        child_sid = orch._session_store.create_session(
            f"wf-{uuid.uuid4().hex[:8]}", AgentType.EPHEMERAL_SUBAGENT
        )
        child_context = ContextManager(child_sid, orch._config)

        assert parent_context.load_reference(parent_message.message_id) == "父会话方案原文"
        with pytest.raises(ValueError, match="不存在或无权访问"):
            child_context.load_reference(parent_message.message_id)

    def test_assistant_can_follow_message_reference_across_own_sessions(self, orch):
        """主助理保留既有跨会话摘要下钻到历史原始消息的能力。"""
        from src.business.memory.context_manager import ContextManager

        historical_sid = _parent_session(orch)
        current_sid = _parent_session(orch)
        historical_context = ContextManager(historical_sid, orch._config)
        historical_message = historical_context.save_assistant_message("历史会话方案原文")
        current_context = ContextManager(current_sid, orch._config)

        assert current_context.load_reference(historical_message.message_id) == "历史会话方案原文"


class _NoopCutoverGuard:
    def assert_can_dispatch(self) -> None:
        return None


class _DispatcherConfig:
    def get_assistant_tasks_dispatch_max_workers(self) -> int:
        return 2

    def get_assistant_tasks_attempt_lease_seconds(self) -> int:
        return 60

    def get_assistant_tasks_board_fallback_seconds(self) -> int:
        return 10

    def get_assistant_tasks_board_capacity(self) -> int:
        return 10

    def get_assistant_tasks_recruitment_min_fallback_count(self) -> int:
        return 1


class TestAsyncChainPersistsExpandedText:
    def _dispatch_complex(self, orch, parent_sid, monkeypatch) -> dict:
        # 打开统一任务派发门,并抑制后台 attempt 执行(测试只关心落库内容)
        from src.business.task_collaboration.dispatcher import TaskDispatcher

        orch._config.get_assistant_tasks_unified_dispatch_enabled.return_value = True
        monkeypatch.setattr(orch, "_start_unified_attempt", lambda *a, **kw: None)
        monkeypatch.setattr(
            "src.business.task_collaboration.dispatcher.get_unified_config",
            lambda: _DispatcherConfig(),
        )
        dispatcher = TaskDispatcher(cutover_guard=_NoopCutoverGuard())
        monkeypatch.setattr(orch, "_get_task_dispatcher", lambda: dispatcher)
        handler = _subagent_handler(orch, parent_sid)
        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            result = handler(
                task_description="把方案写到 docs/plan.md",
                execution_context="目标路径 docs/plan.md",
                context_message_indexes=[3],
                complexity="complex",
            )
        return json.loads(result)

    def test_task_description_persisted_as_expanded_fulltext(self, orch, monkeypatch):
        parent_sid = _parent_session(orch)
        data = self._dispatch_complex(orch, parent_sid, monkeypatch)
        assert data.get("accepted") is True, f"unified dispatch 未生效: {data}"

        task_id = data.get("taskId")
        assert task_id, f"缺少 taskId: {data}"

        from src.data.repos import AssistantTaskRepository

        with AssistantTaskRepository() as repo:
            task = repo.get_task(task_id)
        assert task is not None
        assert PLAN_TEXT in (task.description or "")
        assert "context_message_indexes" not in (task.description or "")
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER in (task.description or "")

    def test_executor_receives_fulltext_after_snapshot_gone(self, orch, monkeypatch):
        """快照消亡(进程重启等价)后经真 TaskExecutorAdapter 路径执行:输入仍含全文"""
        from src.business.orchestration.agent.task_executor_adapter import (
            TaskExecutorAdapter,
        )
        from src.data.repos import AssistantTaskRepository

        parent_sid = _parent_session(orch)
        data = self._dispatch_complex(orch, parent_sid, monkeypatch)
        task_id = data.get("taskId")
        assert task_id

        with AssistantTaskRepository() as repo:
            task = repo.get_task(task_id)

        # 委派轮已结束,快照不存在
        assert get_llm_messages_snapshot() is None

        captured: dict = {}

        def capture_executor(**kwargs):
            captured.update(kwargs)
            return {"success": True, "result_text": "done"}

        orch._run_delegated_executor = capture_executor
        adapter = TaskExecutorAdapter(orch)
        adapter._run_ephemeral(orch, task, parent_sid, None)

        user_input = captured["user_input"]
        assert PLAN_TEXT in user_input
        assert EXPANDED_CONTEXT_HEADER in user_input
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER not in user_input


class TestSpecialistSnapshotGoneReceivesFulltext:
    """Specialist 路径快照消亡后经 TaskExecutorAdapter._run_specialist 执行:
    执行体输入仍含全文(补集成覆盖,与 ephemeral 对称)。"""

    def test_run_specialist_receives_fulltext_after_snapshot_gone(self, orch, monkeypatch):
        from src.business.orchestration.agent.task_executor_adapter import (
            TaskExecutorAdapter,
        )
        from src.business.task_collaboration.dispatcher import TaskDispatcher
        from src.data.repos import AssistantTaskRepository, SpecialistRepository

        parent_sid = _parent_session(orch)
        specialist_name = f"文档专员-{uuid.uuid4().hex[:8]}"
        with SpecialistRepository() as repo:
            specialist_id = repo.create_specialist(
                name=specialist_name,
                description="按要求编写文档",
                role_definition="保真接收委派上下文并完成文档任务。",
                tool_whitelist=[],
                origin="test",
                reason="032 specialist context handoff integration",
            )

        # 真 handler → DelegationOrchestrator → TaskDispatcher → Repository。
        orch._config.get_assistant_tasks_unified_dispatch_enabled.return_value = True
        monkeypatch.setattr(orch, "_start_unified_attempt", lambda *a, **kw: None)
        monkeypatch.setattr(
            "src.business.task_collaboration.dispatcher.get_unified_config",
            lambda: _DispatcherConfig(),
        )
        dispatcher = TaskDispatcher(cutover_guard=_NoopCutoverGuard())
        monkeypatch.setattr(orch, "_get_task_dispatcher", lambda: dispatcher)
        handler = _specialist_handler(orch, parent_sid)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            data = json.loads(
                handler(
                    specialist_name=specialist_name,
                    task="把方案写到 docs/plan.md",
                    execution_context="目标路径 docs/plan.md",
                    context_message_indexes=[3],
                )
            )

        assert data.get("accepted") is True, f"unified dispatch 未生效: {data}"
        with AssistantTaskRepository() as repo:
            task = repo.get_task(data["taskId"])
        assert task is not None
        assert task.assignee_id == specialist_id
        assert PLAN_TEXT in (task.description or "")
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER in (task.description or "")

        captured: dict = {}

        def capture_executor(**kwargs):
            captured.update(kwargs)
            return {"success": True, "result_text": "done"}

        orch._run_delegated_executor = capture_executor

        # 快照不存在
        assert get_llm_messages_snapshot() is None

        # mock equipment snapshot 以避免 SkillEquipmentService 依赖
        monkeypatch.setattr(
            orch,
            "_specialist_equipped_skills_snapshot",
            staticmethod(lambda s: []),
        )

        adapter = TaskExecutorAdapter(orch)
        execution_dispatcher = TaskDispatcher(
            cutover_guard=_NoopCutoverGuard(),
            executor_callback=adapter,
        )
        try:
            future = execution_dispatcher.start_attempt_async(
                task_id=task.task_id,
                executor_type=AgentType.SPECIALIST.value,
                executor_id=specialist_id,
                lease_owner="032-context-handoff-test",
            )
            assert future is not None
            attempt_payload = future.result(timeout=5)
            assert attempt_payload["accepted"] is True
            assert attempt_payload["deliveredStatus"] == "done"
        finally:
            execution_dispatcher.shutdown(wait=True)
            dispatcher.shutdown(wait=True)

        user_input = captured["user_input"]
        assert PLAN_TEXT in user_input, "specialist 执行体应收到展开全文"
        assert EXPANDED_CONTEXT_HEADER in user_input
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER not in user_input

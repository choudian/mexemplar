"""
032 T011: 专员链路 execution_context 透传(行为契约)。

- DelegationOrchestrator.delegate_to_specialist 把 execution_context 传入
  统一派发 context 与同步执行核心。
- run_specialist_via_delegated_executor 把 execution_context 渲染进执行体
  user_input 的"补充上下文"段。
- TaskExecutorAdapter._run_specialist 不再丢弃 task.description(修复既有缺口)。
"""

import uuid
from unittest.mock import MagicMock

import pytest

from src.business.agents.config import AgentType
from src.business.agents.delegation_context import (
    EXPANDED_CONTEXT_PROVENANCE_MARKER,
    attach_expanded_context_provenance,
)
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.business.orchestration.agent.task_executor_adapter import (
    TaskExecutorAdapter,
    _execution_context_with_checkpoint,
)


@pytest.fixture
def orch(mock_config, in_memory_db):
    return AgentOrchestrator(MagicMock(), mock_config)


def _parent_session(orch) -> str:
    return orch._session_store.create_session(f"wf-{uuid.uuid4().hex[:8]}", AgentType.ASSISTANT)


def _fake_specialist(name="文档专员"):
    specialist = MagicMock()
    specialist.specialist_id = "sp-032"
    specialist.name = name
    specialist.description = "写文档"
    specialist.role_definition = "按规范写文档"
    specialist.tool_whitelist = "[]"
    specialist.composition_ids = "[]"
    specialist.role_kind = "executor"
    specialist.is_active = 1
    return specialist


class TestRunSpecialistCarriesExecutionContext:
    def test_formatter_keeps_legacy_whitespace_normalization_without_expanded_text(self):
        rendered = AgentOrchestrator._format_delegated_task_input("写文件", "  背景  ")

        assert "补充上下文：\n背景\n\n请完成任务" in rendered
        assert "  背景  " not in rendered

    def test_display_header_alone_does_not_claim_expanded_provenance(self):
        legacy = "  说明【主对话相关原文】  "

        rendered = AgentOrchestrator._format_delegated_task_input("写文件", legacy)

        assert "补充上下文：\n说明【主对话相关原文】\n\n请完成任务" in rendered
        assert "说明\n\n【主对话相关原文】" not in rendered

    def test_formatter_preserves_trailing_whitespace_in_expanded_text(self):
        expanded = "【主对话相关原文】\n--- 消息 #3（assistant）---\nMarkdown 硬换行  "

        rendered = AgentOrchestrator._format_delegated_task_input(
            "写文件", attach_expanded_context_provenance(expanded)
        )

        assert expanded in rendered
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER not in rendered

    def test_execution_context_rendered_into_user_input(self, orch):
        parent_sid = _parent_session(orch)
        captured: dict = {}

        def capture_executor(**kwargs):
            captured.update(kwargs)
            return {"success": True, "result_text": "done"}

        orch._run_delegated_executor = capture_executor
        orch._specialist_equipped_skills_snapshot = staticmethod(lambda s: [])

        orch.delegation_orchestrator.run_specialist_via_delegated_executor(
            parent_session_id=parent_sid,
            specialist=_fake_specialist(),
            task="把方案写到 docs/plan.md",
            execution_context="【主对话相关原文】\n--- 消息 #3（assistant）---\n方案全文",
        )

        user_input = captured["user_input"]
        assert "补充上下文" in user_input
        assert "方案全文" in user_input

    def test_no_execution_context_keeps_legacy_input(self, orch):
        parent_sid = _parent_session(orch)
        captured: dict = {}

        def capture_executor(**kwargs):
            captured.update(kwargs)
            return {"success": True, "result_text": "done"}

        orch._run_delegated_executor = capture_executor
        orch._specialist_equipped_skills_snapshot = staticmethod(lambda s: [])

        orch.delegation_orchestrator.run_specialist_via_delegated_executor(
            parent_session_id=parent_sid,
            specialist=_fake_specialist(),
            task="做点什么",
        )

        assert "补充上下文" not in captured["user_input"]


class TestDelegateToSpecialistPassesContext:
    def test_unified_dispatch_receives_execution_context(self, orch, monkeypatch):
        parent_sid = _parent_session(orch)
        captured: dict = {}

        def fake_unified(**kwargs):
            captured.update(kwargs)
            return {"accepted": True, "taskId": "t-1"}

        monkeypatch.setattr(orch, "_dispatch_task_via_unified_model", fake_unified)
        monkeypatch.setattr(
            "src.data.repos.specialist_repository.SpecialistRepository",
            _fake_specialist_repo_cls(_fake_specialist()),
        )

        orch.delegation_orchestrator.delegate_to_specialist(
            parent_session_id=parent_sid,
            specialist_name="文档专员",
            task="写文件",
            execution_context="展开后的上下文全文",
        )

        assert captured["context"] == "展开后的上下文全文"

    def test_sync_fallback_receives_execution_context(self, orch, monkeypatch):
        parent_sid = _parent_session(orch)
        captured: dict = {}

        monkeypatch.setattr(orch, "_dispatch_task_via_unified_model", lambda **kw: None)
        monkeypatch.setattr(
            "src.data.repos.specialist_repository.SpecialistRepository",
            _fake_specialist_repo_cls(_fake_specialist()),
        )

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"success": True}

        monkeypatch.setattr(
            orch.delegation_orchestrator,
            "run_specialist_via_delegated_executor",
            fake_run,
        )

        orch.delegation_orchestrator.delegate_to_specialist(
            parent_session_id=parent_sid,
            specialist_name="文档专员",
            task="写文件",
            execution_context="展开后的上下文全文",
        )

        assert captured["execution_context"] == "展开后的上下文全文"


class TestAdapterSpecialistDescriptionNotDropped:
    def test_checkpoint_helper_keeps_legacy_whitespace_normalization(self):
        assert _execution_context_with_checkpoint("  背景  ", None) == "背景"

    def test_checkpoint_helper_keeps_provenance_until_formatter(self):
        expanded = "【主对话相关原文】\nMarkdown 硬换行  "

        marked = attach_expanded_context_provenance(expanded)

        assert _execution_context_with_checkpoint(marked, None) == marked

    def test_checkpoint_helper_preserves_text_before_appending_checkpoint(self):
        expanded = "【主对话相关原文】\nMarkdown 硬换行  "

        marked = attach_expanded_context_provenance(expanded)
        rendered = _execution_context_with_checkpoint(marked, '{"step": 2}')

        assert rendered == f'{marked}\n\n恢复检查点:\n{{"step": 2}}'
        final_input = AgentOrchestrator._format_delegated_task_input("写文件", rendered)
        assert expanded in final_input
        assert '恢复检查点:\n{"step": 2}' in final_input
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER not in final_input

    def test_adapter_then_formatter_preserves_expanded_trailing_whitespace(self):
        """异步链路只能在最终执行体格式化边界消费一次 provenance。"""
        expanded = "【主对话相关原文】\nMarkdown 硬换行  "
        marked = attach_expanded_context_provenance(expanded)

        staged = _execution_context_with_checkpoint(marked, None)
        rendered = AgentOrchestrator._format_delegated_task_input("写文件", staged)

        assert expanded in rendered
        assert EXPANDED_CONTEXT_PROVENANCE_MARKER not in rendered

    def test_run_specialist_passes_task_description(self, orch, monkeypatch):
        """修复既有缺口:异步专员路径 task.description 不再被静默丢弃"""
        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"success": True}

        monkeypatch.setattr(
            orch.delegation_orchestrator,
            "run_specialist_via_delegated_executor",
            fake_run,
        )
        monkeypatch.setattr(
            "src.data.repos.specialist_repository.SpecialistRepository",
            _fake_specialist_repo_cls(_fake_specialist()),
        )

        task = MagicMock()
        task.task_id = "t-032"
        task.title = "写文件"
        task.description = "展开后的全文(含主对话相关原文)"
        task.assignee_id = "sp-032"

        adapter = TaskExecutorAdapter(orch)
        adapter._run_specialist(orch, task, "parent-sid", None)

        assert "展开后的全文(含主对话相关原文)" in captured["execution_context"]
        assert captured["task"] == "写文件"

    def test_empty_description_keeps_legacy_input_shape(self, orch, monkeypatch):
        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"success": True}

        monkeypatch.setattr(
            orch.delegation_orchestrator,
            "run_specialist_via_delegated_executor",
            fake_run,
        )
        monkeypatch.setattr(
            "src.data.repos.specialist_repository.SpecialistRepository",
            _fake_specialist_repo_cls(_fake_specialist()),
        )

        task = MagicMock()
        task.task_id = "t-032-empty-description"
        task.title = "写文件"
        task.description = ""
        task.assignee_id = "sp-032"

        adapter = TaskExecutorAdapter(orch)
        adapter._run_specialist(orch, task, "parent-sid", None)

        assert captured["task"] == "写文件"
        assert captured["execution_context"] == ""

    def test_title_fallback_description_keeps_legacy_input_shape(self, orch, monkeypatch):
        """统一派发会以 title 兜底 description；专员执行时不得因此重复任务。"""
        captured: dict = {}

        def fake_run(**kwargs):
            captured.update(kwargs)
            return {"success": True}

        monkeypatch.setattr(
            orch.delegation_orchestrator,
            "run_specialist_via_delegated_executor",
            fake_run,
        )
        monkeypatch.setattr(
            "src.data.repos.specialist_repository.SpecialistRepository",
            _fake_specialist_repo_cls(_fake_specialist()),
        )

        task = MagicMock()
        task.task_id = "t-032-title-fallback"
        task.title = "写文件"
        task.description = "写文件"
        task.assignee_id = "sp-032"

        TaskExecutorAdapter(orch)._run_specialist(orch, task, "parent-sid", None)

        assert captured["task"] == "写文件"
        assert captured["execution_context"] == ""


def _fake_specialist_repo_cls(specialist):
    class _FakeRepo:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_specialist_by_name(self, name):
            return specialist

        def get_specialist(self, specialist_id):
            return specialist

    return _FakeRepo

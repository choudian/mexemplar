import json
from types import SimpleNamespace

import pytest

from src.business.agents.config import ResultType
from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager
from src.business.orchestration.agent import AgentOrchestrator
from src.business.services import SkillCompositionError, SkillCompositionService, SkillsService
import src.business.services.skill_composition.service as skill_composition_service_module
from src.data.models import SkillComposition, SkillCompositionMember, Tool
from src.data.models_sqlite import (
    Message as MessageOrm,
    Session as SessionOrm,
    SkillComposition as SkillCompositionOrm,
    SkillCompositionMember as SkillCompositionMemberOrm,
    Tool as ToolOrm,
)
from src.data.repositories import (
    MessageRepository,
    SessionRepository,
    SkillCompositionRepository,
    ToolRepository,
)


class _FakeConfig:
    def get_ai_api_key(self) -> str:
        return "test-key"

    def get_ai_provider(self) -> str:
        return "openai"

    def get_ai_model(self) -> str:
        return "gpt-test"

    def get_ai_base_url(self):
        return None

    def get_ai_thinking_level(self):
        return None

    def get_ai_request_timeout(self) -> int:
        return 60

    def get_ai_retry_max_retries(self) -> int:
        return 0

    def get_ai_retry_delay(self) -> float:
        return 0.0


class _DummyLLMClient:
    def __init__(self, *args, **kwargs):
        pass


def _patch_trial_environment(monkeypatch) -> None:
    monkeypatch.setattr(
        skill_composition_service_module,
        "get_unified_config",
        lambda: _FakeConfig(),
    )
    monkeypatch.setattr(
        skill_composition_service_module,
        "LangChainLLMClient",
        _DummyLLMClient,
    )


def _seed_published_tool(
    tool_id: str,
    tool_name: str,
    description: str = "技能描述",
) -> None:
    with ToolRepository() as tool_repo:
        tool_repo.create(
            ToolOrm(
                tool_id=tool_id,
                tool_name=tool_name,
                description=description,
                status="published",
            )
        )


def _create_composition(
    composition_name: str,
    tool_ids: list[str],
    mode: str = "range",
) -> SkillComposition:
    members = []
    for index, tool_id in enumerate(tool_ids, start=1):
        members.append(
            {
                "tool_id": tool_id,
                "selected_order": index,
                "execution_order": index if mode == "ordered" else None,
            }
        )
    return SkillCompositionService().create_composition(
        composition_name=composition_name,
        description=f"{composition_name}描述",
        applicability=f"{composition_name}适用场景",
        mode=mode,
        assistant_enabled=True,
        recommend_order=(mode == "ordered"),
        members=members,
    )


def _seed_review_required_composition() -> None:
    _seed_published_tool("tool_reviewed_member", "成员技能", "成员技能描述")

    with SkillCompositionRepository() as composition_repo:
        composition_repo.create(
            SkillCompositionOrm(
                composition_id="comp_needs_review",
                composition_name="待复核组合",
                description="需要重新发布",
                applicability="测试待复核过滤",
                mode="range",
                status="published",
                assistant_enabled=True,
                needs_review=True,
            ),
            [
                SkillCompositionMemberOrm(
                    member_id="member_reviewed_1",
                    composition_id="comp_needs_review",
                    tool_id="tool_reviewed_member",
                    selected_order=1,
                )
            ],
        )


def test_update_tool_metadata_persists_with_single_repository_session():
    with ToolRepository() as repo:
        repo.create(
            ToolOrm(
                tool_id="tool_meta_update",
                tool_name="旧名称",
                description="旧描述",
                status="published",
            )
        )

    referenced = SkillsService().update_tool_metadata(
        "tool_meta_update",
        "新名称",
        " 新描述 ",
    )

    assert referenced == []
    with ToolRepository() as repo:
        updated = repo.get_by_id("tool_meta_update")
        assert updated is not None
        assert updated.tool_name == "新名称"
        assert updated.description == "新描述"


def test_needs_review_compositions_are_hidden_from_assistant_queries():
    _seed_review_required_composition()

    service = SkillCompositionService()

    assert service.get_assistant_published_summaries() == []
    assert service.search_published_compositions("待复核组合") == []

    detail = DynamicToolManager().get_tool_detail("技能组合:待复核组合")
    assert "不存在或当前不可用" in detail


def test_execution_snapshot_hides_needs_review_composition_when_published_is_required():
    _seed_review_required_composition()

    service = SkillCompositionService()

    assert service.get_execution_snapshot("comp_needs_review") is None
    assert (
        service.get_execution_snapshot(
            "comp_needs_review",
            require_published=False,
        )
        is not None
    )


def test_large_composition_keeps_all_members_activated():
    manager = DynamicToolManager(revalidate_activated=False)
    members = []
    expected_short_ids = set()

    for index in range(1, 13):
        tool = Tool(
            tool_id=f"tool_large_{index}",
            tool_name=f"大组合成员 {index}",
            description=f"成员 {index}",
            status="published",
        )
        members.append(
            SkillCompositionMember(
                tool_id=tool.tool_id,
                selected_order=index,
                execution_order=index,
                tool=tool,
            )
        )
        expected_short_ids.add(manager._make_short_id(tool.tool_id, "utool"))

    composition = SkillComposition(
        composition_id="comp_large",
        composition_name="超大组合",
        applicability="验证成员激活不被提前淘汰",
        mode="ordered",
        status="published",
        assistant_enabled=True,
        members=members,
    )

    handler = manager._create_composition_handler(composition)
    handler(task="执行超大组合")

    activated_short_ids = {tool_def.name for tool_def in manager.get_activated_tools()}
    assert expected_short_ids.issubset(activated_short_ids)


def test_generate_applicability_uses_selected_skills_and_cleans_prefix(monkeypatch):
    _seed_published_tool("tool_apply_1", "资料抓取", "收集原始资料")
    _seed_published_tool("tool_apply_2", "结果整理", "整理输出结构")
    monkeypatch.setattr(
        skill_composition_service_module,
        "get_unified_config",
        lambda: _FakeConfig(),
    )

    captured = {}

    class _ApplicabilityLLM:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, prompt: str, **kwargs) -> str:
            captured["prompt"] = prompt
            return "适用场景：适合先抓取资料、再整理结果的多步骤任务。"

    monkeypatch.setattr(
        skill_composition_service_module,
        "LangChainLLMClient",
        _ApplicabilityLLM,
    )

    result = SkillCompositionService().generate_applicability(
        composition_name="资料整合组合",
        description="先抓取再整理",
        mode="ordered",
        members=[
            {"tool_id": "tool_apply_1", "selected_order": 1, "execution_order": 1},
            {"tool_id": "tool_apply_2", "selected_order": 2, "execution_order": 2},
        ],
    )

    assert result == "适合先抓取资料、再整理结果的多步骤任务。"
    assert "资料抓取" in captured["prompt"]
    assert "结果整理" in captured["prompt"]
    assert "组合模式：顺序型" in captured["prompt"]


def test_get_tool_detail_accepts_display_labels_shown_to_assistant():
    _seed_published_tool("tool_display_label", "展示技能", "用于验证展示名激活")
    _seed_published_tool("tool_display_label_2", "展示技能2", "第二个成员")
    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="展示组合",
        description="用于验证展示名激活",
        applicability="测试展示名解析",
        mode="ordered",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "tool_display_label", "selected_order": 1, "execution_order": 1},
            {"tool_id": "tool_display_label_2", "selected_order": 2, "execution_order": 2},
        ],
    )
    service.publish_composition(composition.composition_id)

    manager = DynamicToolManager()

    tool_detail = manager.get_tool_detail("- **[技能] 展示技能**：用于验证展示名激活")
    composition_detail = manager.get_tool_detail("- [技能组合/顺序型] 展示组合：用于验证展示名激活")

    assert "技能已激活" in tool_detail
    assert "技能组合已激活" in composition_detail


def test_search_tools_supports_browse_filter_pagination_and_legacy_query():
    for index in range(6):
        _seed_published_tool(
            f"tool_search_{index}",
            f"报告能力{index}",
            f"生成报告 {index}",
        )
    _seed_published_tool("tool_search_unrelated", "无关能力", "其它用途")
    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="报告组合",
        description="组合报告流程",
        applicability="适合报告任务",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "tool_search_0", "selected_order": 1},
            {"tool_id": "tool_search_1", "selected_order": 2},
        ],
    )
    service.publish_composition(composition.composition_id)
    manager = DynamicToolManager()

    first = json.loads(manager.search_tools(query="", offset=0, limit=3))
    second = json.loads(manager.search_tools(query="", offset=first["nextOffset"], limit=3))
    legacy = json.loads(manager.search_tools("报告"))
    compositions = json.loads(manager.search_tools(query="", kind="composition"))

    assert first["total"] == 8
    assert len(first["items"]) == 3
    assert first["nextOffset"] == 3
    assert {item["selector"] for item in first["items"]}.isdisjoint(
        {item["selector"] for item in second["items"]}
    )
    assert legacy["query"] == "报告"
    assert legacy["total"] == 7
    assert compositions["total"] == 1
    assert compositions["items"][0]["selector"] == "技能组合:报告组合"


def test_search_tools_applies_tool_and_composition_authorization():
    _seed_published_tool("tool_allowed", "允许技能", "允许")
    _seed_published_tool("tool_allowed_2", "允许技能2", "允许")
    _seed_published_tool("tool_denied", "拒绝技能", "拒绝")
    service = SkillCompositionService()
    allowed_composition = service.create_composition(
        composition_name="允许组合",
        description="成员都允许",
        applicability="测试",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "tool_allowed", "selected_order": 1},
            {"tool_id": "tool_allowed_2", "selected_order": 2},
        ],
    )
    denied_composition = service.create_composition(
        composition_name="拒绝组合",
        description="含未授权成员",
        applicability="测试",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "tool_allowed", "selected_order": 1},
            {"tool_id": "tool_denied", "selected_order": 2},
        ],
    )
    service.publish_composition(allowed_composition.composition_id)
    service.publish_composition(denied_composition.composition_id)

    manager = DynamicToolManager(allowed_tool_ids={"tool_allowed", "tool_allowed_2"})
    page = json.loads(manager.search_tools())
    selectors = {item["selector"] for item in page["items"]}

    assert selectors == {
        "技能:允许技能",
        "技能:允许技能2",
        "技能组合:允许组合",
    }


def test_search_tools_and_activated_schema_revalidate_status_changes():
    _seed_published_tool("tool_runtime_status", "状态技能", "会被停用")
    manager = DynamicToolManager()
    manager.get_tool_detail("技能:状态技能")

    before = json.loads(manager.search_tools("状态技能"))
    assert before["total"] == 1
    assert manager.get_activated_tools()

    with ToolRepository() as tool_repo:
        tool_repo.update_status("tool_runtime_status", "pending")

    after = json.loads(manager.search_tools("状态技能"))
    assert after["total"] == 0
    assert "不存在或当前不可用" in manager.get_tool_detail("技能:状态技能")
    assert manager.get_activated_tools() == []


def test_search_tools_invalid_parameters_return_error_without_changing_activation():
    _seed_published_tool("tool_search_error", "参数校验技能", "验证错误路径")
    manager = DynamicToolManager()
    manager.get_tool_detail("技能:参数校验技能")
    activated_before = [tool.name for tool in manager.get_activated_tools()]

    for kwargs in (
        {"kind": "unknown"},
        {"offset": -1},
        {"offset": "bad"},
        {"limit": 0},
        {"limit": "bad"},
    ):
        payload = json.loads(manager.search_tools(**kwargs))
        assert payload["success"] is False

    assert [tool.name for tool in manager.get_activated_tools()] == activated_before


def test_activated_composition_is_removed_after_it_needs_review():
    _seed_published_tool("tool_stale_member", "待失效成员", "用于验证重校验")
    _seed_published_tool("tool_stale_member_2", "待失效成员2", "第二个成员")
    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="待失效组合",
        description="用于验证重校验",
        applicability="用于验证重校验",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "tool_stale_member", "selected_order": 1},
            {"tool_id": "tool_stale_member_2", "selected_order": 2},
        ],
    )
    service.publish_composition(composition.composition_id)

    manager = DynamicToolManager()
    manager.get_tool_detail("技能组合:待失效组合")
    composition_short_id = manager._make_short_id(composition.composition_id, "comp")
    assert composition_short_id in {tool.name for tool in manager.get_activated_tools()}
    assert json.loads(manager.search_tools("待失效组合"))["total"] == 1

    service.mark_needs_review_by_tool("tool_stale_member")

    assert json.loads(manager.search_tools("待失效组合"))["total"] == 0
    assert "不存在或当前不可用" in manager.get_tool_detail("技能组合:待失效组合")
    assert composition_short_id not in {tool.name for tool in manager.get_activated_tools()}


def test_save_tool_marks_referencing_compositions_stale_when_status_changes_to_pending(monkeypatch):
    workflow_id = "wf_status_flip_member"
    with ToolRepository() as tool_repo:
        tool_repo.create(
            ToolOrm(
                tool_id="tool_status_flip_member",
                tool_name="状态回退成员",
                description="用于验证状态回退触发复核",
                execution_code="print('stable')",
                parameters=[{"name": "topic", "description": "主题"}],
                execution_strategy="function_call",
                workflow_id=workflow_id,
                source="intent",
                status="published",
            )
        )

    _seed_published_tool("tool_status_flip_member_2", "状态回退成员2", "第二个成员")
    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="状态回退组合",
        description="用于验证状态回退触发复核",
        applicability="用于验证状态回退触发复核",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "tool_status_flip_member", "selected_order": 1},
            {"tool_id": "tool_status_flip_member_2", "selected_order": 2},
        ],
    )
    service.publish_composition(composition.composition_id)

    manager = DynamicToolManager()
    manager.get_tool_detail("技能组合:状态回退组合")
    composition_short_id = manager._make_short_id(composition.composition_id, "comp")
    assert composition_short_id in {tool.name for tool in manager.get_activated_tools()}

    orchestrator = AgentOrchestrator(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(),
        llm_reviewer=SimpleNamespace(),
    )
    orchestrator._composition_service = service
    monkeypatch.setattr(orchestrator, "_emit_and_log", lambda *args, **kwargs: None)

    saved_tool_id = orchestrator._save_tool(
        {
            "code": "print('stable')",
            "tool_name": "状态回退成员",
            "description": "用于验证状态回退触发复核",
            "parameters": [{"name": "topic", "description": "主题"}],
            "execution_strategy": "function_call",
        },
        workflow_id=workflow_id,
        session_id="session_status_flip_member",
        status="pending",
    )

    assert saved_tool_id == "tool_status_flip_member"
    refreshed = service.get_composition(composition.composition_id)
    assert refreshed is not None
    assert refreshed.needs_review is True
    assert composition_short_id not in {tool.name for tool in manager.get_activated_tools()}


def test_service_create_composition_defaults_assistant_enabled_and_recommend_order():
    """Service 层 create_composition 的 assistant_enabled / recommend_order 有正确默认值。"""
    import inspect

    sig = inspect.signature(SkillCompositionService.create_composition)
    assert sig.parameters["assistant_enabled"].default is True
    assert sig.parameters["recommend_order"].default is False


def test_start_trial_session_creates_session():
    _seed_published_tool("tool_range_dialog_member", "范围成员", "范围成员描述")
    _seed_published_tool("tool_range_dialog_member_2", "范围成员2", "第二个成员")
    composition = _create_composition(
        "范围试用组合",
        ["tool_range_dialog_member", "tool_range_dialog_member_2"],
        mode="range",
    )

    start = SkillCompositionService().start_trial_session(composition.composition_id)

    assert start.composition_id == composition.composition_id
    assert start.composition_name == composition.composition_name

    with SessionRepository() as repo:
        session = repo.get_by_id(start.session_id)
        assert session is not None
        assert session.workflow_id == composition.composition_id
        assert session.agent_type == "composition_trial"


def test_build_trial_bootstrap_input_uses_program_role():
    bootstrap = SkillCompositionService.build_trial_bootstrap_input()

    assert bootstrap["role"] == "program"
    assert "主动向用户发起第一轮沟通" in bootstrap["content"]
    assert "不要先讲长篇说明" in bootstrap["content"]


def test_trial_prompt_does_not_reference_unavailable_helper_tools():
    composition = SkillComposition(
        composition_id="comp_prompt_test",
        composition_name="试用提示组合",
        description="验证试用提示词",
        applicability="验证试用提示词",
        mode="ordered",
        status="published",
        assistant_enabled=True,
        members=[
            SkillCompositionMember(
                tool_id="tool_prompt_a",
                selected_order=1,
                execution_order=1,
                tool=Tool(
                    tool_id="tool_prompt_a",
                    tool_name="成员A",
                    parameters=[
                        {"name": "query", "description": "想查的主题", "required": True},
                        {
                            "name": "limit",
                            "description": "数量上限",
                            "required": False,
                            "default": 3,
                        },
                    ],
                    status="published",
                ),
            ),
            SkillCompositionMember(
                tool_id="tool_prompt_b",
                selected_order=2,
                execution_order=2,
                tool=Tool(tool_id="tool_prompt_b", tool_name="成员B", status="published"),
            ),
        ],
    )

    prompt = SkillCompositionService._build_trial_system_prompt(composition)

    assert "search_tools" not in prompt
    assert "get_tool_detail" not in prompt
    assert "report_tool_bug" not in prompt
    assert "你必须先直接调用这个技能组合本身" in prompt
    assert "成员技能只会在技能组合启动后才会出现" in prompt
    assert "## 你的任务" in prompt
    assert "## 你的内部推进节奏" in prompt
    assert "## 引导策略" in prompt
    assert "先获取用户这次想通过这个技能组合完成什么任务" in prompt
    assert "先判断这个技能组合能不能完成当前任务" in prompt
    assert "获取目标：先判断用户有没有明确说出这次想完成什么任务" in prompt
    assert "判断可行性与缺口：基于整体目标，先判断这个技能组合能不能完成任务" in prompt
    assert "顺序型组合的完整目标有四件事" in prompt
    assert "先判断这个技能组合按当前配置是否真的适合完成用户的任务" in prompt
    assert "更合适的路径更像是 1-3-2 而不是当前配置的 1-2-3" in prompt
    assert "用户接受就继续，以完成任务为第一优先" in prompt
    assert "用非技术语言说话" in prompt
    assert "不要说“参数”“字段”“变量”“内部名”" in prompt
    assert "不要把“参数”“参数名”“字段名”“内部名”这类技术词直接抛给用户" in prompt
    assert "如果你判断这个组合本身不适合当前任务，或者当前顺序不太对" in prompt
    assert "不要为了顺序完美而放弃完成任务" in prompt
    assert "不要先做大段说明" in prompt
    assert "不要模板化寒暄" in prompt
    assert "把任务最终结果用用户能看懂的方式反馈给用户" in prompt
    assert "第 1 步技能：成员A" in prompt
    assert "想查的主题" in prompt


def test_trial_initially_exposes_only_composition_tool(monkeypatch):
    _seed_published_tool("tool_trial_member", "试用成员")
    _seed_published_tool("tool_trial_member_2", "试用成员2")
    composition = _create_composition("试用组合", ["tool_trial_member", "tool_trial_member_2"])
    _patch_trial_environment(monkeypatch)

    captured = {}
    composition_short_id = DynamicToolManager()._make_short_id(
        composition.composition_id,
        "comp",
    )
    member_short_id = DynamicToolManager()._make_short_id("tool_trial_member", "utool")

    def fake_run(self, session_id, user_input=None, tools=None, system_prompt_override=None):
        tool_defs = tools() if callable(tools) else tools
        captured["tool_names"] = [tool.name for tool in tool_defs]
        captured["session_id"] = session_id
        captured["user_input"] = user_input
        captured["system_prompt"] = system_prompt_override
        return SimpleNamespace(
            result_type=ResultType.NEEDS_USER_INPUT,
            question="请补充任务细节",
            error=None,
        )

    monkeypatch.setattr(skill_composition_service_module.AgentLoop, "run", fake_run)

    start = SkillCompositionService().start_trial_session(composition.composition_id)
    result = SkillCompositionService().continue_trial(
        composition.composition_id,
        start.session_id,
        SkillCompositionService.build_trial_bootstrap_input(),
    )

    assert composition_short_id in captured["tool_names"]
    assert member_short_id not in captured["tool_names"]
    assert captured["user_input"]["role"] == "program"
    assert "第一轮沟通" in captured["user_input"]["content"]
    assert "你必须先直接调用这个技能组合本身" in captured["system_prompt"]
    assert "成员技能只会在技能组合启动后才会出现" in captured["system_prompt"]
    assert result.success is False
    assert result.result_type == ResultType.NEEDS_USER_INPUT.value
    assert result.reply == "请补充任务细节"
    assert result.session_id == captured["session_id"]

    with SessionRepository() as repo:
        session = repo.get_by_id(result.session_id)
        assert session is not None
        assert session.workflow_id == composition.composition_id


def test_continue_trial_exposes_members_after_composition_has_started(monkeypatch):
    _seed_published_tool("tool_continue_member_1", "续跑成员1")
    _seed_published_tool("tool_continue_member_2", "续跑成员2")
    composition = _create_composition(
        "续跑组合",
        ["tool_continue_member_1", "tool_continue_member_2"],
        mode="ordered",
    )
    _patch_trial_environment(monkeypatch)

    session_id = "comptrial_continue"
    composition_short_id = DynamicToolManager()._make_short_id(
        composition.composition_id,
        "comp",
    )
    member_short_ids = {
        DynamicToolManager()._make_short_id("tool_continue_member_1", "utool"),
        DynamicToolManager()._make_short_id("tool_continue_member_2", "utool"),
    }

    with SessionRepository() as session_repo:
        session_repo.create(
            SessionOrm(
                session_id=session_id,
                workflow_id=composition.composition_id,
                agent_type="composition_trial",
                status="suspended",
            )
        )

    with MessageRepository() as message_repo:
        message_repo.create(
            MessageOrm(
                message_id="msg_composition_started",
                session_id=session_id,
                sequence=1,
                role="tool",
                content="技能组合已启动",
                tool_name=composition_short_id,
            )
        )

    captured = {}

    def fake_run(self, session_id, user_input=None, tools=None, system_prompt_override=None):
        tool_defs = tools() if callable(tools) else tools
        captured["tool_names"] = [tool.name for tool in tool_defs]
        with MessageRepository() as message_repo:
            message_repo.create(
                MessageOrm(
                    message_id="msg_composition_reply",
                    session_id=session_id,
                    sequence=message_repo.get_next_sequence(session_id),
                    role="assistant",
                    content="组合试用完成",
                )
            )
        return SimpleNamespace(result_type=ResultType.COMPLETED, error=None)

    monkeypatch.setattr(skill_composition_service_module.AgentLoop, "run", fake_run)

    result = SkillCompositionService().continue_trial(
        composition.composition_id,
        session_id,
        "补充信息",
    )

    assert composition_short_id in captured["tool_names"]
    assert member_short_ids.issubset(set(captured["tool_names"]))
    assert result.success is True
    assert result.reply == "组合试用完成"


def test_continue_trial_uses_saved_session_snapshot_when_live_composition_changes(monkeypatch):
    _seed_published_tool("snapold1_member", "旧成员1", "旧成员1描述")
    _seed_published_tool("snapold2_member", "旧成员2")
    _seed_published_tool("snapnewx_member", "新成员")
    _seed_published_tool("snapnewy_member", "新成员2")

    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="快照组合",
        description="旧版组合",
        applicability="旧版组合适用场景",
        mode="ordered",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "snapold1_member", "selected_order": 1, "execution_order": 1},
            {"tool_id": "snapold2_member", "selected_order": 2, "execution_order": 2},
        ],
    )
    snapshot_payload = service._build_trial_session_snapshot_payload(composition)
    _patch_trial_environment(monkeypatch)

    service.update_composition(
        composition_id=composition.composition_id,
        composition_name="快照组合",
        description="新版组合",
        applicability="新版组合适用场景",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "snapnewx_member", "selected_order": 1},
            {"tool_id": "snapnewy_member", "selected_order": 2},
        ],
    )
    with ToolRepository() as tool_repo:
        old_member = tool_repo.get_by_id("snapold1_member")
        assert old_member is not None
        old_member.tool_name = "旧成员1-线上改版"
        old_member.description = "旧成员1线上改版描述"
        old_member.parameters = [{"name": "city", "description": "线上改版输入"}]
        old_member.execution_code = "print('live-changed')"
        tool_repo.update(old_member)

    session_id = "comptrial_snapshot"
    composition_short_id = DynamicToolManager()._make_short_id(
        composition.composition_id,
        "comp",
    )
    old_member_short_ids = {
        DynamicToolManager()._make_short_id("snapold1_member", "utool"),
        DynamicToolManager()._make_short_id("snapold2_member", "utool"),
    }
    new_member_short_id = DynamicToolManager()._make_short_id("snapnewx_member", "utool")

    with SessionRepository() as session_repo:
        session_repo.create(
            SessionOrm(
                session_id=session_id,
                workflow_id=composition.composition_id,
                agent_type="composition_trial",
                status="suspended",
                tool_ids=json.dumps(snapshot_payload, ensure_ascii=False),
            )
        )
        session = session_repo.get_by_id(session_id)
        assert session is not None

    restored = service._get_trial_session_composition(session)
    assert restored is not None
    assert restored.mode == "ordered"
    assert restored.description == "旧版组合"
    assert restored.applicability == "旧版组合适用场景"
    assert [member.tool_id for member in restored.members] == ["snapold1_member", "snapold2_member"]
    assert [member.selected_order for member in restored.members] == [1, 2]
    assert [member.execution_order for member in restored.members] == [1, 2]
    assert restored.members[0].tool is not None
    assert restored.members[0].tool.tool_name == "旧成员1"
    assert restored.members[0].tool.description == "旧成员1描述"
    assert restored.members[0].tool.parameters == []
    assert restored.members[0].tool.execution_code is None

    with MessageRepository() as message_repo:
        message_repo.create(
            MessageOrm(
                message_id="msg_snapshot_started",
                session_id=session_id,
                sequence=1,
                role="tool",
                content="技能组合已启动",
                tool_name=composition_short_id,
            )
        )

    captured = {}

    def fake_run(self, session_id, user_input=None, tools=None, system_prompt_override=None):
        tool_defs = tools() if callable(tools) else tools
        captured["tool_names"] = [tool.name for tool in tool_defs]
        return SimpleNamespace(
            result_type=ResultType.NEEDS_USER_INPUT,
            question="继续补充信息",
            error=None,
        )

    monkeypatch.setattr(skill_composition_service_module.AgentLoop, "run", fake_run)

    result = service.continue_trial(
        composition.composition_id,
        session_id,
        "继续试用",
    )

    assert composition_short_id in captured["tool_names"]
    assert old_member_short_ids.issubset(set(captured["tool_names"]))
    assert new_member_short_id not in captured["tool_names"]
    assert result.result_type == ResultType.NEEDS_USER_INPUT.value


def test_continue_trial_keeps_members_hidden_until_composition_has_started(monkeypatch):
    _seed_published_tool("tool_continue_hidden", "续跑隐藏成员")
    _seed_published_tool("tool_continue_hidden_2", "续跑隐藏成员2")
    composition = _create_composition(
        "续跑未启动组合", ["tool_continue_hidden", "tool_continue_hidden_2"]
    )
    _patch_trial_environment(monkeypatch)

    session_id = "comptrial_not_started"
    composition_short_id = DynamicToolManager()._make_short_id(
        composition.composition_id,
        "comp",
    )
    member_short_id = DynamicToolManager()._make_short_id("tool_continue_hidden", "utool")

    with SessionRepository() as session_repo:
        session_repo.create(
            SessionOrm(
                session_id=session_id,
                workflow_id=composition.composition_id,
                agent_type="composition_trial",
                status="suspended",
            )
        )

    captured = {}

    def fake_run(self, session_id, user_input=None, tools=None, system_prompt_override=None):
        tool_defs = tools() if callable(tools) else tools
        captured["tool_names"] = [tool.name for tool in tool_defs]
        return SimpleNamespace(
            result_type=ResultType.NEEDS_USER_INPUT,
            question="还需要更多信息",
            error=None,
        )

    monkeypatch.setattr(skill_composition_service_module.AgentLoop, "run", fake_run)

    result = SkillCompositionService().continue_trial(
        composition.composition_id,
        session_id,
        "补充信息",
    )

    assert composition_short_id in captured["tool_names"]
    assert member_short_id not in captured["tool_names"]
    assert result.success is False
    assert result.result_type == ResultType.NEEDS_USER_INPUT.value


def test_continue_trial_rejects_session_from_other_composition():
    _seed_published_tool("tool_session_guard", "会话守卫成员")
    _seed_published_tool("tool_session_guard_2", "会话守卫成员2")
    first = _create_composition("会话组合A", ["tool_session_guard", "tool_session_guard_2"])
    second = _create_composition("会话组合B", ["tool_session_guard", "tool_session_guard_2"])

    with SessionRepository() as session_repo:
        session_repo.create(
            SessionOrm(
                session_id="comptrial_foreign",
                workflow_id=first.composition_id,
                agent_type="composition_trial",
                status="suspended",
            )
        )

    with pytest.raises(SkillCompositionError, match="不属于当前技能组合"):
        SkillCompositionService().continue_trial(
            second.composition_id,
            "comptrial_foreign",
            "补充信息",
        )


def test_duplicate_composition_name_is_rejected_on_create():
    _seed_published_tool("tool_duplicate_create", "重名成员")
    _seed_published_tool("tool_duplicate_create_2", "重名成员2")
    members = [
        {"tool_id": "tool_duplicate_create", "selected_order": 1},
        {"tool_id": "tool_duplicate_create_2", "selected_order": 2},
    ]
    service = SkillCompositionService()
    service.create_composition(
        composition_name="重名组合",
        description="第一个组合",
        applicability="创建测试",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=members,
    )

    with pytest.raises(SkillCompositionError, match="技能组合名称已存在"):
        service.create_composition(
            composition_name=" 重名组合 ",
            description="第二个组合",
            applicability="创建测试2",
            mode="range",
            assistant_enabled=True,
            recommend_order=False,
            members=members,
        )


def test_duplicate_composition_name_is_rejected_on_update():
    _seed_published_tool("tool_duplicate_update", "更新重名成员")
    _seed_published_tool("tool_duplicate_update_2", "更新重名成员2")
    members = [
        {"tool_id": "tool_duplicate_update", "selected_order": 1},
        {"tool_id": "tool_duplicate_update_2", "selected_order": 2},
    ]
    service = SkillCompositionService()
    service.create_composition(
        composition_name="组合甲",
        description="第一个组合",
        applicability="更新测试1",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=members,
    )
    second = service.create_composition(
        composition_name="组合乙",
        description="第二个组合",
        applicability="更新测试2",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=members,
    )

    with pytest.raises(SkillCompositionError, match="技能组合名称已存在"):
        service.update_composition(
            composition_id=second.composition_id,
            composition_name="组合甲",
            description="第二个组合",
            applicability="更新测试2",
            mode="range",
            assistant_enabled=True,
            recommend_order=False,
            members=members,
        )

    reloaded = service.get_composition(second.composition_id)
    assert reloaded is not None
    assert reloaded.composition_name == "组合乙"

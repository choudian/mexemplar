"""主助理工具隔离门卫:主助理只拿只读查找工具,不含副作用执行工具(100% 调度硬边界)。

真断言:实例化 ``AgentOrchestrator`` 后调 ``_build_assistant_tools(session_id)`` 取 factory,
验证工具名集合不含副作用 BUILTIN 工具(由 has_side_effects 派生:write_file/edit_file/
apply_patch/exec/process_stop/process_send_input/process_close),含调度工具
(delegate_to_subagent/delegate_to_specialist)与只读 BUILTIN(read_file/web_search/process_list);
对比 delegated executor 仍含全量副作用工具(防主助理隔离误伤执行层)。

与 test_planner_specialist_tools.py 的区别:那把守「planner 不拿执行工具」,本文件把守
「主助理不拿副作用工具但保留只读」(A− 方向)——两者都不靠 prompt 自觉,靠工具集硬构成。
"""

from src.business.agents.config import AgentType
from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
from src.data.repos.base_repository import generate_id


def _tool_names(factory):
    return {t.name for t in factory()}


def _assistant_tools(orch):
    return _tool_names(orch._build_assistant_tools(generate_id("assistant")))


# 副作用执行工具——直接从 BUILTIN_GENERAL_TOOLS 的 has_side_effects 标志派生(单一真相),
# 不再手动抄一份工具名,避免与 ToolDefinition.has_side_effects 默认值形成两处同步。
_SIDE_EFFECT_TOOLS = {t.name for t in BUILTIN_GENERAL_TOOLS if t.has_side_effects}

# 主助理 MUST 含的调度工具(过滤副作用时不能误伤调度能力)
_ASSISTANT_DISPATCH_TOOLS = {
    "delegate_to_subagent",
    "delegate_to_specialist",
}

# 主助理 MUST 含的只读 BUILTIN 工具(完整 12 个穷举,与 _SIDE_EFFECT_TOOLS 对称;
# A− 方向:移副作用、留只读查找。若有人误把其中某个标 has_side_effects=True,它会从
# ASSISTANT_READ_ONLY_TOOLS 派生集掉出 → 主助理缺该工具 → missing 非空 → 此处挡住)
_ASSISTANT_READ_ONLY_BUILTINS = {
    "web_search",
    "web_fetch",
    "read_file",
    "search_files",
    "search_content",
    "list_dir",
    "process_list",
    "process_poll",
    "process_logs",
    "process_wait",
    "wait_for_process_event",
    "load_tool_output",
}


class TestAssistantToolIsolation:
    """主助理工具集边界——100% 调度的硬保证,不靠 prompt 自觉。"""

    def test_assistant_excludes_side_effect_tools(self, in_memory_db, orchestrator):
        """主助理工具集不含副作用执行工具(由 has_side_effects 派生)。"""
        names = _assistant_tools(orchestrator)
        leaked = _SIDE_EFFECT_TOOLS & names
        assert not leaked, f"主助理不该拿副作用工具,却包含:{leaked}"

    def test_assistant_keeps_dispatch_tools(self, in_memory_db, orchestrator):
        """主助理仍含调度工具 delegate_to_subagent/delegate_to_specialist。"""
        names = _assistant_tools(orchestrator)
        missing = _ASSISTANT_DISPATCH_TOOLS - names
        assert not missing, f"主助理该保留调度工具,却缺失:{missing}"

    def test_assistant_keeps_all_read_only_builtins(self, in_memory_db, orchestrator):
        """主助理保留全部 12 个只读 BUILTIN 工具(穷举,防某个被误标副作用后悄悄掉出)。"""
        names = _assistant_tools(orchestrator)
        missing = _ASSISTANT_READ_ONLY_BUILTINS - names
        assert not missing, f"主助理该保留只读 BUILTIN,却缺失:{missing}"

    def test_executor_still_includes_side_effect_tools(self, in_memory_db, orchestrator):
        """delegated executor 仍含全量副作用工具——防主助理隔离误伤执行层。"""
        factory = orchestrator._build_delegated_executor_tools(
            None,
            agent_type=AgentType.SPECIALIST,
            specialist_id="spec-guard",
            role_kind="executor",
        )
        names = _tool_names(factory)
        assert "write_file" in names
        assert "exec" in names

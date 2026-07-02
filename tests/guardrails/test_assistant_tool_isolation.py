"""主助理工具隔离门卫:主助理不拿 builtin 读取/抓取/进程/执行工具(100% 调度硬边界)。

真断言:实例化 ``AgentOrchestrator`` 后调 ``_build_assistant_tools(session_id)`` 取 factory,
验证工具名集合不含任何 BUILTIN_GENERAL_TOOLS,含调度工具
(delegate_to_subagent/delegate_to_specialist)与能力目录发现工具(search_tools/get_tool_detail);
对比 delegated executor 仍含全量 BUILTIN 工具(防主助理隔离误伤执行层)。

与 test_planner_specialist_tools.py 的区别:那把守「planner 不拿执行工具」,本文件把守
「主助理不拿 builtin general 工具」(A− 方向)——两者都不靠 prompt 自觉,靠工具集硬构成。
"""

from src.business.agents.config import AgentType
from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
from src.data.repos.base_repository import generate_id


def _tool_names(factory):
    return {t.name for t in factory()}


def _assistant_tools(orch):
    return _tool_names(orch._build_assistant_tools(generate_id("assistant")))


_BUILTIN_TOOL_NAMES = {t.name for t in BUILTIN_GENERAL_TOOLS}

# 主助理 MUST 含的调度工具(过滤副作用时不能误伤调度能力)
_ASSISTANT_DISPATCH_TOOLS = {
    "delegate_to_subagent",
    "delegate_to_specialist",
}

_ASSISTANT_DISCOVERY_TOOLS = {
    "search_tools",
    "get_tool_detail",
}


class TestAssistantToolIsolation:
    """主助理工具集边界——100% 调度的硬保证,不靠 prompt 自觉。"""

    def test_assistant_excludes_all_builtin_general_tools(self, in_memory_db, orchestrator):
        """主助理工具集不含任何 builtin general 读取/抓取/进程/执行工具。"""
        names = _assistant_tools(orchestrator)
        leaked = _BUILTIN_TOOL_NAMES & names
        assert not leaked, f"主助理不该拿 builtin general 工具,却包含:{leaked}"

    def test_assistant_keeps_dispatch_tools(self, in_memory_db, orchestrator):
        """主助理仍含调度工具 delegate_to_subagent/delegate_to_specialist。"""
        names = _assistant_tools(orchestrator)
        missing = _ASSISTANT_DISPATCH_TOOLS - names
        assert not missing, f"主助理该保留调度工具,却缺失:{missing}"

    def test_assistant_keeps_discovery_tools(self, in_memory_db, orchestrator):
        """主助理仍含能力目录发现工具,但不能直接执行被激活能力。"""
        names = _assistant_tools(orchestrator)
        missing = _ASSISTANT_DISCOVERY_TOOLS - names
        assert not missing, f"主助理该保留能力目录发现工具,却缺失:{missing}"

    def test_executor_still_includes_side_effect_tools(self, in_memory_db, orchestrator):
        """delegated executor 仍含全量 builtin 工具——防主助理隔离误伤执行层。"""
        factory = orchestrator._build_delegated_executor_tools(
            None,
            agent_type=AgentType.SPECIALIST,
            specialist_id="spec-guard",
            role_kind="executor",
        )
        names = _tool_names(factory)
        assert "write_file" in names
        assert "exec" in names
        assert "web_fetch" in names

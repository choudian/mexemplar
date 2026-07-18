"""
032 T006/T011: 委派工具 context_message_indexes 行为契约。

- delegate_to_subagent:合法引用合并展开块进 execution_context;
  非法/无快照/超限整体 fail-closed(error JSON,dispatch_callback 不被调用);
  不带新参数时行为与现状一致(向后兼容)。
- schema:新参数存在、required 不变、description 含硬约束关键语义。
"""

import json
from unittest.mock import MagicMock, patch

from src.business.agents.delegation_context import (
    EXPANDED_CONTEXT_HEADER,
    use_llm_messages_snapshot,
)

SESSION_ID = "test-session-032"

SNAPSHOT = [
    {"role": "system", "content": "你是助理。"},
    {"role": "user", "content": "给我出一个部署方案"},
    {"role": "assistant", "content": "方案全文：第一步…第二步…第三步…"},
    {"role": "user", "content": "把这个方案写到 docs/plan.md"},
]


def _patch_max_chars(value: int = 30000):
    config = MagicMock()
    config.get_agent_tools_delegation_context_expansion_max_chars.return_value = value
    return patch(
        "src.business.agents.delegation_context.get_unified_config",
        return_value=config,
    )


class TestDelegateToSubagentContextIndexes:
    def _handler(self, callback):
        from src.business.agents.tools.assistant_tools import (
            create_delegate_to_subagent_handler,
        )

        return create_delegate_to_subagent_handler(SESSION_ID, dispatch_callback=callback)

    def test_valid_indexes_merge_expanded_block_into_execution_context(self):
        callback = MagicMock(return_value={"success": True})
        handler = self._handler(callback)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            result = handler(
                task_description="把方案写到 docs/plan.md",
                execution_context="目标路径 docs/plan.md",
                context_message_indexes=[3],
            )

        assert json.loads(result)["success"] is True
        merged = callback.call_args.kwargs["execution_context"]
        assert merged.startswith("目标路径 docs/plan.md")
        assert EXPANDED_CONTEXT_HEADER in merged
        assert "方案全文：第一步…第二步…第三步…" in merged
        assert "--- 消息 #3（assistant）---" in merged

    def test_indexes_without_execution_context_still_expand(self):
        callback = MagicMock(return_value={"success": True})
        handler = self._handler(callback)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            handler(task_description="写文件", context_message_indexes=[2, 3])

        merged = callback.call_args.kwargs["execution_context"]
        assert merged.startswith(EXPANDED_CONTEXT_HEADER)
        assert "给我出一个部署方案" in merged

    def test_no_indexes_keeps_legacy_behavior(self):
        callback = MagicMock(return_value={"success": True})
        handler = self._handler(callback)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            handler(task_description="写文件", execution_context="原样上下文")

        merged = callback.call_args.kwargs["execution_context"]
        assert merged == "原样上下文"
        assert EXPANDED_CONTEXT_HEADER not in merged

    def test_out_of_range_fail_closed_without_dispatch(self):
        callback = MagicMock()
        handler = self._handler(callback)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            result = handler(task_description="写文件", context_message_indexes=[99])

        data = json.loads(result)
        assert data["success"] is False
        assert "99" in data["message"]
        callback.assert_not_called()

    def test_system_message_fail_closed_without_dispatch(self):
        callback = MagicMock()
        handler = self._handler(callback)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            result = handler(task_description="写文件", context_message_indexes=[1])

        data = json.loads(result)
        assert data["success"] is False
        assert "system" in data["message"]
        callback.assert_not_called()

    def test_no_snapshot_fail_closed_with_guidance(self):
        callback = MagicMock()
        handler = self._handler(callback)

        with _patch_max_chars():
            result = handler(task_description="写文件", context_message_indexes=[1])

        data = json.loads(result)
        assert data["success"] is False
        assert "execution_context" in data["message"]
        callback.assert_not_called()

    def test_over_limit_fail_closed(self):
        callback = MagicMock()
        handler = self._handler(callback)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars(10):
            result = handler(task_description="写文件", context_message_indexes=[3])

        assert json.loads(result)["success"] is False
        callback.assert_not_called()

    def test_limit_applies_only_to_system_expanded_block(self):
        callback = MagicMock(return_value={"success": True})
        handler = self._handler(callback)
        merged_config = MagicMock()
        merged_config.get_agent_tools_delegation_context_expansion_max_chars.return_value = 120

        with (
            use_llm_messages_snapshot(SNAPSHOT),
            _patch_max_chars(120),
            patch(
                "src.data.unified_config.get_unified_config",
                return_value=merged_config,
            ),
        ):
            result = handler(
                task_description="写文件",
                execution_context="x" * 100,
                context_message_indexes=[2],
            )

        assert json.loads(result)["success"] is True
        callback.assert_called_once()


class TestDelegateToSpecialistContextIndexes:
    def _handler(self, callback):
        from src.business.agents.tools.assistant_tools import (
            create_delegate_to_specialist_handler,
        )

        return create_delegate_to_specialist_handler(SESSION_ID, dispatch_callback=callback)

    def test_valid_indexes_merge_into_execution_context(self):
        callback = MagicMock(return_value={"success": True})
        handler = self._handler(callback)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            result = handler(
                specialist_name="文档专员",
                task="把方案写到 docs/plan.md",
                execution_context="目标路径 docs/plan.md",
                context_message_indexes=[3],
            )

        assert json.loads(result)["success"] is True
        merged = callback.call_args.kwargs["execution_context"]
        assert merged.startswith("目标路径 docs/plan.md")
        assert EXPANDED_CONTEXT_HEADER in merged
        assert "方案全文：第一步…第二步…第三步…" in merged

    def test_no_new_params_keeps_legacy_callback_shape(self):
        callback = MagicMock(return_value={"success": True})
        handler = self._handler(callback)

        handler(specialist_name="文档专员", task="做点什么")

        assert callback.call_args.kwargs["execution_context"] == ""
        assert callback.call_args.kwargs["task"] == "做点什么"

    def test_invalid_index_fail_closed_without_dispatch(self):
        callback = MagicMock()
        handler = self._handler(callback)

        with use_llm_messages_snapshot(SNAPSHOT), _patch_max_chars():
            result = handler(
                specialist_name="文档专员",
                task="写文件",
                context_message_indexes=[0],
            )

        assert json.loads(result)["success"] is False
        callback.assert_not_called()

    def test_schema_has_new_optional_params_and_required_unchanged(self):
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SPECIALIST_SCHEMA

        params = DELEGATE_TO_SPECIALIST_SCHEMA["function"]["parameters"]
        assert params["properties"]["execution_context"]["type"] == "string"
        assert params["properties"]["context_message_indexes"]["type"] == "array"
        assert params["required"] == ["specialist_name", "task"]
        indexes_desc = params["properties"]["context_message_indexes"]["description"]
        assert "对话历史" in indexes_desc and "禁止" in indexes_desc
        assert "system" in indexes_desc and "不得引用" in indexes_desc


class TestDelegateToSubagentSchema:
    def test_schema_has_context_message_indexes(self):
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SUBAGENT_SCHEMA

        props = DELEGATE_TO_SUBAGENT_SCHEMA["function"]["parameters"]["properties"]
        assert props["context_message_indexes"]["type"] == "array"
        assert props["context_message_indexes"]["items"]["type"] == "integer"

    def test_required_unchanged(self):
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SUBAGENT_SCHEMA

        assert DELEGATE_TO_SUBAGENT_SCHEMA["function"]["parameters"]["required"] == [
            "task_description"
        ]

    def test_descriptions_carry_hard_constraint_semantics(self):
        """约束写在工具 description(不进 system prompt):关键词级断言,不做整段快照"""
        from src.business.agents.tools.assistant_tools import DELEGATE_TO_SUBAGENT_SCHEMA

        props = DELEGATE_TO_SUBAGENT_SCHEMA["function"]["parameters"]["properties"]
        indexes_desc = props["context_message_indexes"]["description"]
        assert "对话历史" in indexes_desc
        assert "禁止" in indexes_desc
        assert "system" in indexes_desc and "不得引用" in indexes_desc
        assert "1" in indexes_desc  # 1-based 计数说明
        task_desc = props["task_description"]["description"]
        assert "context_message_indexes" in task_desc or "对话历史" in task_desc

    def test_execution_context_descriptions_carry_handoff_constraint(self):
        """两个委派入口的 execution_context 字段都必须独立说明交接约束。"""
        from src.business.agents.tools.assistant_tools import (
            DELEGATE_TO_SPECIALIST_SCHEMA,
            DELEGATE_TO_SUBAGENT_SCHEMA,
        )

        for schema in (DELEGATE_TO_SUBAGENT_SCHEMA, DELEGATE_TO_SPECIALIST_SCHEMA):
            description = schema["function"]["parameters"]["properties"]["execution_context"][
                "description"
            ]
            assert "看不到" in description and "对话历史" in description
            assert "context_message_indexes" in description
            assert "禁止只写指代" in description

    def test_build_task_graph_node_description_self_contained_constraint(self):
        """build_task_graph 节点描述字段:自包含 + 看不到对话历史 + 禁止指代"""
        from src.business.agents.tools.assistant_tools import BUILD_TASK_GRAPH_SCHEMA

        node_props = BUILD_TASK_GRAPH_SCHEMA["function"]["parameters"]["properties"]["nodes"][
            "items"
        ]["properties"]
        desc = node_props["description"]["description"]
        assert "自包含" in desc
        assert "对话历史" in desc
        assert "禁止" in desc

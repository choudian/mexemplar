"""蒸馏 prompt 语义约束回归测试。

只断言关键语义与 phase 边界，不做整段字符串快照——见 ``src/CLAUDE.md``「Brain Service 约束」：
证据数量/质量规则由 prompt 引导（advisory），不是 schema 或业务层硬校验。因此本文件验证
「规则存在且 phase 边界正确」，而非锁死具体示例文案。
"""

import pytest
from unittest.mock import MagicMock

from src.business.brain.distillation_service import DistillationService
from src.utils.events import clear_all


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


@pytest.fixture
def service():
    return DistillationService(repo=MagicMock(), config=MagicMock())


# 主蒸馏 prompt 应包含的 advisory 质量规则关键短语（规则名/核心词，非示例整句）。
_MAIN_PROMPT_RULES = [
    "忠实原意",  # 质量标准 4
    "加码",  # 反加码规则核心词
    "助理的发挥",  # 归因准确性规则
    "助理的行为",  # 归因准确性规则
    "去重校验",  # 去重段落标题
]


class TestDistillationPromptQualityRules:
    """主蒸馏 prompt 包含 advisory 质量规则（关键语义，非整句快照）。"""

    @pytest.mark.parametrize("phase", ["p1", "p4"])
    @pytest.mark.parametrize("needle", _MAIN_PROMPT_RULES)
    def test_main_prompt_contains_rule(self, service, phase, needle):
        assert needle in service._build_distillation_prompt(phase=phase)


class TestDistillationPromptGeneralizationThreshold:
    """持久区要求跨对话证据（至少 2 次不同对话）——advisory 规则存在性。"""

    @pytest.mark.parametrize("phase", ["p1", "p4"])
    def test_persistent_zone_requires_cross_conversation(self, service, phase):
        assert "2 次不同对话" in service._build_distillation_prompt(phase=phase)


class TestDistillationPromptNoToolName:
    """prompt 不硬编码 tool 名称（模型经 API tools 参数获知工具）。"""

    @pytest.mark.parametrize("phase", ["p1", "p2", "p4"])
    def test_main_prompt_does_not_contain_tool_name(self, service, phase):
        assert "distillation_output" not in service._build_distillation_prompt(phase=phase)

    def test_subconscious_prompt_does_not_contain_tool_name(self, service):
        from src.business.brain.distillation_service import (
            SUBCONSCIOUS_DISTILLATION_TOOL_SCHEMA,
        )

        schema_name = SUBCONSCIOUS_DISTILLATION_TOOL_SCHEMA["name"]
        # 真测潜意识 prompt（非主 prompt），确保 schema name 未泄漏进 prompt 文本
        prompt = service._build_subconscious_prompt()
        assert schema_name not in prompt


class TestDistillationPromptPhaseAwareZones:
    """phase-aware zone 结构（zone 名存在性，关键语义边界）。"""

    def test_p1_only_has_hot_and_persistent(self, service):
        prompt = service._build_distillation_prompt(phase="p1")
        assert "hot_zone" in prompt
        assert "persistent_zone" in prompt
        assert "archive_zone" not in prompt
        assert "subconscious_zone" not in prompt
        assert "failure_zone" not in prompt

    def test_p2_adds_archive(self, service):
        prompt = service._build_distillation_prompt(phase="p2")
        assert "hot_zone" in prompt
        assert "persistent_zone" in prompt
        assert "archive_zone" in prompt
        assert "subconscious_zone" not in prompt
        assert "failure_zone" not in prompt

    def test_p4_adds_subconscious_and_failure(self, service):
        prompt = service._build_distillation_prompt(phase="p4")
        for zone in (
            "hot_zone",
            "persistent_zone",
            "archive_zone",
            "subconscious_zone",
            "failure_zone",
        ):
            assert zone in prompt


class TestSubconsciousPromptConstraints:
    """潜意识 prompt 的跨对话证据自检（advisory，非 schema 硬保证）。"""

    def test_subconscious_prompt_contains_cross_conversation_check(self, service):
        prompt = service._build_subconscious_prompt()
        assert "同一段对话" in prompt
        assert "证据自检" in prompt

    def test_subconscious_prompt_contains_attribution_guard(self, service):
        prompt = service._build_subconscious_prompt()
        assert "助理的行为模式归为用户的习惯" in prompt

    def test_subconscious_prompt_requires_multiple_conversations(self, service):
        prompt = service._build_subconscious_prompt()
        assert "至少两条不同对话" in prompt


class TestDistillationPromptEmptyResultSemantics:
    """空结果语义保留。"""

    @pytest.mark.parametrize("phase", ["p1", "p4"])
    def test_prompt_allows_empty(self, service, phase):
        prompt = service._build_distillation_prompt(phase=phase)
        assert "留空数组" in prompt
        assert "不要为了填满而提取" in prompt

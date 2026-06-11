"""
引用处理器

会话内大体积 tool result 的运行时引用替换已停用。当前处理器只负责
将 Message 转换为 LLM API 消息格式，避免旧引用机制把工具结果替换成
纯指针后诱发 load_reference 循环。
"""

import json
from typing import List

from src.data.models_sqlite import Message
from src.data.unified_config import UnifiedConfigManager

_USER_ROLES = frozenset({"summary", "program", "agent"})


class ReferenceHandler:
    """引用处理逻辑：当前保留完整 tool result，不做运行时指针替换。"""

    def __init__(self, config: UnifiedConfigManager):
        """
        初始化引用处理器

        Args:
            config: 统一配置管理器
        """
        self.steps_threshold = config.get_memory_reference_steps_threshold()
        self.size_threshold = config.get_memory_reference_size_threshold()

    def apply_replacements(self, messages: List[Message]) -> List[dict]:
        """
        输入有序消息列表，输出 LLM 格式的消息列表。

        旧实现会在每次上下文组装时按 size/steps 阈值把历史 tool result
        重新替换为 ``REF::`` 纯指针。该机制会让 search/fetch 等工具结果
        在 load_reference 后再次被归档，造成模型反复恢复同一引用。
        Phase 1 先停用会话内替换，让工具结果直接留在上下文中。

        Args:
            messages: 按序列号排序的消息列表

        Returns:
            LLM API 格式的消息列表
        """
        return [self._to_llm_format(msg) for msg in messages]

    def _to_llm_format(self, msg: Message) -> dict:
        """
        将 Message 对象转换为 LLM API 格式

        Args:
            msg: Message 对象

        Returns:
            LLM API 格式的消息字典
        """
        # summary / program / agent 角色映射为 user 发给 LLM
        # - summary: 压缩摘要，属于用户侧上下文
        # - program: 程序自动追加的指令（如分诊修复通知）
        # - agent: agent 间传递的消息
        llm_role = "user" if msg.role in _USER_ROLES else msg.role
        content = msg.content

        if msg.role == "assistant":
            # assistant 可能只有 tool_calls，content 为 None
            if content is None:
                content = ""
        else:
            content = content or ""

        result = {"role": llm_role, "content": content}

        if msg.role == "tool":
            if msg.tool_call_id:
                result["tool_call_id"] = msg.tool_call_id
            if msg.tool_name:
                result["name"] = msg.tool_name

        if msg.role == "assistant" and msg.tool_calls:
            result["tool_calls"] = json.loads(msg.tool_calls)

        return result

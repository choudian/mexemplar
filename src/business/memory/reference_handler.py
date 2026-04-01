"""
引用替换处理器

将旧的大体积 tool result 替换为指针，短期记忆机制。
"""

import json
import logging
from typing import List

from src.data.models_sqlite import Message
from src.data.unified_config import UnifiedConfigManager

logger = logging.getLogger(__name__)


class ReferenceHandler:
    """引用替换逻辑：将旧的大体积 tool result 替换为指针。"""

    def __init__(self, config: UnifiedConfigManager):
        """
        初始化引用替换处理器

        Args:
            config: 统一配置管理器
        """
        self.steps_threshold = config.get_memory_reference_steps_threshold()
        self.size_threshold = config.get_memory_reference_size_threshold()

    def apply_replacements(self, messages: List[Message]) -> List[dict]:
        """
        输入有序消息列表，输出 LLM 格式的消息列表，其中符合条件的
        tool result 被替换为指针。

        算法：
        1. 遍历消息，对每条 role=tool 的消息
        2. 计算其后有多少条 role=assistant 消息
        3. 如果 >= steps_threshold 且 len(content) >= size_threshold
           将 content 替换为指针文本

        Args:
            messages: 按序列号排序的消息列表

        Returns:
            LLM API 格式的消息列表
        """
        result = []

        for i, msg in enumerate(messages):
            # 先转换为 LLM 格式
            llm_msg = self._to_llm_format(msg)

            # 只对 tool 角色应用引用替换
            if msg.role == "tool":
                content = msg.content or ""
                if len(content) >= self.size_threshold:
                    # 计算后续 assistant 消息数量
                    assistant_count = self._count_assistant_steps_after(messages, i)

                    # 如果超过阈值，替换为指针
                    if assistant_count >= self.steps_threshold:
                        llm_msg["content"] = self._make_pointer(msg.message_id, len(content))
                        logger.debug(
                            f"[引用替换] {msg.message_id}: "
                            f"{len(content)}字符 → 指针 (后续{assistant_count}条assistant消息)"
                        )

            result.append(llm_msg)

        return result

    def _make_pointer(self, message_id: str, original_size: int) -> str:
        """生成指针文本"""
        return f"[REF::{message_id}] 此工具结果已归档（原始大小: {original_size}字符）。如需查看原始数据，请调用 load_reference(\"{message_id}\")"

    def _count_assistant_steps_after(self, messages: List[Message], tool_index: int) -> int:
        """
        计算指定位置之后的 assistant 消息数量

        Args:
            messages: 消息列表
            tool_index: tool 消息的索引

        Returns:
            后续的 assistant 消息数量
        """
        return sum(1 for msg in messages[tool_index + 1:] if msg.role == "assistant")

    def _to_llm_format(self, msg: Message) -> dict:
        """
        将 Message 对象转换为 LLM API 格式

        Args:
            msg: Message 对象

        Returns:
            LLM API 格式的消息字典
        """
        # summary 角色映射为 user 发给 LLM（压缩摘要是之前对话的总结，属于用户侧上下文）
        llm_role = "user" if msg.role == "summary" else msg.role
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
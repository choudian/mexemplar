"""
上下文管理器

Agent Loop 与记忆系统的唯一接口。
负责上下文组装、消息持久化、引用加载、会话管理。
"""

import json
import logging
import threading
import uuid
from typing import List, Optional, Dict

from src.data.repositories import (
    SessionRepository,
    MessageRepository,
)
from src.data.models_sqlite import Message
from src.data.unified_config import UnifiedConfigManager
from .reference_handler import ReferenceHandler
from .compression_handler import CompressionHandler

logger = logging.getLogger(__name__)


class ContextManager:
    """Agent Loop 与记忆系统的唯一接口。"""

    def __init__(self, session_id: str, config: UnifiedConfigManager):
        """
        初始化上下文管理器

        Args:
            session_id: 会话 ID
            config: 统一配置管理器
        """
        self.session_id = session_id

        # 初始化 Repository
        self._msg_repo = MessageRepository()
        self._session_repo = SessionRepository()

        # 初始化引用处理器（当前只做 LLM 消息格式转换）
        self._reference_handler = ReferenceHandler(config)

        # 初始化压缩处理器
        self._compression_handler = CompressionHandler(config)

        # load_reference 复用共享 Repository session，并发访问需串行化；
        # 锁与受保护的资源同位（见 load_reference）。
        self._reference_lock = threading.Lock()

    # --- 上下文组装 ---

    def assemble_context(self) -> List[Dict]:
        """
        加载会话消息，按需压缩并转换为 LLM API 格式的消息列表。

        流程：
        1. 从 DB 加载非 archived 消息（按 sequence 排序）
        2. 检查是否需要压缩 → 如需要，执行压缩，重新加载
        3. 清理孤立 tool result（压缩后、格式转换前）
        4. 转换为 LLM API 格式

        Returns:
            LLM API 格式的消息列表
        """
        # 1. 加载消息
        messages = self._msg_repo.get_context(self.session_id)

        # 2. 检查是否需要压缩
        if messages:
            if self._compression_handler.should_compress(messages):
                logger.info(f"[上下文] 会话 {self.session_id} 触发压缩")
                self._compression_handler.compress(self.session_id, messages, self._msg_repo)
                # 重新加载消息
                messages = self._msg_repo.get_context(self.session_id)

        # 3. 清理孤立 tool result
        messages = self._cleanup_orphan_tool_results(messages)

        # 4. 转换为 LLM API 格式
        llm_messages = self._reference_handler.apply_replacements(messages)

        logger.debug(f"[上下文] 已组装 {len(llm_messages)} 条消息")
        return llm_messages

    def _cleanup_orphan_tool_results(self, messages: List[Message]) -> List[Message]:
        """检测并剔除孤立的 tool result 消息。

        孤立 tool result 是指 tool_call_id 不在任意 assistant(tool_calls) 中出现的
        tool 消息。这通常由压缩边界调整遗漏导致。

        清理不影响 get_pending_tool_calls 的语义：只移除 tool 消息，
        不修改 assistant(tool_calls)。
        """
        # 收集所有 assistant(tool_calls) 中的 id
        valid_tc_ids = set()
        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                try:
                    for tc in json.loads(msg.tool_calls):
                        tc_id = tc.get("id")
                        if tc_id:
                            valid_tc_ids.add(tc_id)
                except (json.JSONDecodeError, TypeError):
                    pass

        if not valid_tc_ids:
            # 没有 assistant(tool_calls)，所有 tool 消息都是孤立的
            orphan_count = sum(1 for m in messages if m.role == "tool")
            if orphan_count > 0:
                logger.warning(
                    f"[上下文] 发现 {orphan_count} 个孤立 tool result（无对应 assistant），已剔除"
                )
                return [m for m in messages if m.role != "tool"]
            return messages

        # 过滤孤立 tool result
        cleaned = []
        orphan_count = 0
        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id not in valid_tc_ids:
                orphan_count += 1
                continue
            cleaned.append(msg)

        if orphan_count > 0:
            logger.warning(f"[上下文] 发现 {orphan_count} 个孤立 tool result，已剔除")

        return cleaned

    # --- 消息持久化 ---

    def save_message(
        self,
        role: str,
        content: Optional[str],
        tool_call_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_calls: Optional[str] = None,
    ) -> Message:
        """
        保存消息，自动分配 sequence

        Args:
            role: 消息角色（'system' | 'user' | 'assistant' | 'tool'）
            content: 消息内容
            tool_call_id: 工具调用 ID（tool 角色必需）
            tool_name: 工具名称（tool 角色）
            tool_calls: 工具调用列表 JSON（assistant 角色）

        Returns:
            保存的消息对象
        """
        sequence = self._msg_repo.get_next_sequence(self.session_id)

        msg = Message(
            message_id=str(uuid.uuid4()),
            session_id=self.session_id,
            sequence=sequence,
            role=role,
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_calls=tool_calls,
        )

        return self._msg_repo.create(msg)

    def save_user_message(self, content: str) -> Message:
        """便捷方法：保存用户消息"""
        return self.save_message(role="user", content=content)

    def save_assistant_message(
        self,
        content: Optional[str],
        tool_calls: Optional[str] = None,
    ) -> Message:
        """便捷方法：保存 assistant 消息"""
        return self.save_message(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
        )

    def save_tool_result(
        self,
        tool_call_id: str,
        tool_name: str,
        content: str,
    ) -> Message:
        """便捷方法：保存工具结果"""
        return self.save_message(
            role="tool",
            content=content,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        )

    def get_last_message(self):
        """获取最后一条非归档消息（用于判断是否需要等待用户输入）"""
        return self._msg_repo.get_last(self.session_id)

    def get_pending_tool_calls(self) -> List[dict]:
        """
        检测 session 中所有未配对的工具调用。

        遍历全部消息做完整匹配。损坏的 tool call（缺少 name）以占位名称保留，
        以便调用方生成配对错误结果，避免未配对的 tool call 遗留在历史中。

        Returns:
            [{"id": ..., "name": ..., "args": {...}}, ...] 或 []
        """
        messages = self._msg_repo.get_context(self.session_id)
        tool_result_ids = set()
        pending_assistant_msgs = []

        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id:
                tool_result_ids.add(msg.tool_call_id)
            if msg.role == "assistant" and msg.tool_calls:
                pending_assistant_msgs.append(msg)

        if not pending_assistant_msgs:
            return []

        pending_calls = []
        for msg in pending_assistant_msgs:
            try:
                tcs = json.loads(msg.tool_calls)
            except Exception:
                logger.debug(f"[上下文] 解析 tool_calls 失败: {msg.tool_calls!r}")
                continue
            for tc in tcs:
                tc_id = tc.get("id", "")
                if not tc_id or tc_id in tool_result_ids:
                    continue
                if "name" not in tc:
                    logger.warning(f"[上下文] tool call 缺少 name 字段: {tc}")
                    tc = {**tc, "name": "__corrupted_tool_call__"}
                pending_calls.append(tc)

        return pending_calls

    # --- 引用加载 ---

    def load_reference(self, reference_id: str) -> str:
        """
        加载显式 REF 指向的原始内容。供 load_reference 工具调用。

        根据 ID 前缀路由到不同的存储：
        - ss_* / gs_* / global_* → assistant_summaries 表（跨会话记忆摘要）
        - 其他（msg_* 等） → messages 表（会话内消息）

        Args:
            reference_id: 引用 ID（消息 ID 或摘要 ID）

        Returns:
            原始内容文本

        Raises:
            ValueError: 如果引用不存在
        """
        # load_reference 复用共享 MessageRepository session（见 __init__），
        # 并发工具调用时必须串行化访问。
        with self._reference_lock:
            # 摘要 ID 路由：ss_ (会话摘要), gs_ (分组摘要), global_ (全局摘要)
            if reference_id.startswith(("ss_", "gs_", "global_")):
                from src.data.repositories import AssistantSummaryRepository

                summary = AssistantSummaryRepository().get_by_summary_id(reference_id)
                if not summary:
                    raise ValueError(f"摘要不存在: {reference_id}")
                logger.info(f"[引用加载] 摘要 {reference_id}: {len(summary.content or '')} 字符")
                return summary.content or ""

            # 消息 ID 路由（默认路径）
            msg = self._msg_repo.get_by_id(reference_id)
            if not msg:
                raise ValueError(f"消息不存在: {reference_id}")

            logger.info(f"[引用加载] {reference_id}: {len(msg.content or '')} 字符")
            return msg.content or ""

    # --- 会话管理 ---

    def get_session_status(self) -> Optional[str]:
        """获取会话状态"""
        return self._session_repo.get_status(self.session_id)

    def update_session_status(self, status: str):
        """
        更新会话状态

        Args:
            status: 会话状态（'active' | 'completed' | 'suspended' | 'failed'）
        """
        self._session_repo.update_status(self.session_id, status)
        logger.debug(f"[会话] {self.session_id} 状态更新为 {status}")

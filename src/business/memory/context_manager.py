"""
上下文管理器

Agent Loop 与记忆系统的唯一接口。
负责上下文组装、消息持久化、引用加载、会话管理。
"""

import json
import logging
import uuid
from typing import List, Optional, Dict

from src.data.repositories import (
    SessionRepository,
    MessageRepository,
    WorkflowTransitionRepository,
)
from src.data.models_sqlite import Session, Message, WorkflowTransition
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
        self._config = config

        # 初始化 Repository
        self._msg_repo = MessageRepository()
        self._session_repo = SessionRepository()
        self._wf_repo = WorkflowTransitionRepository()

        # 初始化引用替换处理器
        self._reference_handler = ReferenceHandler(config)

        # 初始化压缩处理器
        self._compression_handler = CompressionHandler(config)

    # --- 上下文组装 ---

    def assemble_context(self) -> List[Dict]:
        """
        加载会话消息，按需压缩，应用引用替换，返回 LLM API 格式的消息列表。

        流程：
        1. 从 DB 加载非 archived 消息（按 sequence 排序）
        2. 检查是否需要压缩 → 如需要，执行压缩，重新加载
        3. 对 tool result 消息应用引用替换
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

        # 3. 应用引用替换
        llm_messages = self._reference_handler.apply_replacements(messages)

        logger.debug(f"[上下文] 已组装 {len(llm_messages)} 条消息")
        return llm_messages

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

    def get_pending_tool_call(self) -> Optional[dict]:
        """
        检测 session 是否有待重试的工具调用。

        当 execute_tool 失败且 save_result=False 时，最后一条消息是 assistant 的
        tool_calls（无对应 tool result）。重启后 AgentLoop 可直接重执行，无需再问 LLM。

        Returns:
            {"id": ..., "name": ..., "args": {...}} 或 None
        """
        last = self._msg_repo.get_last(self.session_id)
        if last and last.role == "assistant" and last.tool_calls:
            try:
                tcs = json.loads(last.tool_calls)
                if tcs:
                    if len(tcs) > 1:
                        logger.warning(f"[上下文] session {self.session_id} 有多个待重试 tool call，只取第一个")
                    tc = tcs[0]
                    if "name" not in tc:
                        logger.warning(f"[上下文] 待重试 tool call 缺少 name 字段: {tc}")
                        return None
                    return tc
            except Exception:
                logger.debug(f"[上下文] 解析 tool_calls 失败: {last.tool_calls!r}")
        return None

    # --- 引用加载 ---

    def load_reference(self, reference_id: str) -> str:
        """
        加载被引用替换的原始内容。供 load_reference 工具调用。

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

    def fork_session(self, fork_at_sequence: int) -> str:
        """
        从指定位置分叉会话，返回新 session_id

        Args:
            fork_at_sequence: 分叉位置（保留该序号之前的消息）

        Returns:
            新会话 ID
        """
        # 获取原会话信息
        old_session = self._session_repo.get_by_id(self.session_id)
        if not old_session:
            raise ValueError(f"会话不存在: {self.session_id}")

        # 创建新会话
        new_session = Session(
            session_id=str(uuid.uuid4()),
            workflow_id=old_session.workflow_id,
            agent_type=old_session.agent_type,
            status="active",
        )
        self._session_repo.create(new_session)

        # 复制消息
        self._msg_repo.bulk_copy(
            from_session_id=self.session_id,
            to_session_id=new_session.session_id,
            up_to_sequence=fork_at_sequence,
        )

        logger.info(
            f"[会话] 从 {self.session_id} 分叉到 {new_session.session_id} "
            f"(保留前 {fork_at_sequence} 条消息)"
        )

        return new_session.session_id

    # --- 交接记录 ---

    def record_transition(
        self,
        to_session_id: str,
        event_type: str,
        payload: Optional[Dict] = None,
    ):
        """
        记录 Agent 之间的交接事件

        Args:
            to_session_id: 目标会话 ID
            event_type: 事件类型
            payload: 交接携带的关键数据摘要
        """
        # 获取当前会话的 workflow_id
        current_session = self._session_repo.get_by_id(self.session_id)
        if not current_session:
            raise ValueError(f"会话不存在: {self.session_id}")

        transition = WorkflowTransition(
            transition_id=str(uuid.uuid4()),
            workflow_id=current_session.workflow_id,
            from_session_id=self.session_id,
            to_session_id=to_session_id,
            event_type=event_type,
            payload=json.dumps(payload) if payload else None,
        )

        self._wf_repo.create(transition)
        logger.info(
            f"[交接] {self.session_id} → {to_session_id} "
            f"(事件: {event_type})"
        )
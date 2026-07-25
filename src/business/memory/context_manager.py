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

from src.data.repos.base_repository import ID_PREFIX_ADJUDICATION, ID_PREFIX_GRAPH, ID_PREFIX_TASK
from src.data.repositories import (
    SessionRepository,
    MessageRepository,
)
from src.data.models_sqlite import Message
from src.data.unified_config import UnifiedConfigManager
from src.utils.helpers import positive_int
from src.utils.timezone import to_local
from .reference_handler import ReferenceHandler
from .compression_handler import CompressionHandler
from .tool_result_budget import ToolResultBudget

logger = logging.getLogger(__name__)

# 配置读不出数字时的并发工具结果总预算，与 unified_config 默认值一致。
_DEFAULT_TOOL_RESULT_GROUP_BUDGET = 24000

# 低于这个值的预算一定是配错了：单条工具结果的可见上限就有 12000 字符，
# 预算小于一条结果的量级只会把每条结果都截成预览。踩过两次——mock 配置
# 未显式赋值时 int(MagicMock()) 返回 1，静默把预算变成 1 字符。
_MIN_SANE_TOOL_RESULT_GROUP_BUDGET = 1000


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

        # 并发工具结果的单批总预算：每条都不超单条上限、加起来仍可撑爆一条消息
        self._tool_result_budget = ToolResultBudget(
            positive_int(
                config.get_memory_tool_result_group_budget(),
                default=_DEFAULT_TOOL_RESULT_GROUP_BUDGET,
                minimum=_MIN_SANE_TOOL_RESULT_GROUP_BUDGET,
            )
        )

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
        5. 为首条及跨日后的首条用户消息注入本地日期

        Returns:
            LLM API 格式的消息列表
        """
        # 1. 加载消息
        messages = self._msg_repo.get_context(self.session_id)

        # 2. 先按并发批次裁剪超预算的工具结果（零模型调用），再判断是否需要压缩。
        # 顺序不能反：裁剪可能已把上下文降到阈值以下，先压缩就白花一次 LLM 调用。
        if messages:
            self._tool_result_budget.apply(self.session_id, messages, self._msg_repo)

        # 3. 检查是否需要压缩
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

        # 5. 仅修改本次 LLM 请求，不改 DB 中保存的用户原话
        self._inject_user_message_dates(messages, llm_messages)

        logger.debug(f"[上下文] 已组装 {len(llm_messages)} 条消息")
        return llm_messages

    @staticmethod
    def _inject_user_message_dates(
        messages: List[Message],
        llm_messages: List[Dict],
    ) -> None:
        """为首条及跨日后的首条真实用户消息添加 ``[YYYY-MM-DD]`` 前缀。"""
        # apply_replacements 当前一一对应、等长；显式比较 + log 而非 assert，
        # 因为打包后的 sidecar 可能以 -O 启动，assert 会被剥掉、长度漂移会被
        # zip 静默截断从而漏注入。长度异常时跳过注入，避免错位污染历史。
        if len(messages) != len(llm_messages):
            logger.warning(
                "[上下文] messages 与 llm_messages 长度不一致 (%s vs %s)，跳过日期注入",
                len(messages),
                len(llm_messages),
            )
            return
        previous_user_date = None

        for message, llm_message in zip(messages, llm_messages):
            if message.role != "user" or message.created_at is None:
                continue

            message_date = to_local(message.created_at).date()
            if previous_user_date is None or message_date != previous_user_date:
                llm_message["content"] = (
                    f"[{message_date.isoformat()}] {llm_message.get('content', '')}"
                )
            previous_user_date = message_date

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
        token_usage: Optional[str] = None,
    ) -> Message:
        """
        保存消息，自动分配 sequence

        Args:
            role: 消息角色（'system' | 'user' | 'assistant' | 'tool'）
            content: 消息内容
            tool_call_id: 工具调用 ID（tool 角色必需）
            tool_name: 工具名称（tool 角色）
            tool_calls: 工具调用列表 JSON（assistant 角色）
            token_usage: 本次调用的 token 用量 JSON（assistant 角色）

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
            token_usage=token_usage,
        )

        return self._msg_repo.create(msg)

    def save_user_message(self, content: str) -> Message:
        """便捷方法：保存用户消息"""
        return self.save_message(role="user", content=content)

    def save_assistant_message(
        self,
        content: Optional[str],
        tool_calls: Optional[str] = None,
        token_usage: Optional[str] = None,
    ) -> Message:
        """便捷方法：保存 assistant 消息"""
        return self.save_message(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
            token_usage=token_usage,
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
        - 其他（msg_* 等） → messages 表（执行体限当前会话；主助理可跨会话下钻）

        Args:
            reference_id: 引用 ID（消息 ID 或摘要 ID）

        Returns:
            原始内容文本

        Raises:
            ValueError: 引用类型不受支持、引用不存在，或当前会话无权访问。
                消息引用的“不存在”和“无权访问”故意使用同一错误文案，
                避免向权限较窄的执行体泄露其他会话中的消息是否存在。
        """
        # load_reference 复用共享 MessageRepository session（见 __init__），
        # 并发工具调用时必须串行化访问。
        with self._reference_lock:
            reference_id = (reference_id or "").strip()
            if reference_id.startswith(ID_PREFIX_TASK):
                raise ValueError(
                    f"{reference_id} 是任务 ID，不是 message/summary reference；"
                    "请根据回流提示使用裁定工具处理任务结果，不要传给 load_reference。"
                )
            if reference_id.startswith(ID_PREFIX_GRAPH):
                raise ValueError(
                    f"{reference_id} 是任务图 ID，不是 message/summary reference；"
                    "任务图状态应通过任务协作快照或回流提示查看，不要传给 load_reference。"
                )
            if reference_id.startswith(ID_PREFIX_ADJUDICATION):
                raise ValueError(
                    f"{reference_id} 是任务结果裁定 ID，不是 message/summary reference；"
                    f'请调用 load_task_result(adjudication_id="{reference_id}") 查看交付物。'
                )

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
            can_read_cross_session = False
            if msg and msg.session_id != self.session_id:
                current_session = self._session_repo.get_by_id(self.session_id)
                can_read_cross_session = bool(
                    current_session and current_session.agent_type == "assistant"
                )
            if not msg or (msg.session_id != self.session_id and not can_read_cross_session):
                # 主助理保留既有跨会话记忆下钻；权限更窄的执行体严格限当前会话。
                # 错误文案不区分“不存在”和“属于其他会话”，避免泄露消息存在性。
                raise ValueError(f"消息引用不存在或无权访问: {reference_id}")

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

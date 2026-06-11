"""
压缩处理器

使用 LLM 对旧消息生成摘要，会话级记忆机制。
"""

import json
import logging
import re
import uuid
from abc import ABC, abstractmethod
from typing import List, NamedTuple, Tuple, Optional

from src.business.debug.context import TraceContext
from src.data.models_sqlite import Message
from src.data.unified_config import UnifiedConfigManager

logger = logging.getLogger(__name__)


class ParsedToolCall(NamedTuple):
    tool_id: str
    func_name: str
    args: str


def _parse_tool_call(tc: dict) -> ParsedToolCall:
    """从 tool_call dict 中提取 (id, func_name, args_str)，兼容内部格式和 OpenAI 格式"""
    tool_id = tc.get("id", "")
    func_name = tc.get("name") or tc.get("function", {}).get("name", "")
    args = tc.get("args") or tc.get("function", {}).get("arguments", "")
    if isinstance(args, dict):
        args = json.dumps(args, ensure_ascii=False)
    return ParsedToolCall(tool_id, func_name, args)


class CompressionTrigger(ABC):
    """压缩触发策略基类"""

    @abstractmethod
    def should_compress(self, messages: List[Message]) -> bool:
        """判断是否应该压缩"""
        pass


class TokenTrigger(CompressionTrigger):
    """基于 token 估算的触发策略"""

    def __init__(self, threshold: int):
        self.threshold = threshold

    def should_compress(self, messages: List[Message]) -> bool:
        """根据 token 估算判断是否压缩"""
        total_tokens = sum(self._estimate_tokens(msg.content or "") for msg in messages)
        return total_tokens >= self.threshold

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """
        估算 token 数量

        使用公式：len(content) / 3 * 1.2
        中文/混合内容约 1 token/3 字符，乘 1.2 安全余量
        """
        return int(len(text) / 3 * 1.2)


class CountTrigger(CompressionTrigger):
    """基于消息条数的触发策略"""

    def __init__(self, threshold: int):
        self.threshold = threshold

    def should_compress(self, messages: List[Message]) -> bool:
        """根据消息条数判断是否压缩"""
        return len(messages) >= self.threshold


class CombinedTrigger(CompressionTrigger):
    """组合策略：任一子策略触发即触发"""

    def __init__(self, triggers: List[CompressionTrigger]):
        self.triggers = triggers

    def should_compress(self, messages: List[Message]) -> bool:
        """任一子策略触发即触发"""
        return any(trigger.should_compress(messages) for trigger in self.triggers)


class CompressionHandler:
    """会话压缩：使用 LLM 对旧消息生成摘要。"""

    # 压缩 prompt 模板
    COMPRESSION_PROMPT = """你是一个对话压缩助手。请将以下对话历史压缩为结构化摘要。

## 输出格式要求

必须包含以下章节（无内容则写"无"）：

### 关键决策
- 已做出的决策及其理由

### 技术发现
- 发现的 API 端点、数据结构、页面模式等技术细节

### 当前进展
- 任务进行到哪一步，下一步是什么

### 待确认事项
- 尚未确认或需要用户进一步输入的问题

### 标识符清单
- 必须原样保留的标识符：recording_id、session_id、tool_id、tool_call_id（如 call_xxx）、API 端点 URL、CSS 选择器、参数名、文件路径等
- 格式：每个标识符单独一行，标注用途
- **特别注意**：tool_call_id 必须原样保留，后续处理依赖它来还原工具调用详情

## 压缩规则

保留：
- 所有关键决策和结论
- 用户明确表达的需求和偏好
- 重要的技术发现和具体数据
- 所有不可重构的标识符（ID、URL、选择器、路径等）必须原样保留

不需要保留：
- 礼貌用语和过渡语
- 重复的信息
- 已被后续结论推翻的早期猜测
- 工具调用的原始数据（只保留分析结论）

--- 对话历史 ---
{messages_text}
"""

    def __init__(self, config: UnifiedConfigManager):
        """
        初始化压缩处理器

        Args:
            config: 统一配置管理器
        """
        self._config = config
        self._trigger = self._create_trigger(config)
        self.keep_recent = config.get_memory_compression_keep_recent()
        self._llm_client = None  # 懒初始化

    def _create_trigger(self, config: UnifiedConfigManager) -> CompressionTrigger:
        """
        根据配置创建触发策略

        Args:
            config: 统一配置管理器

        Returns:
            触发策略实例
        """
        strategy = config.get_memory_compression_trigger_strategy()
        token_threshold = config.get_memory_compression_token_threshold()
        count_threshold = config.get_memory_compression_count_threshold()

        if strategy == "token":
            return TokenTrigger(token_threshold)
        elif strategy == "count":
            if count_threshold is None:
                raise ValueError("count 策略需要设置 count_threshold")
            return CountTrigger(count_threshold)
        elif strategy == "combined":
            triggers = [TokenTrigger(token_threshold)]
            if count_threshold is not None:
                triggers.append(CountTrigger(count_threshold))
            return CombinedTrigger(triggers)
        else:
            raise ValueError(f"未知的压缩策略: {strategy}")

    def _get_llm_client(self):
        """
        懒初始化压缩 LLM 客户端

        Returns:
            LLM 客户端实例，如果创建失败则返回 None
        """
        if self._llm_client is None:
            try:
                from src.business.ai.llm_client import LangChainLLMClient
                from src.data.credential_resolver import (
                    get_real_tour_credential_resolver,
                    is_real_tour_runtime,
                )

                resolver = get_real_tour_credential_resolver() if is_real_tour_runtime() else None
                api_key = (
                    resolver.get_compression_model_api_key()
                    if resolver is not None
                    else self._config.get_compression_model_api_key()
                )
                self._llm_client = LangChainLLMClient(
                    provider=self._config.get_compression_model_provider(),
                    model=self._config.get_compression_model_name(),
                    api_key=api_key,
                    base_url=self._config.get_compression_model_base_url(),
                    temperature=self._config.get_compression_model_temperature(),
                    max_tokens=self._config.get_compression_model_max_tokens(),
                    timeout=self._config.get_ai_request_timeout(),
                )
            except Exception as e:
                logger.error(f"[压缩] 创建 LLM 客户端失败: {e}")
                self._llm_client = None
        return self._llm_client

    def should_compress(self, messages: List[Message]) -> bool:
        """委托给触发策略判断"""
        return self._trigger.should_compress(messages)

    def compress(self, session_id: str, messages: List[Message], msg_repo) -> List[Message]:
        """
        执行压缩：
        1. 分离 system prompt、压缩区、保留区
        2. 调用压缩 LLM 对压缩区生成摘要
        3. 后处理：将摘要中的 tool_call_id 替换为原始 tool_call 数据 + tool_result 引用
        4. 创建 compressed 消息，归档原始消息
        5. 返回更新后的消息列表

        Args:
            session_id: 会话 ID
            messages: 会话的所有非归档消息
            msg_repo: 消息仓库

        Returns:
            更新后的消息列表
        """
        # 分离消息区域
        system_msg, compress_msgs, keep_msgs = self._split_messages(messages)

        # 压缩区为空，跳过（边界调整后压缩区可能为空）
        if not compress_msgs:
            logger.debug("[压缩] 边界调整后压缩区为空，跳过压缩")
            result = []
            if system_msg:
                result.append(system_msg)
            result.extend(keep_msgs)
            return result

        # 获取 LLM 客户端
        llm_client = self._get_llm_client()
        if llm_client is None:
            logger.warning("[压缩] LLM 客户端未初始化，跳过压缩")
            return messages

        try:
            # 格式化压缩区消息
            compress_text = self._format_for_compression(compress_msgs)

            # 使用结构化摘要 prompt
            prompt = self.COMPRESSION_PROMPT.format(messages_text=compress_text)

            # 调用压缩 LLM
            logger.info(f"[压缩] 正在压缩 {len(compress_msgs)} 条消息...")
            with TraceContext(source="compression", session_id=session_id):
                summary = llm_client.chat(prompt)

            # 后处理摘要
            summary = self._post_process_summary(summary, compress_msgs)

            # 持久化压缩结果
            start_seq = compress_msgs[0].sequence
            end_seq = compress_msgs[-1].sequence

            # 创建 compressed 消息
            compressed_msg = Message(
                message_id=str(uuid.uuid4()),
                session_id=session_id,
                sequence=start_seq,  # sequence 取压缩区起始序号
                role="summary",
                content=summary,
                message_type="compressed",
                compressed_range=f"{start_seq}-{end_seq}",
            )

            # 保存 compressed 消息并归档原始消息
            msg_repo.create(compressed_msg)
            msg_repo.mark_archived(
                session_id,
                start_seq,
                end_seq,
                exclude_message_id=compressed_msg.message_id,
            )

            logger.info(
                f"[压缩] 已压缩消息 {start_seq}-{end_seq} " f"(摘要长度: {len(summary)}字符)"
            )

            # 返回更新后的消息列表
            return self._rebuild_messages(system_msg, compressed_msg, keep_msgs)

        except Exception as e:
            logger.error(f"[压缩] 压缩失败: {e}")
            # 不阻塞流程，下次重新检查
            return messages

    def _adjust_boundary_for_tool_pairs(
        self,
        compress_msgs: List[Message],
        keep_msgs: List[Message],
    ) -> Tuple[List[Message], List[Message]]:
        """将跨越压缩/保留边界的 tool 组移入保留区。

        算法：
        1. 收集 keep_msgs 中所有 tool role 消息的 tool_call_id
        2. 迭代查找 compress_msgs 中包含这些 id 的 assistant(tool_calls)
        3. 将该 assistant 及压缩区内同组的 tool result 移入 keep_msgs 前部
        4. 重复直到无新匹配（处理多组跨界情况）
        """
        keep_tc_ids = set()
        for msg in keep_msgs:
            if msg.role == "tool" and msg.tool_call_id:
                keep_tc_ids.add(msg.tool_call_id)

        if not keep_tc_ids:
            return compress_msgs, keep_msgs

        to_move = set()
        changed = True
        while changed:
            changed = False
            for i in range(len(compress_msgs) - 1, -1, -1):
                if i in to_move:
                    continue
                msg = compress_msgs[i]
                if msg.role == "assistant" and msg.tool_calls:
                    try:
                        tc_ids = {tc.get("id") for tc in json.loads(msg.tool_calls) if tc.get("id")}
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if tc_ids & keep_tc_ids:
                        to_move.add(i)
                        for j in range(i + 1, len(compress_msgs)):
                            if j in to_move:
                                continue
                            m = compress_msgs[j]
                            if m.role == "tool" and m.tool_call_id in tc_ids:
                                to_move.add(j)
                        changed = True
                        break

        if not to_move:
            return compress_msgs, keep_msgs

        new_compress = [m for i, m in enumerate(compress_msgs) if i not in to_move]
        moved = [compress_msgs[i] for i in sorted(to_move)]
        new_keep = moved + list(keep_msgs)
        return new_compress, new_keep

    def _split_messages(
        self, messages: List[Message]
    ) -> Tuple[Optional[Message], List[Message], List[Message]]:
        """
        分离消息区域：system prompt / 压缩区 / 保留区

        Args:
            messages: 按序列排序的消息列表

        Returns:
            (system_msg, compress_msgs, keep_msgs)
        """
        if not messages:
            return None, [], []

        # 第一条可能是 system prompt
        system_msg = None
        start_idx = 0

        if messages[0].role == "system":
            system_msg = messages[0]
            start_idx = 1

        # 分离压缩区和保留区
        total_count = len(messages) - start_idx
        keep_count = min(self.keep_recent, total_count)

        if total_count <= keep_count:
            # 不够压缩
            compress_start = len(messages)
        else:
            compress_start = len(messages) - keep_count

        compress_msgs = messages[start_idx:compress_start]
        keep_msgs = messages[compress_start:]

        compress_msgs, keep_msgs = self._adjust_boundary_for_tool_pairs(compress_msgs, keep_msgs)

        return system_msg, compress_msgs, keep_msgs

    def _format_for_compression(self, messages: List[Message]) -> str:
        """
        将消息格式化为可读文本，用于压缩 prompt。
        tool result 不喂完整数据，只喂工具名、参数和数据量。
        """
        lines = []

        for msg in messages:
            if msg.role == "system":
                continue

            if msg.role == "assistant" and msg.tool_calls:
                # 解析 tool_calls
                tool_calls = json.loads(msg.tool_calls)
                for tc in tool_calls:
                    tool_id, func_name, args = _parse_tool_call(tc)
                    # 格式: [Tool 调用]: {tool_name}({参数}) → {tool_call_id}
                    lines.append(f"[Tool 调用]: {func_name}({args}) → {tool_id}")
            elif msg.role == "tool":
                # tool result 精简格式
                size = len(msg.content or "")
                # 格式: [Tool 结果]: (数据量: {size}字符，详情可通过引用获取)
                lines.append(f"[Tool 结果]: (数据量: {size}字符，详情可通过引用获取)")
            elif msg.role == "user":
                content = (msg.content or "")[:500]  # 截断长消息
                lines.append(f"[User] {content}")
            elif msg.role == "assistant":
                content = (msg.content or "")[:500]
                lines.append(f"[Assistant] {content}")

        return "\n\n".join(lines)

    def _post_process_summary(self, summary: str, compress_messages: List[Message]) -> str:
        """
        后处理摘要文本：
        1. 扫描摘要中出现的 tool_call_id
        2. 从压缩区原始消息中查找对应 tool_call 数据（函数名 + 参数）
        3. 替换 tool_call_id 为完整 tool_call 信息
        4. 追加对应 tool_result 的引用指针 [REF::{message_id}]

        注意：LLM 可能不会在摘要中保留所有 tool_call_id。
        如果匹配到的 tool_call_id 数量显著少于压缩区中实际的
        tool_call 数量，记录 warning 日志（不阻塞流程）。
        未匹配的 tool_call 信息丢失可接受——Agent 的 assistant
        回复已包含关键结论，压缩的目的是保留决策而非原始数据。

        Args:
            summary: LLM 返回的原始摘要
            compress_messages: 压缩区的原始消息

        Returns:
            后处理后的摘要
        """
        # 构建 tool_call_id 到信息的映射
        tool_call_info = {}
        tool_result_refs = {}

        # 遍历压缩区消息，提取 tool_call 和 tool_result 信息
        for msg in compress_messages:
            if msg.role == "assistant" and msg.tool_calls:
                tool_calls = json.loads(msg.tool_calls)
                for tc in tool_calls:
                    tool_call_id, func_name, args = _parse_tool_call(tc)
                    tool_call_info[tool_call_id] = f"{func_name}({args})"
            elif msg.role == "tool" and msg.tool_call_id:
                tool_result_refs[msg.tool_call_id] = (
                    f"[REF::{msg.message_id}]({len(msg.content or '')}字符)"
                )

        # 检查匹配情况
        matched_count = sum(1 for tc_id in tool_call_info if tc_id in summary)
        total_count = len(tool_call_info)

        if total_count > 0 and matched_count < total_count * 0.5:
            logger.warning(
                f"[压缩] tool_call_id 匹配率低: {matched_count}/{total_count} "
                "部分工具调用信息可能丢失"
            )

        # 替换 tool_call_id
        result = summary
        for tool_call_id, call_info in tool_call_info.items():
            # 匹配 tool_call_id（可能包含 call_ 前缀）
            pattern = re.compile(r"\b" + re.escape(tool_call_id) + r"\b")
            replacement = call_info
            if tool_call_id in tool_result_refs:
                replacement += " → " + tool_result_refs[tool_call_id]
            result = pattern.sub(replacement, result)

        return result

    def _rebuild_messages(
        self, system_msg: Optional[Message], compressed_msg: Message, keep_msgs: List[Message]
    ) -> List[Message]:
        """重建消息列表"""
        result = []
        if system_msg:
            result.append(system_msg)
        result.append(compressed_msg)
        result.extend(keep_msgs)
        return result

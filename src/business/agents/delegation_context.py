"""委派上下文交接:LLM 消息快照 contextvar 与消息下标解析。

主助理委派工具的 ``context_message_indexes`` 参数按"模型本轮可见消息数组"的
1-based 下标引用历史消息;本模块负责:

- 在 AgentLoop 的 LLM 响应路径上以 contextvar 暴露本轮 assembled messages 快照
  (与 ``use_tool_runtime`` 同款模式,委派工具 ``is_concurrency_safe=False``,
  handler 在 caller thread 执行,contextvar 可见);
- 在委派工具执行瞬间按下标逐字展开原文(fail-closed:system/越界/非法/无快照/超限
  整体报错,不部分展开、不截断)。

下标是位置语义,必须对着模型产生 tool call 时看到的那份数组解析;禁止用
重新 ``assemble_context()`` 的结果替代(压缩可能已使位置漂移)。
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Optional, Sequence

from src.data.unified_config import get_unified_config

EXPANDED_CONTEXT_HEADER = "【主对话相关原文】"
# 不可见 provenance 标记：只有委派 handler 在 resolver 成功后注入，执行体输入前移除。
# 展示标题本身属于普通可输入文本，不能单独充当来源判据。
EXPANDED_CONTEXT_PROVENANCE_MARKER = "\u2063\u200b\u2063\u200c\u2063\u200d\u2063"
_EXPANDED_CONTEXT_BOUNDARY = EXPANDED_CONTEXT_HEADER + EXPANDED_CONTEXT_PROVENANCE_MARKER


@dataclass(frozen=True, slots=True)
class SnapshotMessage:
    """模型可见消息的不可变解析投影。"""

    role: str
    content: Optional[str]


LlmMessagesSnapshot = tuple[SnapshotMessage, ...]


_llm_messages_snapshot: ContextVar[Optional[LlmMessagesSnapshot]] = ContextVar(
    "llm_messages_snapshot", default=None
)


class DelegationContextError(Exception):
    """context_message_indexes 解析失败;message 面向主助理,含具体原因与重填指引。"""


@contextlib.contextmanager
def use_llm_messages_snapshot(messages: Sequence[Mapping[str, Any]]) -> Iterator[None]:
    """在工具批次期间暴露本轮送入 LLM 的不可变消息投影。"""
    snapshot = tuple(
        SnapshotMessage(
            role=str(message.get("role") or "?"),
            content=(None if message.get("content") is None else str(message.get("content"))),
        )
        for message in messages
    )
    token = _llm_messages_snapshot.set(snapshot)
    try:
        yield
    finally:
        _llm_messages_snapshot.reset(token)


def get_llm_messages_snapshot() -> Optional[LlmMessagesSnapshot]:
    return _llm_messages_snapshot.get()


def attach_expanded_context_provenance(block: str) -> str:
    """给 resolver 生成的展示块附加持久化所需的内部来源标记。"""
    if not block.startswith(EXPANDED_CONTEXT_HEADER):
        raise ValueError("expanded context block is missing its header")
    return _EXPANDED_CONTEXT_BOUNDARY + block[len(EXPANDED_CONTEXT_HEADER) :]


def prepare_delegated_execution_context(text: str) -> str:
    """为中间传输准备上下文，不提前消费展开块 provenance。

    普通上下文继续沿用 032 前的 ``strip()``；带 provenance 的展开块必须原样
    穿过 TaskExecutorAdapter/checkpoint 拼接层，留给最终执行体格式化边界消费。
    """
    context = text or ""
    return context if _EXPANDED_CONTEXT_BOUNDARY in context else context.strip()


def normalize_delegated_execution_context(text: str) -> str:
    """保留旧上下文 strip 语义，同时逐字保留系统展开块。

    ``_merge_context_message_indexes`` 总是把带内部 provenance 的展开块追加在
    普通 execution_context 之后。只有“展示标题 + provenance”共同出现才是稳定
    边界；用户普通文本里的同名标题不触发。边界之前沿用 032 前的 ``strip()``，
    展开块移除内部标记后不做任何规范化，保留消息尾随空白。
    """
    context = prepare_delegated_execution_context(text)
    base, boundary, expanded = context.partition(_EXPANDED_CONTEXT_BOUNDARY)
    if not boundary:
        return context
    expanded_block = f"{EXPANDED_CONTEXT_HEADER}{expanded}"
    normalized_base = base.strip()
    return f"{normalized_base}\n\n{expanded_block}" if normalized_base else expanded_block


def resolve_context_message_indexes(indexes) -> str:
    """按 1-based 下标从当前快照展开消息原文。

    成功返回以 ``EXPANDED_CONTEXT_HEADER`` 开头的文本块(逐字保真);任何
    system 引用、非法输入、快照缺失或总量超限都抛
    ``DelegationContextError`` 整体失败。
    """
    snapshot = get_llm_messages_snapshot()
    if snapshot is None:
        raise DelegationContextError(
            "当前没有可用的消息快照(委派可能处于恢复或程序注入路径)。"
            "请把所需内容直接写入 execution_context 后重试，或重新发起委派。"
        )

    normalized = _normalize_indexes(indexes, upper_bound=len(snapshot))

    for idx in normalized:
        role = snapshot[idx - 1].role.strip().lower()
        if role == "system":
            raise DelegationContextError(
                f"消息下标 {idx} 指向 system 消息，不能委派。"
                "system 消息可能包含仅对当前 Agent 授权的能力目录；"
                "请只引用 user、assistant 或 tool 消息。"
            )

    lines = [EXPANDED_CONTEXT_HEADER]
    for idx in normalized:
        message = snapshot[idx - 1]
        lines.append(f"--- 消息 #{idx}（{message.role}）---")
        content = message.content
        lines.append("" if content is None else str(content))
    block = "\n".join(lines)

    max_chars = get_unified_config().get_agent_tools_delegation_context_expansion_max_chars()
    if len(block) > max_chars:
        raise DelegationContextError(
            f"引用消息展开后共 {len(block)} 字符，超过上限 {max_chars}。"
            "请缩小 context_message_indexes 的引用范围，"
            "或把关键要点改写进 execution_context。"
        )
    return block


def _normalize_indexes(indexes, *, upper_bound: int) -> list[int]:
    legal_range = (
        f"本轮合法范围是 1..{upper_bound}。" if upper_bound > 0 else "本轮快照没有可引用消息。"
    )
    if not isinstance(indexes, (list, tuple)):
        raise DelegationContextError(
            "context_message_indexes 必须是消息下标组成的数组，请重填。" + legal_range
        )
    if not indexes:
        raise DelegationContextError(
            "context_message_indexes 不能是空数组；不需要携带历史消息时请省略该参数。" + legal_range
        )
    normalized: set[int] = set()
    for item in indexes:
        # bool 是 int 子类,显式排除,避免 True/False 被当下标 1/0
        if isinstance(item, bool) or not isinstance(item, int):
            raise DelegationContextError(
                f"context_message_indexes 含非整数项: {item!r}。"
                "每项必须是 1-based 消息下标整数，请重填。" + legal_range
            )
        if item < 1 or item > upper_bound:
            raise DelegationContextError(
                f"消息下标 {item} 越界：本轮可见消息共 {upper_bound} 条，"
                f"合法范围是 1..{upper_bound}。请按你实际看到的消息顺序重填。"
            )
        if item in normalized:
            raise DelegationContextError(
                f"context_message_indexes 含重复下标 {item}。"
                "每条消息只需引用一次，请去重后重填。" + legal_range
            )
        normalized.add(item)
    return sorted(normalized)

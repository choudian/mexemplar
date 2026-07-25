"""Per-turn budget on the combined size of parallel tool results.

Each tool result is already capped individually (``visible_char_cap``), but a
turn that calls four tools at once can stay under every individual cap and still
produce one oversized message. This trims the group back to budget.

Two properties matter more than the trimming itself:

- **Trim the largest first.** Given 500 / 30000 / 800 / 600, dropping the last
  one leaves the group still over budget and eventually forces the big one to be
  trimmed anyway; dropping the big one alone brings the group under budget and
  leaves the other three intact.
- **Never take back what the model already read.** Trimming happens on the
  assembly that first sends a batch, before the model has seen any of it. Once a
  result has been shown in full it stays full — silently swapping seen content
  for a pointer is what made the old reference handler loop.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Callable, Iterable, List, Optional, Sequence

from src.data.models_sqlite import Message

logger = logging.getLogger(__name__)

# 这些工具返回的是模型主动取回的原文；对它们做任何裁剪/替换都会重新接上
# 「替换 → load_reference 取回 → 再被替换」的循环。compression_handler 共用此常量。
RETRIEVAL_TOOLS = frozenset({"load_reference", "load_tool_output"})

_PREVIEW_CHARS = 600


class ToolResultGroup:
    """One assistant turn's tool results — what the API merges into one message."""

    def __init__(self, results: List[Message]) -> None:
        self.results = results

    @property
    def total_chars(self) -> int:
        return sum(len(m.content or "") for m in self.results)

    def trimmable(self) -> List[Message]:
        return [m for m in self.results if m.tool_name not in RETRIEVAL_TOOLS and (m.content or "")]


def group_tool_results(messages: Sequence[Message]) -> List[ToolResultGroup]:
    """Group tool results by the assistant turn that requested them."""
    groups: List[ToolResultGroup] = []
    pending_ids: set[str] = set()
    current: List[Message] = []

    for message in messages:
        if message.role == "assistant" and message.tool_calls:
            if current:
                groups.append(ToolResultGroup(current))
            current = []
            pending_ids = _tool_call_ids(message.tool_calls)
            continue
        if message.role == "tool" and message.tool_call_id in pending_ids:
            current.append(message)
            continue
        if current:
            groups.append(ToolResultGroup(current))
            current = []
        pending_ids = set()

    if current:
        groups.append(ToolResultGroup(current))
    return [g for g in groups if len(g.results) > 1]


def _tool_call_ids(raw: str) -> set[str]:
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(item.get("id")) for item in parsed if isinstance(item, dict) and item.get("id")}


def select_to_trim(group: ToolResultGroup, limit: int) -> List[Message]:
    """Pick the largest results to trim until the group fits, largest first."""
    candidates = sorted(group.trimmable(), key=lambda m: len(m.content or ""), reverse=True)
    remaining = group.total_chars
    selected: List[Message] = []
    for message in candidates:
        if remaining <= limit:
            break
        selected.append(message)
        remaining -= len(message.content or "")
    return selected


class ToolResultBudget:
    """Trims oversized parallel tool result groups, once, in place."""

    def __init__(self, limit: int) -> None:
        self.limit = limit

    def apply(self, session_id: str, messages: Sequence[Message], msg_repo) -> int:
        """Trim over-budget groups. Returns the number of characters freed.

        The original content is archived and stays reachable through
        ``load_reference``; the visible message keeps its ``tool_call_id`` so the
        assistant/tool pairing does not break.
        """
        freed = 0
        for group in group_tool_results(messages):
            if group.total_chars <= self.limit:
                continue
            for message in select_to_trim(group, self.limit):
                freed += self._trim(session_id, message, msg_repo)
        if freed:
            logger.info("[工具结果预算] 已裁剪并发结果，腾出约 %d 字符", freed)
        return freed

    def _trim(self, session_id: str, message: Message, msg_repo) -> int:
        try:
            return archive_tool_result(session_id, message, msg_repo, build_pointer=_build_preview)
        except Exception:
            # One failed trim must not stop the others, nor block compression.
            logger.warning("[工具结果预算] 裁剪失败: %s", message.message_id, exc_info=True)
            return 0


def archive_tool_result(
    session_id: str,
    message: Message,
    msg_repo,
    *,
    build_pointer: Callable[[str, str, Optional[str]], str],
) -> int:
    """把一条工具结果消息归档为可经 load_reference 取回，原消息改写为指针。

    构造 ``tool_result_archive`` 归档行、写库、把原消息内容替换为 ``build_pointer``
    生成的指针、回写 ``message.content``，返回腾出的字符数。归档或写库抛出的异常
    向调用方传播，由调用方记日志并决定是否继续处理其余消息——pointer 形态和失败
    日志都由调用方决定，本函数只做机械的归档+回写。

    Args:
        session_id: 归档行所属会话。
        message: 要归档的工具结果消息；原地改写 ``content``，保留 role/tool_call_id
            以维持 assistant tool_calls 与 tool results 的配对。
        msg_repo: MessageRepository，提供 create / update_content。
        build_pointer: ``(original_content, archived_id, tool_name) -> 指针文本``，
            指针形态由调用方决定（预算裁剪带预览头，压缩替换是纯引用）。
    """
    original = message.content or ""
    archived = Message(
        message_id=str(uuid.uuid4()),
        session_id=session_id,
        sequence=message.sequence,
        role=message.role,
        content=original,
        message_type="tool_result_archive",
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        is_archived=True,
    )
    msg_repo.create(archived)
    pointer = build_pointer(original, archived.message_id, message.tool_name)
    msg_repo.update_content(message.message_id, pointer)
    message.content = pointer
    return len(original) - len(pointer)


def _build_preview(content: str, reference_id: str, tool_name: str | None) -> str:
    head = content[:_PREVIEW_CHARS]
    return (
        f"{head}\n\n[REF::{reference_id}]（完整结果 {len(content)} 字符）"
        f"{tool_name or '工具'} 的本轮结果因并发总量超限已截断，"
        "需要完整内容时用 load_reference 取回。"
    )


def iter_group_sizes(messages: Iterable[Message]) -> List[int]:
    """Group totals, for diagnostics and tests."""
    return [group.total_chars for group in group_tool_results(list(messages))]

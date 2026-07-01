"""
助理 Agent 专属工具（非动态用户工具）

这些工具把耗时的工具修复/工具化任务写入 DB 队列，由 AssistantTaskWorker 后台消费。
"""

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING
from src.utils.timezone import utc_now

if TYPE_CHECKING:
    from src.business.task_collaboration.adjudication import TaskAdjudicationService
    from src.business.task_collaboration.meetings import TaskMeetingService
    from src.business.task_collaboration.questions import TaskQuestionService
    from src.business.task_collaboration.service import TaskCollaborationService
    from src.business.task_collaboration.todos import TaskTodoService
    from src.business.user_todos import UserTodoService

from src.business.agents.config import ResultType, ToolDefinition, ToolSignal
from src.business.agents.tool_helpers import make_tool_schema, error_json, to_json
from src.business.brain.assistant_facades import (
    AssistantMemoryToolFacade,
    AssistantSpecialistToolFacade,
)
from src.data.models_sqlite import PendingAssistantTask
from src.data.repositories import PendingTaskRepository, ToolRepository

# 后台任务 Worker 唤醒回调（由 Orchestrator 注入）
_task_worker_notify = None


def register_task_worker_notify(callback):
    """注入任务队列唤醒回调（由 Orchestrator 调用）"""
    global _task_worker_notify
    _task_worker_notify = callback


def _notify_task_worker() -> bool:
    """唤醒后台 Worker 立即处理 pending 任务"""
    if _task_worker_notify is None:
        logger.error("[assistant_tools] 后台任务 Worker 唤醒回调未注册")
        return False
    _task_worker_notify()
    return True


logger = logging.getLogger(__name__)
_retrieved_context_lock = threading.RLock()
_retrieved_context_entry_ids: dict[str, set[str]] = {}
_context_access_time: dict[str, float] = {}


def _record_retrieved_context_entry_ids(session_id: str | None, results: list[dict]) -> None:
    """Track entries explicitly retrieved by assistant tools for later invalidation."""
    if not session_id:
        return
    entry_ids = {
        str(item.get("entry_id", "")).strip()
        for item in results
        if isinstance(item, dict) and str(item.get("entry_id", "")).strip()
    }
    if not entry_ids:
        return
    with _retrieved_context_lock:
        _retrieved_context_entry_ids.setdefault(session_id, set()).update(entry_ids)
        _context_access_time[session_id] = time.monotonic()


def _retrieved_context_entry_ids_for_session(session_id: str | None) -> set[str]:
    if not session_id:
        return set()
    with _retrieved_context_lock:
        _context_access_time[session_id] = time.monotonic()
        return set(_retrieved_context_entry_ids.get(session_id, set()))


def cleanup_retrieved_context(session_id: str) -> None:
    """Remove tracked retrieved entry IDs for a closed session to prevent unbounded growth."""
    with _retrieved_context_lock:
        _retrieved_context_entry_ids.pop(session_id, None)
        _context_access_time.pop(session_id, None)
        # Evict stale entries older than 24 hours to bound memory in long-running sidecar
        _evict_stale_context_entries()


def _evict_stale_context_entries(max_age_seconds: int = 86400) -> None:
    """Remove idle retrieved-context entries, then enforce a defensive size cap.

    Called internally after cleanup_retrieved_context; also safe to call from any
    segment-boundary path to bound memory growth for abandoned sessions.
    """
    cutoff = time.monotonic() - max(max_age_seconds, 0)
    with _retrieved_context_lock:
        stale_keys = [
            key
            for key in _retrieved_context_entry_ids
            if _context_access_time.get(key, 0.0) <= cutoff
        ]
        for key in stale_keys:
            _retrieved_context_entry_ids.pop(key, None)
            _context_access_time.pop(key, None)

        if len(_retrieved_context_entry_ids) > 500:
            sorted_keys = sorted(
                _retrieved_context_entry_ids.keys(),
                key=lambda key: _context_access_time.get(key, 0.0),
            )
            for key in sorted_keys[:250]:
                _retrieved_context_entry_ids.pop(key, None)
                _context_access_time.pop(key, None)


REPORT_TOOL_BUG_SCHEMA = make_tool_schema(
    name="report_tool_bug",
    description="报告某个用户工具执行失败。系统将安排自动修复。",
    properties={
        "tool_name": {
            "type": "string",
            "description": "出问题的工具名称",
        },
        "error_message": {
            "type": "string",
            "description": "错误信息或失败描述",
        },
        "user_input": {
            "type": "string",
            "description": "用户当时传入的参数（JSON 字符串或自然语言描述）",
        },
    },
    required=["tool_name", "error_message"],
)


def report_tool_bug_handler(
    tool_name: str,
    error_message: str,
    user_input: str = "",
) -> str:
    """
    report_tool_bug handler

    1. 按工具名查找已发布工具
    2. 创建 pending_assistant_tasks 记录
    3. 唤醒后台 Worker 处理（Orchestrator 轮询消费）
    4. 返回确认消息
    """
    with ToolRepository() as tool_repo:
        tool = tool_repo.get_by_name(tool_name)
        tool_id = tool.tool_id if tool else ""
    if not tool:
        return error_json(f"找不到工具 '{tool_name}'")

    task_id = str(uuid.uuid4())
    payload = to_json(
        {
            "tool_id": tool_id,
            "tool_name": tool_name,
            "error_message": error_message,
            "user_input": user_input,
            "reported_at": utc_now().isoformat(),
        }
    )

    with PendingTaskRepository() as task_repo:
        task_repo.create(
            PendingAssistantTask(
                task_id=task_id,
                task_type="fix_tool_bug",
                payload=payload,
                status="pending",
            )
        )

    # 通知后台 Worker 立即处理（不用 blinker 事件，避免线程嵌套）
    worker_notified = _notify_task_worker()

    logger.info(
        "[report_tool_bug] 已提交 Bug 报告: tool_chars=%d task_id=%s",
        len(tool_name or ""),
        task_id,
    )
    return to_json(
        {
            "success": True,
            "message": f"已收到工具 '{tool_name}' 的 Bug 报告，系统将安排自动修复。",
            "task_id": task_id,
            "worker_notified": worker_notified,
        }
    )


REPORT_TOOL_BUG = ToolDefinition(
    name="report_tool_bug",
    schema=REPORT_TOOL_BUG_SCHEMA,
    handler=report_tool_bug_handler,
)

CODIFY_AS_TOOL_SCHEMA = make_tool_schema(
    name="codify_as_tool",
    description="将最近完成的任务做成可复用工具。用户明确要求将某个任务做成工具时调用。",
    properties={
        "task_description": {
            "type": "string",
            "description": "任务的自然语言描述，如查询指定城市的天气",
        },
    },
    required=["task_description"],
)


def _rfind_role(messages: list, role: str, start: int | None = None) -> int:
    """从后向前查找最后一条指定 role 的消息索引，未找到返回 -1。"""
    begin = len(messages) - 1 if start is None else start
    if begin < 0:
        return -1
    for i in range(begin, -1, -1):
        if messages[i].role == role:
            return i
    return -1


def _extract_tool_calls_from_messages(messages: list) -> list:
    """
    从会话消息历史中提取倒数第二条 user 消息到最后一条 user 消息之间的工具调用链。

    若只有一条 user 消息，则取该 user 消息之后的所有工具调用。只扫描非 archived 消息。
    """
    active_messages = [m for m in messages if not m.is_archived]
    if not active_messages:
        return []

    last_user_idx = _rfind_role(active_messages, "user")
    if last_user_idx < 0:
        return []

    previous_user_idx = _rfind_role(active_messages, "user", start=last_user_idx - 1)

    trace = []
    if previous_user_idx >= 0:
        # 多轮对话：取前一条 user 和最后一条 user 之间的工具调用
        trace_window = active_messages[previous_user_idx + 1 : last_user_idx]
    else:
        # 单条 user 消息：取该 user 消息之后的所有工具调用
        trace_window = active_messages[last_user_idx + 1 :]
    for msg in trace_window:
        if msg.role == "assistant" and msg.tool_calls:
            try:
                calls = json.loads(msg.tool_calls)
                for c in calls:
                    trace.append(
                        {"type": "tool_call", "name": c.get("name", ""), "args": c.get("args", {})}
                    )
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    "[codify_as_tool] 工具调用记录解析失败: message_id=%s, session_id=%s, error=%s",
                    getattr(msg, "message_id", ""),
                    getattr(msg, "session_id", ""),
                    exc,
                )
        elif msg.role == "tool" and msg.content:
            trace.append(
                {"type": "tool_result", "name": msg.tool_name or "", "content": msg.content[:500]}
            )

    return trace


def create_codify_as_tool_handler(session_id: str):
    """工厂函数：创建绑定了 session_id 的 codify_as_tool handler"""

    def codify_as_tool_handler(task_description: str) -> str:
        """将最近完成的任务做成可复用工具"""
        from src.data.repositories import MessageRepository, PendingTaskRepository
        from src.data.models_sqlite import PendingAssistantTask

        # 提取执行记录
        with MessageRepository() as message_repo:
            messages = message_repo.get_by_session(session_id)
        if not messages:
            return error_json("未找到会话消息，请先执行一次该任务再要求做成工具")

        execution_trace = _extract_tool_calls_from_messages(messages)
        if not execution_trace:
            return error_json("未找到最近的工具调用记录，请先执行一次该任务再要求做成工具")

        task_id = str(uuid.uuid4())
        payload = to_json(
            {
                "task_description": task_description,
                "execution_trace": execution_trace,
                "session_id": session_id,
                "requested_at": utc_now().isoformat(),
            }
        )

        with PendingTaskRepository() as repo:
            repo.create(
                PendingAssistantTask(
                    task_id=task_id,
                    task_type="codify_tool",
                    payload=payload,
                    status="pending",
                )
            )

        # 通知后台 Worker 立即处理（不用 blinker 事件，避免线程嵌套）
        worker_notified = _notify_task_worker()
        logger.info(
            "[codify_as_tool] 已提交工具创建请求: task_chars=%d task_id=%s",
            len(task_description or ""),
            task_id,
        )

        return to_json(
            {
                "success": True,
                "message": "已提交工具创建请求，系统正在后台处理，完成后会通知你。",
                "task_id": task_id,
                "worker_notified": worker_notified,
            }
        )

    return codify_as_tool_handler


SAVE_PROFILE_SCHEMA = make_tool_schema(
    name="save_profile",
    description="保存用户的偏好设置（称呼、沟通风格、特别注意事项）。在用户告知偏好后调用一次。",
    properties={
        "display_name": {
            "type": "string",
            "description": "用户希望被如何称呼，如小明、boss 等",
        },
        "style": {
            "type": "string",
            "description": "沟通风格偏好，如简洁直接、详细解释、正式等",
        },
        "notes": {
            "type": "string",
            "description": "其他特别注意事项",
        },
    },
    required=[],
)


def create_save_profile_handler(session_id: str):
    """工厂函数：创建绑定了 session_id 的 save_profile handler"""
    import re

    def save_profile_handler(
        display_name: str = "",
        style: str = "",
        notes: str = "",
    ) -> str:
        """保存用户偏好到 assistant_profile 表，并就地更新当前会话的 system prompt"""
        try:
            from src.data.repositories import AssistantProfileRepository, MessageRepository

            with AssistantProfileRepository() as repo:
                repo.save(display_name=display_name, style=style, notes=notes)

            # 就地替换当前会话 system prompt 中的 ## 关于用户 / ## 首次见面指引 段落
            with MessageRepository() as msg_repo:
                system_msg = msg_repo.get_first(session_id)
                if system_msg and system_msg.role == "system" and system_msg.content:
                    new_section = "## 关于用户\n\n"
                    if display_name:
                        new_section += f"- 称呼：{display_name}\n"
                    if style:
                        new_section += f"- 沟通风格偏好：{style}\n"
                    if notes:
                        new_section += f"- 特别注意：{notes}\n"

                    new_content = re.sub(
                        r"## (?:关于用户|首次见面指引).*?(?=\n\n## |\Z)",
                        new_section.rstrip("\n"),
                        system_msg.content,
                        flags=re.DOTALL,
                    )
                    if new_content != system_msg.content:
                        msg_repo.update_content(system_msg.message_id, new_content)
                        logger.info("[save_profile] 当前会话 system prompt 已更新: %s", session_id)

            logger.info(
                "[save_profile] 用户偏好已保存: display_name=%s, style=%s",
                display_name,
                style,
            )
            return to_json({"success": True, "message": "偏好已保存"})
        except Exception as e:
            logger.error("[save_profile] 保存失败: %s", e, exc_info=True)
            return error_json("偏好保存失败，请稍后重试。")

    return save_profile_handler


DISMISS_SUGGESTION_SCHEMA = make_tool_schema(
    name="dismiss_suggestion",
    description="用户拒绝了某个工具化建议时调用，记录拒绝状态以避免反复提醒。",
    properties={
        "task_pattern": {
            "type": "string",
            "description": "被拒绝的任务类型描述",
        },
    },
    required=["task_pattern"],
)


def dismiss_suggestion_handler(task_pattern: str) -> str:
    """记录用户拒绝工具化建议，重置计数进入冷却期"""
    try:
        from src.data.repositories import ToolSuggestionRepository

        repo = ToolSuggestionRepository()
        record = repo.get_by_pattern(task_pattern)
        if record:
            repo.mark_rejected(record)

        return to_json({"success": True, "message": "好的，不再建议了"})
    except Exception as e:
        logger.error("[dismiss_suggestion] 失败: %s", e, exc_info=True)
        return error_json("处理建议时发生内部错误，请稍后重试。")


DISMISS_SUGGESTION = ToolDefinition(
    name="dismiss_suggestion",
    schema=DISMISS_SUGGESTION_SCHEMA,
    handler=dismiss_suggestion_handler,
)


# ===== 归档检索工具 =====


RETRIEVE_ARCHIVE_SCHEMA = make_tool_schema(
    name="retrieve_archive",
    description="检索大脑归档区中的历史记忆。当你需要回忆用户之前提到过但现在不在当前上下文中的信息时调用。",
    properties={
        "query": {
            "type": "string",
            "description": "搜索关键词，用于匹配归档记忆的内容",
        },
    },
    required=["query"],
)


def retrieve_archive_handler(query: str, session_id: str | None = None) -> str:
    """从归档区检索与查询关键词匹配的记忆条目。"""
    if not query or not query.strip():
        return to_json(
            {
                "success": False,
                "message": "请提供搜索关键词",
                "results": [],
            }
        )

    try:
        results = AssistantMemoryToolFacade().retrieve_archive(query)
        _record_retrieved_context_entry_ids(session_id, results)

        if not results:
            return to_json(
                {
                    "success": True,
                    "message": f"未找到与 '{query}' 相关的归档记忆",
                    "results": [],
                }
            )

        return to_json(
            {
                "success": True,
                "results": [
                    {
                        "entry_id": r["entry_id"],
                        "content": r["content"],
                        "status": r["status"],
                        "relevance_score": r.get("relevance_score", 0),
                        "composite_score": r.get("composite_score", 0),
                        "invalidation_factor": r.get("invalidation_factor", 1.0),
                    }
                    for r in results
                ],
            }
        )
    except Exception as e:
        logger.error("[retrieve_archive] failed: %s", e, exc_info=True)
        return to_json(
            {
                "success": False,
                "message": "检索归档记忆时发生内部错误，请稍后重试。",
                "results": [],
            }
        )


RETRIEVE_ARCHIVE = ToolDefinition(
    name="retrieve_archive",
    schema=RETRIEVE_ARCHIVE_SCHEMA,
    handler=retrieve_archive_handler,
)


def _bind_session_id(handler, session_id: str | None):
    """Create a wrapper that injects session_id into a handler that accepts it as a kwarg."""

    def bound(*args, **kwargs):
        return handler(*args, session_id=session_id, **kwargs)

    return bound


def create_retrieve_archive_handler(session_id: str | None = None):
    return _bind_session_id(retrieve_archive_handler, session_id)


__all__ = [
    "REPORT_TOOL_BUG",
    "SAVE_PROFILE_SCHEMA",
    "create_save_profile_handler",
    "CODIFY_AS_TOOL_SCHEMA",
    "create_codify_as_tool_handler",
    "DISMISS_SUGGESTION",
    "register_task_worker_notify",
    "cleanup_retrieved_context",
    "RETRIEVE_ARCHIVE",
    "RETRIEVE_ARCHIVE_SCHEMA",
    "create_retrieve_archive_handler",
    "RETRIEVE_FAILURE_ZONE",
    "RETRIEVE_FAILURE_ZONE_SCHEMA",
    "create_retrieve_failure_zone_handler",
    "INVALIDATE_MEMORY_ENTRY",
    "create_invalidate_memory_entry_handler",
    "REPLY_TO_USER_SCHEMA",
    "create_reply_to_user_handler",
    "DELEGATE_TO_SUBAGENT_SCHEMA",
    "create_delegate_to_subagent_handler",
    "DELEGATE_TO_SPECIALIST_SCHEMA",
    "create_delegate_to_specialist_handler",
    "CREATE_SPECIALIST_SCHEMA",
    "create_create_specialist_handler",
    "CONTINUE_SUBAGENT_SCHEMA",
    "create_continue_subagent_handler",
    "INSPECT_SUBAGENT_SCHEMA",
    "create_inspect_subagent_handler",
    "ASK_USER_QUESTION_SCHEMA",
    "create_ask_user_question_handler",
    "ASK_PARENT_SCHEMA",
    "create_ask_parent_handler",
    "ANSWER_TASK_QUESTION_SCHEMA",
    "create_answer_task_question_handler",
    "OPEN_MEETING_CHANNEL_SCHEMA",
    "create_open_meeting_channel_handler",
    "MEETING_SEND_MESSAGE_SCHEMA",
    "create_meeting_send_message_handler",
    "TODO_UPDATE_SCHEMA",
    "create_todo_update_handler",
    "CREATE_USER_TODO_SCHEMA",
    "create_user_todo_handler",
    "LIST_USER_TODOS_SCHEMA",
    "create_list_user_todos_handler",
    "UPDATE_USER_TODO_SCHEMA",
    "create_update_user_todo_handler",
    "COMPLETE_USER_TODO_SCHEMA",
    "create_complete_user_todo_handler",
    "DELETE_USER_TODO_SCHEMA",
    "create_delete_user_todo_handler",
    "BUILD_TASK_GRAPH_SCHEMA",
    "create_build_task_graph_handler",
    "MUTATE_TASK_GRAPH_SCHEMA",
    "create_mutate_task_graph_handler",
    "DECIDE_ADJUDICATION_SCHEMA",
    "create_decide_task_adjudication_handler",
    "ABANDON_REQUEST_GRAPH_SCHEMA",
    "create_abandon_request_graph_handler",
]


# ===== 大脑检索工具 =====


RETRIEVE_FAILURE_ZONE_SCHEMA = make_tool_schema(
    name="retrieve_failure_zone",
    description="检索失败区记忆，查找过去类似任务中失败的决策和原因",
    properties={
        "context": {"type": "string", "description": "当前任务的上下文描述，用于匹配相关失败记录"},
    },
    required=["context"],
)


def retrieve_failure_zone_handler(context: str, session_id: str | None = None) -> str:
    """从失败区检索与当前上下文相关的记忆条目"""
    try:
        entries = AssistantMemoryToolFacade().retrieve_failure_zone(context)
        _record_retrieved_context_entry_ids(session_id, entries)
        return to_json(
            {
                "success": True,
                "entries": [
                    {
                        "entry_id": e.get("entry_id"),
                        "content": e.get("content"),
                        "reason": e.get("reason"),
                        "composite_score": e.get("composite_score", 0),
                        "invalidation_factor": e.get("invalidation_factor", 1.0),
                    }
                    for e in entries
                ],
            }
        )
    except Exception as e:
        logger.error("[retrieve_failure_zone] failed: %s", e, exc_info=True)
        return error_json("检索失败记忆时发生内部错误，请稍后重试。")


RETRIEVE_FAILURE_ZONE = ToolDefinition(
    name="retrieve_failure_zone",
    schema=RETRIEVE_FAILURE_ZONE_SCHEMA,
    handler=retrieve_failure_zone_handler,
)


def create_retrieve_failure_zone_handler(session_id: str | None = None):
    return _bind_session_id(retrieve_failure_zone_handler, session_id)


INVALIDATE_MEMORY_ENTRY_SCHEMA = make_tool_schema(
    name="invalidate_memory_entry",
    description="将一条记忆条目标记为失效（降权，不删除）",
    properties={
        "entry_id": {"type": "string", "description": "要失效的记忆条目 ID"},
        "reason": {"type": "string", "description": "失效原因"},
        "invalidation_type": {
            "type": "string",
            "enum": ["reactive", "proactive"],
            "description": "reactive 表示用户明确纠正；proactive 表示助理主动发现事实冲突，之后必须同轮告知用户",
        },
    },
    required=["entry_id", "reason"],
)


def _context_entry_ids_for_session(session_id: str | None) -> list[str] | None:
    if not session_id:
        return None
    return AssistantMemoryToolFacade().context_entry_ids_for_session(
        session_id,
        _retrieved_context_entry_ids_for_session(session_id),
    )


def create_invalidate_memory_entry_handler(session_id: str | None = None):
    """工厂函数：创建绑定当前上下文窗口的 invalidate_memory_entry handler。"""

    def invalidate_memory_entry_handler(
        entry_id: str,
        reason: str,
        invalidation_type: str = "reactive",
    ) -> str:
        """将当前上下文窗口内的一条记忆标记为 invalidated。"""
        try:
            result = AssistantMemoryToolFacade().invalidate_memory_entry(
                entry_id,
                reason,
                current_context_entry_ids=_context_entry_ids_for_session(session_id),
            )
            return to_json(_annotate_invalidation_disclosure(result, invalidation_type))
        except Exception as e:
            logger.error("[invalidate_memory_entry] failed: %s", e, exc_info=True)
            return error_json("标记记忆失效时发生内部错误，请稍后重试。")

    return invalidate_memory_entry_handler


def _annotate_invalidation_disclosure(result: dict, invalidation_type: str) -> dict:
    if (
        not isinstance(result, dict)
        or invalidation_type != "proactive"
        or not result.get("success")
    ):
        return result
    return {
        **result,
        "requires_user_disclosure": True,
        "disclosure_instruction": (
            "你主动发现了记忆冲突。必须在同一轮 reply_to_user 中告知用户已将这条记忆标记为失效。"
        ),
    }


INVALIDATE_MEMORY_ENTRY = ToolDefinition(
    name="invalidate_memory_entry",
    schema=INVALIDATE_MEMORY_ENTRY_SCHEMA,
    handler=create_invalidate_memory_entry_handler(None),
)


# ===== 结构化多选澄清工具（仅主助理）=====


ASK_USER_QUESTION_SCHEMA = make_tool_schema(
    name="ask_user_question",
    description=(
        "在关键决策无法可靠推断时，向用户提出 1-4 道结构化问题（每题 2-4 个选项，单选或多选，"
        '始终可填"其他"）。仅用于关键岔路口；关联问题一次问齐；不得询问或展示任何密钥/令牌等'
        "敏感信息。取消或超时后不得在同一回合重复追问或基于猜测继续执行有副作用的动作。"
    ),
    properties={
        "questions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "description": "1-4 道问题",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "完整问题文本"},
                    "header": {"type": "string", "description": "短标题（建议 ≤12 字符）"},
                    "multiSelect": {
                        "type": "boolean",
                        "description": "true 为多选，默认 false 单选",
                    },
                    "options": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 4,
                        "description": "2-4 个候选项",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string", "description": "选项标签"},
                                "description": {
                                    "type": "string",
                                    "description": "可选的选项说明",
                                },
                                "preview": {
                                    "type": "string",
                                    "description": "可选的纯文本预览（前端不渲染 HTML/Markdown）",
                                },
                            },
                            "required": ["label"],
                        },
                    },
                },
                "required": ["question", "header", "options"],
            },
        },
    },
    required=["questions"],
)


def create_ask_user_question_handler(session_id: str):
    """工厂函数：创建绑定 session_id 的 ask_user_question handler。

    阻塞型工具（非中断）：handler 内等用户决策，返回 str 结果后 AgentLoop 在同一回合继续。
    入参校验失败返回 error_json（不创建 pending）；澄清机制未注册返回 status=unavailable。
    """

    def ask_user_question_handler(questions: list) -> str:
        from src.business.agents.tools import clarification_manager

        try:
            result = clarification_manager.ask_user_question(questions, session_id=session_id)
        except clarification_manager.ClarificationValidationError as exc:
            return error_json(str(exc))
        except Exception as exc:
            logger.error("[ask_user_question] 发起澄清失败: %s", exc, exc_info=True)
            return error_json("发起用户澄清失败，请稍后重试或直接继续。")
        return to_json(result)

    return ask_user_question_handler


# ===== 任务协作工具 =====


def _run_task_service(tool_name: str, generic_error_msg: str, fn):
    """Run a task-collaboration service call with two-tier error handling.

    业务校验异常（LookupError / ValueError / PermissionError）的文案是安全字面量，原样
    回给 LLM；其余异常可能含内部细节，只入后端日志并对 LLM 返回通用文案。session 生命周期
    由各调用方的 ``with ...Service()`` 负责，不在此函数内管理。
    """
    try:
        return fn()
    except (LookupError, ValueError, PermissionError) as e:
        # 业务校验异常的文案是我们自己写的安全字面量，可直接回给 LLM。
        return error_json(str(e))
    except Exception:
        # 其余异常可能携带 DB 错误/路径等内部细节，只入后端日志，对 LLM 给通用文案。
        logger.error("[%s] failed", tool_name, exc_info=True)
        return error_json(generic_error_msg)


def _resolve_bound_task_id(supplied_task_id: str | None, bound_task_id: str | None) -> str:
    task_id = (bound_task_id or supplied_task_id or "").strip()
    if not task_id:
        raise ValueError("taskId is required for this task collaboration tool")
    return task_id


ASK_PARENT_SCHEMA = make_tool_schema(
    name="ask_parent",
    description=(
        "向当前任务的派活方提问或请求资源/能力。用于执行前或执行中对齐目标；"
        "如果问题最终上冒到用户，用户待答和原始答案仍不会持久化。"
    ),
    properties={
        "taskId": {"type": "string", "description": "当前统一任务 ID"},
        "question": {"type": "string", "description": "问题或请求内容"},
        "kind": {
            "type": "string",
            "enum": ["clarification", "resource_request", "capability_request"],
            "description": "问题类型",
        },
        "capabilityDelta": {
            "type": "array",
            "items": {"type": "string"},
            "description": "能力请求的工具/能力 ID 列表，必须是父任务能力范围的子集",
        },
    },
    required=["taskId", "question", "kind"],
)


def create_ask_parent_handler(
    executor_type: str = "specialist",
    executor_id: str = "",
    *,
    bound_task_id: str | None = None,
    interrupt: bool = False,
    service_factory: Callable[[], "TaskQuestionService"] | None = None,
):
    def _question_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.questions import TaskQuestionService

        return TaskQuestionService()

    def ask_parent_handler(
        taskId: str = "",
        question: str = "",
        kind: str = "",
        capabilityDelta: list[str] | None = None,
    ) -> str | ToolSignal:
        def _action():
            effective_task_id = _resolve_bound_task_id(taskId, bound_task_id)
            with _question_service() as service:
                row = service.ask_parent(
                    task_id=effective_task_id,
                    asker_type=executor_type,
                    asker_id=executor_id or executor_type,
                    kind=kind,
                    question=question,
                    capability_delta=capabilityDelta,
                )
                return to_json(
                    {
                        "success": True,
                        "questionId": row.question_id,
                        "taskId": row.task_id,
                        "status": row.status,
                        "kind": row.kind,
                    }
                )

        if interrupt:
            try:
                return ToolSignal(
                    result_type=ResultType.NEEDS_USER_INPUT,
                    display_text=_action(),
                )
            except (LookupError, ValueError, PermissionError) as e:
                return ToolSignal(
                    result_type=ResultType.ERROR,
                    display_text=error_json(str(e)),
                )
            except Exception:
                logger.error("[ask_parent] failed", exc_info=True)
                return ToolSignal(
                    result_type=ResultType.ERROR,
                    display_text=error_json("处理向上提问请求时发生内部错误，请稍后重试。"),
                )

        return _run_task_service(
            "ask_parent", "处理向上提问请求时发生内部错误，请稍后重试。", _action
        )

    return ask_parent_handler


ANSWER_TASK_QUESTION_SCHEMA = make_tool_schema(
    name="answer_task_question",
    description=(
        "答复子任务通过 ask_parent 提交的问题或资源/能力请求。"
        "可选 capabilityDelta 只能授予当前父任务能力范围内的子集。"
    ),
    properties={
        "questionId": {"type": "string", "description": "待答问题 ID"},
        "safeAnswerSummary": {
            "type": "string",
            "description": "给子任务继续执行用的安全答复摘要",
        },
        "capabilityDelta": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选：授予的工具/能力 ID 列表",
        },
    },
    required=["questionId", "safeAnswerSummary"],
)


def create_answer_task_question_handler(
    redispatch_callback=None,
    service_factory: Callable[[], "TaskQuestionService"] | None = None,
):
    def _question_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.questions import TaskQuestionService

        return TaskQuestionService()

    def answer_task_question_handler(
        questionId: str,
        safeAnswerSummary: str,
        capabilityDelta: list[str] | None = None,
    ) -> str:
        def _action():
            with _question_service() as service:
                answered = service.answer_question(
                    questionId,
                    safe_answer_summary=safeAnswerSummary,
                    capability_delta=capabilityDelta,
                )
            redispatched = False
            if redispatch_callback is not None:
                redispatched = bool(redispatch_callback(answered.task_id))
            return to_json(
                {
                    "success": True,
                    "questionId": answered.question_id,
                    "taskId": answered.task_id,
                    "status": answered.status,
                    "redispatched": redispatched,
                }
            )

        return _run_task_service(
            "answer_task_question", "答复子任务问题时发生内部错误，请稍后重试。", _action
        )

    return answer_task_question_handler


OPEN_MEETING_CHANNEL_SCHEMA = make_tool_schema(
    name="open_meeting_channel",
    description=(
        "为两个执行者开一条受监督、仅传消息的两方会议通道。会议不会代理工具调用或扩大授权。"
    ),
    properties={
        "taskId": {"type": "string", "description": "上级任务 ID"},
        "participantA": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["ephemeral_subagent", "specialist"]},
                "id": {"type": "string"},
            },
            "required": ["type", "id"],
        },
        "participantB": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["ephemeral_subagent", "specialist"]},
                "id": {"type": "string"},
            },
            "required": ["type", "id"],
        },
    },
    required=["taskId", "participantA", "participantB"],
)


def create_open_meeting_channel_handler(
    service_factory: Callable[[], "TaskMeetingService"] | None = None,
):
    def _meeting_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.meetings import TaskMeetingService

        return TaskMeetingService()

    def open_meeting_channel_handler(
        taskId: str,
        participantA: dict,
        participantB: dict,
    ) -> str:
        def _action():
            with _meeting_service() as service:
                channel = service.open_channel(
                    parent_task_id=taskId,
                    participant_a=participantA,
                    participant_b=participantB,
                )
                return to_json(
                    {
                        "success": True,
                        "channelId": channel.channel_id,
                        "taskId": channel.parent_task_id,
                        "turnBudget": channel.turn_budget,
                        "timeBudgetSeconds": channel.time_budget_seconds,
                    }
                )

        return _run_task_service(
            "open_meeting_channel", "打开会议通道时发生内部错误，请稍后重试。", _action
        )

    return open_meeting_channel_handler


MEETING_SEND_MESSAGE_SCHEMA = make_tool_schema(
    name="meeting_send_message",
    description=(
        "向已打开的会议通道发送消息。只能传消息；不得请求对方代用工具、共享密钥或扩大授权。"
    ),
    properties={
        "channelId": {"type": "string", "description": "会议通道 ID"},
        "content": {"type": "string", "description": "消息内容"},
        "conclusion": {"type": "string", "description": "可选结论；非空时关闭会议为已达成结论"},
    },
    required=["channelId", "content"],
)


def create_meeting_send_message_handler(
    executor_type: str = "specialist",
    executor_id: str = "",
    service_factory: Callable[[], "TaskMeetingService"] | None = None,
):
    """Create a meeting_send_message handler with bound executor identity.

    The executor identity is bound at construction time (like ask_parent and
    todo_update handlers) so the LLM cannot impersonate other participants.
    """

    def _meeting_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.meetings import TaskMeetingService

        return TaskMeetingService()

    def meeting_send_message_handler(
        channelId: str,
        content: str,
        conclusion: str = "",
    ) -> str:
        def _action():
            with _meeting_service() as service:
                channel = service.send_message(
                    channel_id=channelId,
                    sender_type=executor_type,
                    sender_id=executor_id,
                    content=content,
                    conclusion=conclusion or None,
                )
                return to_json(
                    {
                        "success": True,
                        "channelId": channel.channel_id,
                        "status": channel.status,
                        "turnsUsed": channel.turns_used,
                        "conclusion": channel.conclusion,
                    }
                )

        return _run_task_service(
            "meeting_send_message", "发送会议消息时发生内部错误，请稍后重试。", _action
        )

    return meeting_send_message_handler


TODO_UPDATE_SCHEMA = make_tool_schema(
    name="todo_update",
    description=(
        "更新当前被派任务的私人 checklist。"
        "何时用：当前任务内部 ≥3 个子步骤、或非平凡的多步执行时，开工前先用本工具列出 todo。"
        "何时不用：1-2 步的简单任务直接做；纯信息查询不必列 todo。"
        "三态流转：todo（待办）→ doing（进行中，同一时刻尽量一件）→ done（真正完成）/ skipped（有意跳过）。"
        "实时更新：每完成一个子步骤立即标 done 再推进下一个，不要全做完一次性更新。"
        "完成判定红线：未真正完成的子步骤绝不标 done；拿不准就先列 todo 再动手。"
        "范围：todo 是你当前任务的私人 checklist，不委派、不裁定、不进入任务图依赖。"
    ),
    properties={
        "taskId": {"type": "string", "description": "当前统一任务 ID"},
        "items": {
            "type": "array",
            "description": "完整 Todo 列表，按 sortOrder 排序",
            "items": {
                "type": "object",
                "properties": {
                    "todoId": {"type": "string"},
                    "text": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["todo", "doing", "done", "skipped"],
                    },
                    "sortOrder": {"type": "integer"},
                },
                "required": ["text", "status", "sortOrder"],
            },
        },
    },
    required=["taskId", "items"],
)


def create_todo_update_handler(
    executor_type: str = "specialist",
    executor_id: str = "",
    *,
    bound_task_id: str | None = None,
    service_factory: Callable[[], "TaskTodoService"] | None = None,
):
    def _todo_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.todos import TaskTodoService

        return TaskTodoService()

    def todo_update_handler(taskId: str = "", items: list[dict] | None = None) -> str:
        def _action():
            effective_task_id = _resolve_bound_task_id(taskId, bound_task_id)
            with _todo_service() as service:
                projected = service.update_todos(
                    task_id=effective_task_id,
                    executor_type=executor_type,
                    executor_id=executor_id or executor_type,
                    items=items or [],
                )
                return to_json({"success": True, "taskId": effective_task_id, "items": projected})

        return _run_task_service(
            "todo_update", "更新任务 Todo 时发生内部错误，请稍后重试。", _action
        )

    return todo_update_handler


# ===== 用户个人 Todo 工具 =====


CREATE_USER_TODO_SCHEMA = make_tool_schema(
    name="create_user_todo",
    description=(
        "创建用户个人待办事项。只用于用户自己的待办列表，不用于当前任务执行者的私人 checklist；"
        "当前任务内部拆步骤仍使用 todo_update。"
    ),
    properties={
        "title": {"type": "string", "description": "待办标题，必填"},
        "description": {"type": "string", "description": "可选描述"},
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high", "urgent"],
            "description": "优先级，默认 medium",
        },
    },
    required=["title"],
)


LIST_USER_TODOS_SCHEMA = make_tool_schema(
    name="list_user_todos",
    description=(
        "查询用户个人待办列表，可按状态、关键词和排序返回候选。"
        "用户问还有什么没做、找某个待办、或准备修改/完成待办前先用本工具。"
    ),
    properties={
        "statusFilter": {
            "type": "string",
            "enum": ["all", "open", "done"],
            "description": "筛选范围；all 返回全部，open 仅 pending 与 in_progress，done 仅已完成；默认 all",
        },
        "sort": {
            "type": "string",
            "enum": ["created_desc", "created_asc", "priority_desc", "priority_asc"],
            "description": "排序方式，默认 created_desc",
        },
        "query": {"type": "string", "description": "可选关键词，用于标题/描述匹配"},
        "limit": {"type": "integer", "description": "最多返回数量，默认 20"},
    },
    required=[],
)


UPDATE_USER_TODO_SCHEMA = make_tool_schema(
    name="update_user_todo",
    description=(
        "更新用户个人待办的标题、描述、状态或优先级。"
        "如果用户自然语言只描述了待办内容而没有 todoId，先用 list_user_todos 查候选。"
    ),
    properties={
        "todoId": {"type": "string", "description": "用户待办 ID"},
        "title": {"type": "string", "description": "可选新标题"},
        "description": {"type": "string", "description": "可选新描述"},
        "status": {
            "type": "string",
            "enum": ["pending", "in_progress", "done"],
            "description": "可选新状态",
        },
        "priority": {
            "type": "string",
            "enum": ["low", "medium", "high", "urgent"],
            "description": "可选新优先级",
        },
    },
    required=["todoId"],
)


COMPLETE_USER_TODO_SCHEMA = make_tool_schema(
    name="complete_user_todo",
    description=(
        "把用户个人待办标记为完成，或撤销完成。"
        "如果没有明确 todoId，先用 list_user_todos 查候选，不要猜。"
    ),
    properties={
        "todoId": {"type": "string", "description": "用户待办 ID"},
        "done": {"type": "boolean", "description": "true=完成，false=撤销完成；默认 true"},
    },
    required=["todoId"],
)


DELETE_USER_TODO_SCHEMA = make_tool_schema(
    name="delete_user_todo",
    description=(
        "删除用户个人待办。仅当用户明确要求删除时调用；"
        "如果没有明确 todoId，先用 list_user_todos 查候选。"
    ),
    properties={
        "todoId": {"type": "string", "description": "用户待办 ID"},
    },
    required=["todoId"],
)


def _make_user_todo_service(service_factory: Callable[[], "UserTodoService"] | None):
    if service_factory is not None:
        return service_factory()
    from src.business.user_todos import UserTodoService

    return UserTodoService()


def create_user_todo_handler(
    service_factory: Callable[[], "UserTodoService"] | None = None,
):
    def create_user_todo(
        title: str,
        description: str = "",
        priority: str = "medium",
    ) -> str:
        def _action():
            with _make_user_todo_service(service_factory) as service:
                todo = service.create(
                    title=title,
                    description=description,
                    priority=priority,
                )
                return to_json(
                    {
                        "success": True,
                        "message": "已创建用户待办。",
                        "todo": todo,
                    }
                )

        return _run_task_service(
            "create_user_todo", "创建用户待办时发生内部错误，请稍后重试。", _action
        )

    return create_user_todo


def create_list_user_todos_handler(
    service_factory: Callable[[], "UserTodoService"] | None = None,
):
    def list_user_todos(
        statusFilter: str = "all",
        sort: str = "created_desc",
        query: str = "",
        limit: int = 20,
    ) -> str:
        def _action():
            with _make_user_todo_service(service_factory) as service:
                items, total = service.list_todos(
                    status_filter=statusFilter,
                    sort=sort,
                    query=query,
                    limit=limit,
                    offset=0,
                )
                return to_json(
                    {
                        "success": True,
                        "items": items,
                        "total": total,
                        "message": "未找到匹配的用户待办。" if not items else "",
                    }
                )

        return _run_task_service(
            "list_user_todos", "查询用户待办时发生内部错误，请稍后重试。", _action
        )

    return list_user_todos


def create_update_user_todo_handler(
    service_factory: Callable[[], "UserTodoService"] | None = None,
):
    def update_user_todo(
        todoId: str,
        title: str | None = None,
        description: str | None = None,
        status: str | None = None,
        priority: str | None = None,
    ) -> str:
        def _action():
            updates = {}
            if title is not None:
                updates["title"] = title
            if description is not None:
                updates["description"] = description
            if status is not None:
                updates["status"] = status
            if priority is not None:
                updates["priority"] = priority
            with _make_user_todo_service(service_factory) as service:
                todo = service.update(todoId, updates)
                return to_json(
                    {
                        "success": True,
                        "message": "已更新用户待办。",
                        "todo": todo,
                    }
                )

        return _run_task_service(
            "update_user_todo", "更新用户待办时发生内部错误，请稍后重试。", _action
        )

    return update_user_todo


def create_complete_user_todo_handler(
    service_factory: Callable[[], "UserTodoService"] | None = None,
):
    def complete_user_todo(todoId: str, done: bool = True) -> str:
        def _action():
            with _make_user_todo_service(service_factory) as service:
                todo = service.complete(todoId, done=done)
                # done=False 时按撤销后的状态给消息：pending 说明本就未完成（no-op），
                # 否则是从 done 撤销回 in_progress（或本来 in_progress，结果成立）。
                if done:
                    message = "已完成用户待办。"
                elif todo["status"] == "pending":
                    message = "该待办原本就未完成，无需撤销。"
                else:
                    message = "已撤销完成，回到进行中。"
                return to_json(
                    {
                        "success": True,
                        "message": message,
                        "todo": todo,
                    }
                )

        return _run_task_service(
            "complete_user_todo", "完成用户待办时发生内部错误，请稍后重试。", _action
        )

    return complete_user_todo


def create_delete_user_todo_handler(
    service_factory: Callable[[], "UserTodoService"] | None = None,
):
    def delete_user_todo(todoId: str) -> str:
        def _action():
            with _make_user_todo_service(service_factory) as service:
                service.delete(todoId)
                return to_json(
                    {
                        "success": True,
                        "message": "已删除用户待办。",
                        "todoId": todoId,
                    }
                )

        return _run_task_service(
            "delete_user_todo", "删除用户待办时发生内部错误，请稍后重试。", _action
        )

    return delete_user_todo


# ===== 024 Task Graph Scheduling 工具 =====


BUILD_TASK_GRAPH_SCHEMA = make_tool_schema(
    name="build_task_graph",
    description=(
        "把一个复杂任务分解成一张带依赖关系的任务图并原子落库，交由 DAG 调度器按依赖自动推进。"
        "仅用于多步、有先后依赖或跨领域的复杂任务；1-2 步的简单任务直接用 "
        "delegate_to_subagent/specialist，不要建图。"
        "节点粒度=一个执行器（专员/子agent）的一次连贯执行；"
        "节点内部若≥3步，执行器会用 todo_update 自行分解子步骤。"
        "高风险/不可逆节点（发邮件、删数据、对外发送）必须标 needsConfirmation=true，"
        "调度器会在执行前暂停等主助理裁定。"
    ),
    properties={
        "nodes": {
            "type": "array",
            "minItems": 1,
            "description": "任务节点列表",
            "items": {
                "type": "object",
                "required": ["nodeId", "title", "description"],
                "properties": {
                    "nodeId": {
                        "type": "string",
                        "description": "节点稳定标识，用于 dependencies 引用",
                    },
                    "title": {"type": "string", "description": "节点标题"},
                    "description": {"type": "string", "description": "自包含的执行指令"},
                    "assigneeHint": {
                        "type": "string",
                        "enum": ["specialist", "ephemeral_subagent"],
                        "description": "建议执行器类型",
                    },
                    "assigneeId": {
                        "type": "string",
                        "description": "可选：具体 specialist id；没有具体 id 时 specialist hint 只作建议",
                    },
                    "capabilityScope": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "该节点允许的工具白名单",
                    },
                    "needsConfirmation": {
                        "type": "boolean",
                        "default": False,
                        "description": "高风险/不可逆节点标 true",
                    },
                },
            },
        },
        "dependencies": {
            "type": "array",
            "description": "先后依赖；from 必须先于 to 完成。无依赖的节点可并行。",
            "items": {
                "type": "object",
                "required": ["from", "to"],
                "properties": {
                    "from": {"type": "string", "description": "前置节点 nodeId"},
                    "to": {"type": "string", "description": "后继节点 nodeId"},
                },
            },
        },
    },
    required=["nodes"],
)


def _latest_user_message_sequence(session_id: str) -> int | None:
    try:
        from src.data.repos import MessageRepository

        with MessageRepository() as repo:
            return repo.get_latest_user_message_sequence(session_id)
    except Exception:
        logger.warning(
            "build_task_graph: failed to resolve latest user message sequence for %s",
            session_id,
            exc_info=True,
        )
        return None


def _trigger_graph_scheduler_start(graph_id: str, *, source: str) -> bool:
    try:
        from src.business.task_collaboration.graph_scheduler import get_graph_scheduler

        scheduler = get_graph_scheduler()
        if scheduler is None:
            return False
        scheduler.start_graph(graph_id)
        return True
    except Exception:
        logger.warning(
            "%s: scheduler start_graph failed for %s",
            source,
            graph_id,
            exc_info=True,
        )
        return False


def create_build_task_graph_handler(
    session_id: str,
    user_message_sequence_provider: Callable[[], int | None] | None = None,
    service_factory: Callable[[], "TaskCollaborationService"] | None = None,
):
    """工厂函数：创建 build_task_graph handler。"""

    def _task_graph_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.service import TaskCollaborationService

        return TaskCollaborationService()

    def build_task_graph_handler(
        nodes: list[dict] | None = None,
        dependencies: list[dict] | None = None,
    ) -> str:
        """将复杂任务分解成带依赖的 DAG 并原子落库。"""

        def _action() -> str:
            # workspaceRoot 是特权字段，只允许受信的 proposal_bridge 直连 service
            # 设置；LLM 工具入口（主助理 + 规划专员共享此 handler）必须剥离，避免
            # 执行体 blast radius 被重定向、proposal 沙箱守卫被绕过（026 C2）。
            sanitized_nodes = [
                {
                    k: v
                    for k, v in (node or {}).items()
                    if k not in ("workspaceRoot", "workspace_root")
                }
                for node in (nodes or [])
            ]
            with _task_graph_service() as service:
                result = service.build_task_graph(
                    session_id=session_id,
                    nodes=sanitized_nodes,
                    dependencies=dependencies,
                    user_message_sequence=(
                        user_message_sequence_provider()
                        if user_message_sequence_provider is not None
                        else _latest_user_message_sequence(session_id)
                    ),
                )
            # 024: 建图后触发 scheduler 推进就绪节点（FR-006 自动推进）。scheduler 未装配
            # 时优雅降级（图已持久化，后续 dispatch/recovery 兜底）。
            graph_id = result.get("graphId")
            if graph_id:
                _trigger_graph_scheduler_start(graph_id, source="build_task_graph")
            return to_json(result)

        return _run_task_service("build_task_graph", "建图时发生内部错误，请稍后重试。", _action)

    return build_task_graph_handler


MUTATE_TASK_GRAPH_SCHEMA = make_tool_schema(
    name="mutate_task_graph",
    description=(
        "在任务图自愈时修改图结构：新增节点、跳过节点、增删依赖边。"
        "仅当回流建议「改图」且确有必要时使用；"
        "每次变更会 bump graph_version 并重新过无环校验。"
    ),
    properties={
        "graphId": {"type": "string", "description": "任务图 ID"},
        "changes": {
            "type": "array",
            "description": "变更列表",
            "items": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": [
                            "add_node",
                            "skip_node",
                            "add_dependency",
                            "remove_dependency",
                        ],
                    },
                    "nodeId": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "assigneeHint": {
                        "type": "string",
                        "enum": ["specialist", "ephemeral_subagent"],
                    },
                    "assigneeId": {"type": "string"},
                    "capabilityScope": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "needsConfirmation": {"type": "boolean", "default": False},
                    "taskId": {"type": "string"},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
            },
        },
        "reason": {"type": "string", "description": "自愈理由（可追溯）"},
    },
    required=["graphId", "changes"],
)


def create_mutate_task_graph_handler(
    session_id: str,
    service_factory: Callable[[], "TaskCollaborationService"] | None = None,
):
    """工厂函数：创建 mutate_task_graph handler。"""

    def _task_graph_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.service import TaskCollaborationService

        return TaskCollaborationService()

    def mutate_task_graph_handler(
        graphId: str = "",
        changes: list[dict] | None = None,
        reason: str = "",
    ) -> str:
        """自愈改图。"""

        def _action() -> str:
            with _task_graph_service() as service:
                result = service.mutate_task_graph(
                    graph_id=graphId,
                    session_id=session_id,
                    changes=changes or [],
                    reason=reason,
                )
            if result.get("rescanned") and graphId:
                _trigger_graph_scheduler_start(graphId, source="mutate_task_graph")
            return to_json(result)

        return _run_task_service("mutate_task_graph", "改图时发生内部错误，请稍后重试。", _action)

    return mutate_task_graph_handler


# ===== 调度工具 =====


REPLY_TO_USER_SCHEMA = make_tool_schema(
    name="reply_to_user",
    description="向用户回复消息。这是你回复用户的主要方式——当你准备好直接回答用户时调用此工具。",
    properties={
        "text": {
            "type": "string",
            "description": "回复给用户的文本内容",
        },
        "memory_entries_referenced": {
            "type": "array",
            "items": {"type": "string"},
            "description": "本条回复引用的记忆条目 ID 列表，用于更新 referenced_count 计量",
        },
        "skills_referenced": {
            "type": "array",
            "items": {"type": "string"},
            "description": "本条回复实际按步骤执行过的方法论 skill_id 列表，用于更新 referenced_count 计量",
        },
    },
    required=["text"],
)


def create_reply_to_user_handler(session_id: str):
    """工厂函数：创建绑定了 session_id 的 reply_to_user handler。

    这是中断型工具（is_interrupting=True），返回 ToolSignal 而非 str。
    同步更新 memory_entries_referenced 中引用的条目的 referenced_count。
    """
    from src.business.agents.config import ResultType, ToolSignal

    def reply_to_user_handler(
        text: str,
        memory_entries_referenced: list[str] | None = None,
        skills_referenced: list[str] | None = None,
    ) -> ToolSignal:
        """向用户回复消息（中断型工具）"""
        referenced_ids: list[str] = []
        if isinstance(memory_entries_referenced, list) and all(
            isinstance(entry_id, str) for entry_id in memory_entries_referenced
        ):
            referenced_ids = [
                entry_id.strip() for entry_id in memory_entries_referenced if entry_id.strip()
            ]

        # 字段缺失或结构错误时静默跳过引用计数更新
        if referenced_ids:
            try:
                AssistantMemoryToolFacade().record_memory_references(referenced_ids)
                logger.info(
                    "[reply_to_user] referenced_count updated for %d entries",
                    len(referenced_ids),
                )
            except Exception as e:
                logger.warning("[reply_to_user] 更新 referenced_count 失败: %s", e)

        if isinstance(skills_referenced, list):
            try:
                AssistantMemoryToolFacade().record_skill_references(skills_referenced)
            except Exception as e:
                logger.warning("[reply_to_user] 更新方法论 referenced_count 失败: %s", e)

        return ToolSignal(
            result_type=ResultType.NEEDS_USER_INPUT,
            display_text=text,
        )

    return reply_to_user_handler


DELEGATE_TO_SUBAGENT_SCHEMA = make_tool_schema(
    name="delegate_to_subagent",
    description=(
        "将任务委托给一个临时子代理执行。统一任务图下异步执行，返回受理回执（accepted+taskId）；"
        "结果完成后经「任务结果回流提示」送达，由你用 decide_task_adjudication 裁定。"
    ),
    properties={
        "task_description": {
            "type": "string",
            "description": "要委托给子代理执行的任务描述",
        },
        "execution_context": {
            "type": "string",
            "description": "补充给子代理的执行上下文，例如用户约束、已知背景或输出格式要求",
        },
        "tool_whitelist": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选工具名称白名单；不传则继承当前助理会话可用技能池",
        },
    },
    required=["task_description"],
)


def create_delegate_to_subagent_handler(session_id: str, dispatch_callback=None):
    """工厂函数：创建 delegate_to_subagent handler。"""

    def delegate_to_subagent_handler(
        task_description: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
    ) -> str:
        """将任务委托给临时子代理"""
        try:
            logger.info(
                "[delegate_to_subagent] session=%s task_chars=%d context_chars=%d whitelist_count=%d",
                session_id,
                len(task_description or ""),
                len(execution_context or ""),
                len(tool_whitelist or []),
            )
            if dispatch_callback is not None:
                return to_json(
                    dispatch_callback(
                        parent_session_id=session_id,
                        task_description=task_description,
                        execution_context=execution_context or "",
                        tool_whitelist=tool_whitelist,
                    )
                )
            # 无 dispatch_callback（仅测试场景）时只返回占位结果；统一任务派发由
            # orchestrator 注入的 dispatch_callback 经 _dispatch_task_via_unified_model 收口。
            return to_json(
                {
                    "success": True,
                    "message": "任务已委托给临时子代理",
                    "delegation_type": "ephemeral_subagent",
                }
            )
        except Exception as e:
            logger.error("[delegate_to_subagent] 委派失败: %s", e, exc_info=True)
            return error_json("委派任务时发生内部错误，请稍后重试。")

    return delegate_to_subagent_handler


DECIDE_ADJUDICATION_SCHEMA = make_tool_schema(
    name="decide_task_adjudication",
    description=(
        "对子任务回传的结果做父侧裁定。认可→完成；打回→返工（需给 instruction）；"
        "放弃→失败并尝试别的办法。adjudication_id 来自任务结果回流提示。"
    ),
    properties={
        "adjudication_id": {
            "type": "string",
            "description": "回流结果提供的裁定ID",
        },
        "decision": {
            "type": "string",
            "enum": ["accepted", "returned", "abandoned"],
            "description": "认可 / 打回 / 放弃",
        },
        "instruction": {
            "type": "string",
            "description": "打回时的返工指示（打回必填）",
        },
    },
    required=["adjudication_id", "decision"],
)


def create_decide_task_adjudication_handler(
    session_id: str,
    service_factory: Callable[[], "TaskAdjudicationService"] | None = None,
):
    """工厂函数：创建 decide_task_adjudication handler（主助理对子任务结果裁定）。"""

    def _adjudication_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.adjudication import TaskAdjudicationService

        return TaskAdjudicationService()

    def decide_task_adjudication_handler(
        adjudication_id: str,
        decision: str,
        instruction: str = "",
    ) -> str:
        """对子任务结果做裁定（认可/打回/放弃）"""

        def _action():
            with _adjudication_service() as service:
                result = service.decide(
                    adjudication_id=adjudication_id,
                    decision=decision,
                    decided_by="agent",
                    instruction=instruction or None,
                    session_id=session_id,
                )
            return to_json(result)

        return _run_task_service(
            "decide_task_adjudication", "裁定任务结果时发生内部错误。", _action
        )

    return decide_task_adjudication_handler


ABANDON_REQUEST_GRAPH_SCHEMA = make_tool_schema(
    name="abandon_request_graph",
    description=(
        "当子任务失败导致本次用户请求（整张任务图）已无法继续完成时，显式放弃整个请求。"
        "根任务转 FAILED、级联取消下游，并触发安全失败卡告知用户'这步没办成'。"
        "仅在整个请求确实无法挽回时调用；单个子任务失败优先用 decide_task_adjudication "
        "放弃该子任务。safeSummary 必须是给用户看的安全文案，不得包含密钥/路径/原始错误。"
    ),
    properties={
        "safeSummary": {
            "type": "string",
            "description": "给用户看的安全失败摘要（已脱敏，不泄露密钥/路径/原始 provider 错误）",
        },
    },
    required=["safeSummary"],
)


def create_abandon_request_graph_handler(
    session_id: str,
    service_factory: Callable[[], "TaskAdjudicationService"] | None = None,
):
    """工厂函数：创建 abandon_request_graph handler（主助理放弃整个用户请求）。"""

    def _adjudication_service():
        if service_factory is not None:
            return service_factory()
        from src.business.task_collaboration.adjudication import TaskAdjudicationService

        return TaskAdjudicationService()

    def abandon_request_graph_handler(safeSummary: str) -> str:
        """放弃整个用户请求任务图（根任务失败，触发安全失败卡）"""

        def _action():
            with _adjudication_service() as service:
                result = service.fail_root_graph(
                    session_id=session_id,
                    safe_summary=safeSummary,
                )
            return to_json(result)

        return _run_task_service("abandon_request_graph", "放弃请求时发生内部错误。", _action)

    return abandon_request_graph_handler


CONTINUE_SUBAGENT_SCHEMA = make_tool_schema(
    name="continue_subagent",
    description=(
        "继续执行一个已暂停（suspended）的可唤回子代理。仅当 delegate_to_subagent 直接同步返回 "
        "paused=true 时使用——子代理达到迭代上限或可恢复失败会暂停，用此工具续跑配额、从断点接着跑；"
        "也可对已完成但未达标的子代理带追加指令返工。异步委派（返回 taskId）的子代理不要用本工具。"
    ),
    properties={
        "subagent_id": {
            "type": "string",
            "description": "仅当 delegate_to_subagent 直接返回 paused=true（同步路径）时获得的 subagent_id；异步委派返回的 taskId 不可用于本工具",
        },
        "instruction": {
            "type": "string",
            "description": "可选追加指令（例如指出还差什么、要避开的弯路）；不传则让子代理纯接着跑",
        },
        "extra_iterations": {
            "type": "integer",
            "description": "本次续跑额外允许的迭代次数，默认 20",
        },
    },
    required=["subagent_id"],
)


def create_continue_subagent_handler(session_id: str, continue_callback=None):
    """工厂函数：创建 continue_subagent handler。"""

    def continue_subagent_handler(
        subagent_id: str,
        instruction: str = "",
        extra_iterations: int = 20,
    ) -> str:
        """唤回子代理续跑"""
        try:
            logger.info(
                "[continue_subagent] session=%s subagent=%s instruction_chars=%d extra_iterations=%s",
                session_id,
                subagent_id,
                len(instruction or ""),
                extra_iterations,
            )
            if continue_callback is not None:
                return to_json(
                    continue_callback(
                        parent_session_id=session_id,
                        subagent_id=subagent_id,
                        instruction=instruction or "",
                        extra_iterations=extra_iterations,
                    )
                )
            return to_json({"success": False, "error": "续跑回调未注册"})
        except Exception as e:
            logger.error("[continue_subagent] 续跑失败: %s", e, exc_info=True)
            return error_json("续跑子代理时发生内部错误，请稍后重试。")

    return continue_subagent_handler


INSPECT_SUBAGENT_SCHEMA = make_tool_schema(
    name="inspect_subagent",
    description=(
        "查看一个已暂停（suspended）的可唤回子代理的工作概览（迭代轮数、调用过的工具及次数、最后产出、状态），"
        "用于判断它是任务复杂该续跑、还是走弯路该新开。只读，不消耗额外模型调用。"
        "仅当 delegate_to_subagent 直接同步返回 paused=true 时使用；异步委派（返回 taskId）的子代理不要用本工具。"
    ),
    properties={
        "subagent_id": {
            "type": "string",
            "description": "仅当 delegate_to_subagent 直接返回 paused=true（同步路径）时获得的 subagent_id；异步委派返回的 taskId 不可用于本工具",
        },
    },
    required=["subagent_id"],
)


def create_inspect_subagent_handler(session_id: str, inspect_callback=None):
    """工厂函数：创建 inspect_subagent handler。"""

    def inspect_subagent_handler(subagent_id: str) -> str:
        """查看子代理工作概览"""
        try:
            logger.info(
                "[inspect_subagent] session=%s subagent=%s",
                session_id,
                subagent_id,
            )
            if inspect_callback is not None:
                return to_json(
                    inspect_callback(
                        parent_session_id=session_id,
                        subagent_id=subagent_id,
                    )
                )
            return to_json({"success": False, "error": "查看回调未注册"})
        except Exception as e:
            logger.error("[inspect_subagent] 查看失败: %s", e, exc_info=True)
            return error_json("查看子代理时发生内部错误，请稍后重试。")

    return inspect_subagent_handler


DELEGATE_TO_SPECIALIST_SCHEMA = make_tool_schema(
    name="delegate_to_specialist",
    description="将任务委托给一个已命名的固定专员。专员拥有特定角色定义和工具白名单。",
    properties={
        "specialist_name": {
            "type": "string",
            "description": "专员名称",
        },
        "task": {
            "type": "string",
            "description": "要委托给专员的任务描述",
        },
    },
    required=["specialist_name", "task"],
)


def create_delegate_to_specialist_handler(session_id: str, dispatch_callback=None):
    """工厂函数：创建 delegate_to_specialist handler。"""

    def delegate_to_specialist_handler(specialist_name: str, task: str) -> str:
        """将任务委托给固定专员"""
        try:
            logger.info(
                "[delegate_to_specialist] session=%s specialist=%s task_chars=%d",
                session_id,
                specialist_name,
                len(task or ""),
            )
            if dispatch_callback is not None:
                return to_json(
                    dispatch_callback(
                        parent_session_id=session_id,
                        specialist_name=specialist_name,
                        task=task,
                    )
                )
            # 无 dispatch_callback（仅测试场景）时只返回占位结果；统一任务派发由
            # orchestrator 注入的 dispatch_callback 经 _dispatch_task_via_unified_model 收口。
            return to_json(
                {
                    "success": True,
                    "message": f"任务已委托给专员 '{specialist_name}'",
                    "delegation_type": "specialist",
                }
            )
        except Exception as e:
            logger.error("[delegate_to_specialist] 委派失败: %s", e, exc_info=True)
            return error_json("委派专员任务时发生内部错误，请稍后重试。")

    return delegate_to_specialist_handler


CREATE_SPECIALIST_SCHEMA = make_tool_schema(
    name="create_specialist",
    description="创建一个新的固定专员。专员拥有特定角色定义和工具白名单，可以被反复委派任务。",
    properties={
        "name": {
            "type": "string",
            "description": "专员名称（唯一标识）",
        },
        "description": {
            "type": "string",
            "description": "专员的简短描述",
        },
        "role_definition": {
            "type": "string",
            "description": "专员的角色定义（详细说明其职责和工作方式）",
        },
        "tool_whitelist": {
            "type": "array",
            "items": {"type": "string"},
            "description": "专员可以使用的工具名称白名单",
        },
    },
    required=["name", "description", "role_definition", "tool_whitelist"],
)


def create_create_specialist_handler(session_id: str):
    """工厂函数：创建 create_specialist handler。"""

    def create_specialist_handler(
        name: str,
        description: str,
        role_definition: str,
        tool_whitelist: list[str],
    ) -> str:
        """创建新专员"""
        try:
            specialist = AssistantSpecialistToolFacade().create_from_conversation(
                session_id=session_id,
                name=name,
                description=description,
                role_definition=role_definition,
                tool_whitelist=tool_whitelist,
            )
            logger.info("[create_specialist] 专员已创建: name=%s", name)
            return to_json(
                {
                    "success": True,
                    "message": f"专员 '{name}' 已创建",
                    "specialist_id": specialist["specialist_id"],
                }
            )
        except ValueError as e:
            return error_json(str(e))
        except Exception as e:
            logger.error("[create_specialist] 创建失败: %s", e, exc_info=True)
            return error_json("创建专员时发生内部错误，请稍后重试。")

    return create_specialist_handler

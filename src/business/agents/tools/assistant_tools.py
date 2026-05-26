"""
助理 Agent 专属工具（非动态用户工具）

这些工具把耗时的工具修复/工具化任务写入 DB 队列，由 AssistantTaskWorker 后台消费。
"""

import json
import logging
import threading
import time
import uuid
from src.utils.timezone import utc_now

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema, error_json, to_json
from src.business.brain.specialist_service import SpecialistService
from src.business.brain.retrieval_service import RetrievalService
from src.data.models_sqlite import PendingAssistantTask
from src.data.repos.brain_repository import BrainRepository
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
    tool_repo = ToolRepository()
    tool = tool_repo.get_by_name(tool_name)
    if not tool:
        return error_json(f"找不到工具 '{tool_name}'")

    task_id = str(uuid.uuid4())
    payload = to_json(
        {
            "tool_id": tool.tool_id,
            "tool_name": tool_name,
            "error_message": error_message,
            "user_input": user_input,
            "reported_at": utc_now().isoformat(),
        }
    )

    task_repo = PendingTaskRepository()
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

    logger.info(f"[report_tool_bug] 已提交 Bug 报告: tool={tool_name}, task={task_id}")
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
        messages = MessageRepository().get_by_session(session_id)
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

        repo = PendingTaskRepository()
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
        logger.info(f"[codify_as_tool] 已提交工具创建请求: {task_description}, task={task_id}")

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

            repo = AssistantProfileRepository()
            repo.save(display_name=display_name, style=style, notes=notes)

            # 就地替换当前会话 system prompt 中的 ## 关于用户 / ## 首次见面指引 段落
            msg_repo = MessageRepository()
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
                    logger.info(f"[save_profile] 当前会话 system prompt 已更新: {session_id}")

            logger.info(
                f"[save_profile] 用户偏好已保存: display_name={display_name}, style={style}"
            )
            return to_json({"success": True, "message": "偏好已保存"})
        except Exception as e:
            logger.error(f"[save_profile] 保存失败: {e}")
            return error_json(e)

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
        logger.error(f"[dismiss_suggestion] 失败: {e}")
        return error_json(e)


DISMISS_SUGGESTION = ToolDefinition(
    name="dismiss_suggestion",
    schema=DISMISS_SUGGESTION_SCHEMA,
    handler=dismiss_suggestion_handler,
)


# ===== 归档检索工具 (T057) =====


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
        service = RetrievalService()
        results = service.retrieve_archive(query)
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
        logger.error("[retrieve_archive] failed: %s", e)
        return to_json(
            {
                "success": False,
                "message": str(e),
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
        service = RetrievalService()
        entries = service.retrieve_failure_zone(context)
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
        logger.error("[retrieve_failure_zone] failed: %s", e)
        return error_json(e)


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
    from src.business.brain.context_builder import BrainContextBuilder

    context = BrainContextBuilder().build_context(session_id, track_loaded=False)
    entry_ids = set(context.injected_entry_ids)
    entry_ids.update(_retrieved_context_entry_ids_for_session(session_id))
    return list(entry_ids)


def create_invalidate_memory_entry_handler(session_id: str | None = None):
    """工厂函数：创建绑定当前上下文窗口的 invalidate_memory_entry handler。"""

    def invalidate_memory_entry_handler(
        entry_id: str,
        reason: str,
        invalidation_type: str = "reactive",
    ) -> str:
        """将当前上下文窗口内的一条记忆标记为 invalidated。"""
        try:
            from src.data.repos.brain_repository import BrainRepository

            with BrainRepository() as repo:
                service = RetrievalService(brain_repo=repo)
                result = service.invalidate_memory_entry(
                    entry_id,
                    reason,
                    current_context_entry_ids=_context_entry_ids_for_session(session_id),
                )
                _annotate_invalidation_disclosure(result, invalidation_type)
                return to_json(result)
        except Exception as e:
            logger.error("[invalidate_memory_entry] failed: %s", e)
            return error_json(e)

    return invalidate_memory_entry_handler


def _annotate_invalidation_disclosure(result: dict, invalidation_type: str) -> None:
    if (
        not isinstance(result, dict)
        or invalidation_type != "proactive"
        or not result.get("success")
    ):
        return
    result["requires_user_disclosure"] = True
    result["disclosure_instruction"] = (
        "你主动发现了记忆冲突。必须在同一轮 reply_to_user 中告知用户已将这条记忆标记为失效。"
    )


INVALIDATE_MEMORY_ENTRY = ToolDefinition(
    name="invalidate_memory_entry",
    schema=INVALIDATE_MEMORY_ENTRY_SCHEMA,
    handler=create_invalidate_memory_entry_handler(None),
)


# ===== 调度工具 (T069, T070) =====


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
                with BrainRepository() as repo:
                    repo.batch_update_referenced_counts(referenced_ids)
                logger.info(
                    "[reply_to_user] referenced_count updated for %d entries",
                    len(referenced_ids),
                )
            except Exception as e:
                logger.warning("[reply_to_user] 更新 referenced_count 失败: %s", e)

        return ToolSignal(
            result_type=ResultType.NEEDS_USER_INPUT,
            display_text=text,
        )

    return reply_to_user_handler


DELEGATE_TO_SUBAGENT_SCHEMA = make_tool_schema(
    name="delegate_to_subagent",
    description="将任务委托给一个临时子代理执行。子代理会独立完成任务并返回结果。",
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
            return to_json(
                {
                    "success": True,
                    "message": "任务已委托给临时子代理",
                    "delegation_type": "ephemeral_subagent",
                }
            )
        except Exception as e:
            logger.error("[delegate_to_subagent] 委派失败: %s", e)
            return error_json(e)

    return delegate_to_subagent_handler


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
            return to_json(
                {
                    "success": True,
                    "message": f"任务已委托给专员 '{specialist_name}'",
                    "delegation_type": "specialist",
                }
            )
        except Exception as e:
            logger.error("[delegate_to_specialist] 委派失败: %s", e)
            return error_json(e)

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
            service = SpecialistService()
            specialist = service.create_specialist(
                name=name,
                description=description,
                role_definition=role_definition,
                tool_whitelist=tool_whitelist,
                origin="user_conversation",
                reason=f"由用户在会话 {session_id[:8]}... 中创建",
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
            logger.error("[create_specialist] 创建失败: %s", e)
            return error_json(e)

    return create_specialist_handler

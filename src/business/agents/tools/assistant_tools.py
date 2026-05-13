"""
助理 Agent 专属工具（非动态用户工具）

这些工具把耗时的工具修复/工具化任务写入 DB 队列，由 AssistantTaskWorker 后台消费。
"""

import json
import logging
import uuid
from src.utils.timezone import utc_now

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema, error_json, to_json
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

__all__ = [
    "REPORT_TOOL_BUG",
    "SAVE_PROFILE_SCHEMA",
    "create_save_profile_handler",
    "CODIFY_AS_TOOL_SCHEMA",
    "create_codify_as_tool_handler",
    "DISMISS_SUGGESTION",
    "register_task_worker_notify",
]

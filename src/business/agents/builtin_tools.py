"""
内置工具定义

定义所有 Agent 共享的内置工具。
load_reference 由 AgentLoop 自动追加到每次请求的工具列表中，
handler 由 ContextManager 提供，不进入 hook 管线。

talk_to_user 已整体移除（向用户输出统一）：主助理走 reply_to_user 显式工具，
PM/Trial 走 text_as_user_input=True 的纯文本对话，子代理/专员向上沟通走 ask_parent。
历史会话中已存的 talk_to_user tool_calls 由 agent_session_store 展示层反查兼容。
"""

from .tool_helpers import make_tool_schema

# load_reference 由 AgentLoop 内部处理，不在注册表中
LOAD_REFERENCE_SCHEMA = make_tool_schema(
    name="load_reference",
    description="加载显式 REF 指向的原始内容，适用于跨会话摘要或历史引用下钻。",
    properties={
        "reference_id": {"type": "string", "description": "要加载的引用 ID（消息 ID 或摘要 ID）"}
    },
    required=["reference_id"],
)


__all__ = [
    "LOAD_REFERENCE_SCHEMA",
]

"""
内置工具定义

定义所有 Agent 共享的内置工具。
"""

# talk_to_user 是哨兵工具，无实际执行逻辑
TALK_TO_USER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "talk_to_user",
        "description": "向用户提问，等待用户回复。这是一个中断信号，不会实际执行。",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "要向用户提出的问题"
                }
            },
            "required": ["message"]
        }
    }
}

# load_reference 由 AgentLoop 内部处理，不在注册表中
LOAD_REFERENCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_reference",
        "description": "加载被引用替换的原始消息内容。当工具结果被引用替换时，使用此工具获取完整内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "要加载的消息 ID"
                }
            },
            "required": ["message_id"]
        }
    }
}


__all__ = [
    "TALK_TO_USER_SCHEMA",
    "LOAD_REFERENCE_SCHEMA",
]
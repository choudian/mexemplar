"""
记忆机制模块

Agent Loop 的记忆管理系统，负责：
- 引用替换：将旧的大体积 tool result 替换为指针
- 会话压缩：使用 LLM 对旧消息生成摘要
- 上下文组装：加载消息、应用压缩和引用替换

三个 Agent 共用同一套记忆机制，行为通过配置参数调节。

依赖：
- 数据层：MessageRepository, SessionRepository
- 配置：UnifiedConfigManager
- AI：LLM 客户端（用于压缩）

使用示例：
    from src.data.unified_config import get_unified_config
    from src.business.memory import ContextManager

    config = get_unified_config()
    ctx = ContextManager(session_id, config)

    # 组装上下文
    messages = ctx.assemble_context()

    # 保存消息
    ctx.save_user_message("用户输入")
    ctx.save_assistant_message("AI回复")

    # 加载引用
    ctx.load_reference(message_id)
"""

from .context_manager import ContextManager

__all__ = ["ContextManager"]
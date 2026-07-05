"""
MCP (Model Context Protocol) 业务模块 — 管理第三方 MCP server 的配置、
子进程生命周期、工具注册和 AI 自动调用。

核心组件：
- McpServerService: server 生命周期编排（配置→启动→运行→停止）
- McpProcessManager: 子进程管理 + async 事件循环 + SDK 桥接
- McpToolRegistry: 进程级 MCP 工具注册表（双轨：预置全量 + 自定义独立 LRU）
- McpSessionProtocol: 业务层 Session 抽象（N9：返回业务类型，不泄漏 SDK 类型）

辅助模块：
- models: 业务模型（McpServerConfigPublic / McpLaunchPayload / McpToolInfo / McpCallResult）
- mcp_errors: 错误分类映射 → suggestion
- mcp_env_resolver: ${VAR} 环境变量解析
- mcp_json_import: JSON 配置解析（三种格式）+ secret 自动检测
- mcp_presets: 预置 server 默认配置
- mcp_search_tools: MCP-aware search_tools / get_tool_detail wrapper
"""

# 延迟导入——避免 SDK import 失败时阻塞整个模块
# 调用方应使用 get_mcp_server_service() / get_mcp_tool_registry() 单例入口

import logging
import threading

from src.business.mcp.models import (
    McpCallResult,
    McpLaunchPayload,
    McpServerConfigPublic,
    McpServerStatus,
    McpToolInfo,
)

logger = logging.getLogger(__name__)

__all__ = [
    "McpCallResult",
    "McpLaunchPayload",
    "McpServerConfigPublic",
    "McpServerStatus",
    "McpToolInfo",
    "get_mcp_server_service",
    "get_mcp_tool_registry",
]

_mcp_server_service = None
_mcp_tool_registry = None
_singleton_lock = threading.Lock()


def get_mcp_server_service():
    """获取 McpServerService 单例。SDK 不可用时内部使用 NullRegistry 降级，始终返回非 None 实例。"""
    global _mcp_server_service
    if _mcp_server_service is not None:
        return _mcp_server_service
    with _singleton_lock:
        # double-checked locking
        if _mcp_server_service is not None:
            return _mcp_server_service
        from src.business.mcp.mcp_server_service import McpServerService

        _mcp_server_service = McpServerService()
        return _mcp_server_service


def get_mcp_tool_registry():
    """获取 McpToolRegistry 单例。SDK import 失败时返回 NullRegistry。"""
    global _mcp_tool_registry
    if _mcp_tool_registry is not None:
        return _mcp_tool_registry
    with _singleton_lock:
        # double-checked locking
        if _mcp_tool_registry is not None:
            return _mcp_tool_registry

        # NullRegistry 无 SDK 依赖，先导入作 fallback
        from src.business.mcp.mcp_tool_registry import NullRegistry

        try:
            from src.business.mcp.mcp_tool_registry import McpToolRegistry
            _mcp_tool_registry = McpToolRegistry()
        except ImportError:
            logger.warning("[MCP] MCP SDK import failed, using NullRegistry")
            _mcp_tool_registry = NullRegistry()
        except Exception:
            logger.exception("[MCP] McpToolRegistry init failed unexpectedly, using NullRegistry")
            _mcp_tool_registry = NullRegistry()
        return _mcp_tool_registry


def reset_mcp_singletons():
    """重置单例（仅供测试使用）。"""
    global _mcp_server_service, _mcp_tool_registry
    with _singleton_lock:
        _mcp_server_service = None
        _mcp_tool_registry = None

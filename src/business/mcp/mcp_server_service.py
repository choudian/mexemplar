"""
McpServerService — MCP server 生命周期管理 + 同步桥接 + 事件循环崩溃恢复。

编排 McpProcessManager + McpToolRegistry + McpServerRepository + UnifiedConfigManager。
"""

import asyncio
import json
import logging
import re
import threading

from src.business.mcp.mcp_errors import (
    McpCircuitBreakerOpenError,
    McpServerDisconnectedError,
    McpToolSchemaValidationError,
    McpToolTimeoutError,
    classify_runtime_error,
    classify_startup_error,
)
from src.business.mcp.mcp_process_manager import McpProcessManager
from src.business.mcp.mcp_tool_registry import McpToolRegistry, NullRegistry
from src.business.mcp.mcp_env_resolver import (
    check_missing_placeholders,
)
from src.business.mcp.models import (
    McpCallResult,
    McpServerConfigPublic,
    McpServerStatus,
    McpToolInfo,
)
from src.data.repos.mcp_server_repository import McpServerRepository
from src.data.unified_config import get_unified_config
from src.utils.events import emit
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

# 断路器阈值（E8）
_CIRCUIT_BREAKER_THRESHOLD = 3

# 错误信息脱敏模式（与 proposal_service 同源）
_ERROR_REDACT_PATTERNS = [
    re.compile(r"(ghp_[a-zA-Z0-9]{30,})", re.IGNORECASE),
    re.compile(r"(gho_[a-zA-Z0-9]{30,})", re.IGNORECASE),
    re.compile(r"(sk-[a-zA-Z0-9\-]{20,})", re.IGNORECASE),
    re.compile(r"(token[_\-]?[a-zA-Z0-9]{10,})", re.IGNORECASE),
    re.compile(r"(key[_\-]?[a-zA-Z0-9]{10,})", re.IGNORECASE),
    re.compile(r"(bearer\s+[a-zA-Z0-9\-._~+/]+=*)", re.IGNORECASE),
    re.compile(r"(https?://[^:/\s]+:[^:/\s]+@)", re.IGNORECASE),
]


def _sanitize_error_text(text: str, max_len: int = 500) -> str:
    """脱敏错误文本中的密钥模式，防止泄漏到 DB 或 API。"""
    for pattern in _ERROR_REDACT_PATTERNS:
        text = pattern.sub("***", text)
    return text[:max_len]


class McpServerService:
    """MCP server 生命周期管理服务。

    编排 ProcessManager + ToolRegistry + Repository + UnifiedConfigManager。
    订阅 mcp_server_disconnected 事件，在 ping 失败或 call_tool 异常断连时
    注销工具并更新 DB 状态。
    """

    def __init__(self):
        self._process_manager = McpProcessManager()
        self._consecutive_failures: dict[str, int] = {}  # 进程级，sidecar 重启复位
        self._lock = threading.Lock()

        # 使用全局单例 registry（与 tool_registry.py/tool_factory 共享同一实例）
        from src.business.mcp import get_mcp_tool_registry
        self._registry = get_mcp_tool_registry()

        # 订阅 ProcessManager 断连事件（ping/call_tool 异常触发）
        from src.utils.events import connect
        connect("mcp_server_disconnected", self._on_server_disconnected, weak=False)

    @property
    def process_manager(self) -> McpProcessManager:
        return self._process_manager

    @property
    def registry(self) -> McpToolRegistry | NullRegistry:
        return self._registry

    @property
    def sdk_available(self) -> bool:
        return self._process_manager.sdk_available

    # ─── CRUD + 生命周期 ───

    def add_server(self, **kwargs) -> dict:
        """添加 server：validate + save config（secrets→app_settings）+ auto-start if enabled。

        kwargs 同 McpServerRepository.create_server 的参数。
        """
        # 校验 transport
        transport = kwargs.get("transport", "stdio")
        if transport == "http":
            raise ValueError("HTTP transport 尚未支持")

        # 检查 ${VAR} 占位符
        env = kwargs.get("env", {})
        if env:
            missing = check_missing_placeholders(env)
            if missing:
                raise ValueError(f"以下环境变量占位符未解析: {', '.join(missing)}")

        # secret 自动检测
        from src.business.mcp.mcp_json_import import detect_secret_keys_in_dict
        detected_env_secrets = detect_secret_keys_in_dict(env)
        detected_header_secrets = detect_secret_keys_in_dict(kwargs.get("headers", {}))

        # 合并显式声明和自动检测
        explicit_env_secrets = kwargs.get("secret_env_keys", []) or []
        explicit_header_secrets = kwargs.get("secret_header_keys", []) or []
        all_env_secrets = list(set(explicit_env_secrets) | set(detected_env_secrets))
        all_header_secrets = list(set(explicit_header_secrets) | set(detected_header_secrets))

        # 构建不可变 fields dict，不修改调用方 kwargs
        fields = {**kwargs}
        fields["secret_env_keys"] = all_env_secrets
        fields["secret_header_keys"] = all_header_secrets

        # 分离 secret 值
        env = dict(env)  # 复制避免修改传入参数
        headers = dict(kwargs.get("headers", {}) or {})
        secret_env_values = {k: env.pop(k) for k in all_env_secrets if k in env}
        secret_header_values = {k: headers.pop(k) for k in all_header_secrets if k in headers}

        fields["env"] = env
        fields["headers"] = headers

        # 创建 DB 行
        with McpServerRepository() as repo:
            row = repo.create_server(**fields)
            server_id = row.server_id

        # 存储 secret 到 UnifiedConfigManager
        self._save_secrets(server_id, secret_env_values, secret_header_values)

        # auto-start if enabled
        if row.enabled:
            config = McpServerConfigPublic.from_row(row)
            try:
                self._start_and_register(server_id, config)
            except Exception as exc:
                logger.error("[MCP] auto-start server %s failed: %s", server_id, exc)
                suggestion = classify_startup_error(exc)
                with McpServerRepository() as repo:
                    repo.update_status(
                        server_id,
                        status="failed",
                        error=_sanitize_error_text(str(exc)),
                        suggestion=suggestion,
                    )

        return self._get_server_detail(server_id)

    def update_server(self, server_id: str, **fields) -> dict:
        """更新 server 配置：merge fields + update secrets + auto-restart if running。"""
        was_running = self._process_manager.is_server_running(server_id)

        # 分离 secret 值
        env = fields.get("env")
        headers = fields.get("headers")
        secret_env_keys = fields.get("secret_env_keys", []) or []
        secret_header_keys = fields.get("secret_header_keys", []) or []

        secret_env_values = {}
        secret_header_values = {}

        if env is not None:
            env = dict(env)
            for k in secret_env_keys:
                if k in env:
                    secret_env_values[k] = env.pop(k)

        if headers is not None:
            headers = dict(headers)
            for k in secret_header_keys:
                if k in headers:
                    secret_header_values[k] = headers.pop(k)

        # 更新 DB
        with McpServerRepository() as repo:
            row = repo.update_config(server_id, **fields)
            if row is None:
                raise LookupError(f"MCP server 不存在: {server_id}")

        # 更新 secrets
        if secret_env_values or secret_header_values:
            self._save_secrets(server_id, secret_env_values, secret_header_values)

        # auto-restart if was running
        if was_running:
            config = McpServerConfigPublic.from_row(row)
            try:
                tools = self._process_manager.reconnect_server(server_id, config)
                self._register_tools_from_start(server_id, config, tools)
                self._on_server_started(server_id, config)
            except Exception as exc:
                logger.error("[MCP] auto-restart server %s failed: %s", server_id, exc)
                suggestion = classify_startup_error(exc)
                with McpServerRepository() as repo:
                    repo.update_status(
                        server_id,
                        status="failed",
                        error=_sanitize_error_text(str(exc)),
                        suggestion=suggestion,
                        circuit_breaker_open=False,
                    )

        return self._get_server_detail(server_id)

    def delete_server(self, server_id: str) -> bool:
        """删除 server：stop if running + cleanup app_settings + delete DB row。"""
        # 停止运行中的 server（stop 失败仍继续清理，避免阻止删除）
        if self._process_manager.is_server_running(server_id):
            try:
                self._process_manager.stop_server(server_id)
            except RuntimeError as exc:
                logger.warning("[MCP] stop failed during delete of %s: %s", server_id, exc)

        # 注销工具
        self._registry.unregister_server_tools(server_id)

        # 清理 app_settings
        self._cleanup_secrets(server_id)

        # 清理断路器计数（防止无界增长）
        with self._lock:
            self._consecutive_failures.pop(server_id, None)

        # 删除 DB 行
        with McpServerRepository() as repo:
            return repo.delete_server(server_id)

    # ─── 启停 ───

    def start_server(self, server_id: str) -> dict:
        """启动 server。"""
        config = self._get_public_config(server_id)
        self._start_and_register(server_id, config)
        return self._get_server_detail(server_id)

    def stop_server(self, server_id: str) -> dict:
        """停止 server。"""
        self._process_manager.stop_server(server_id)
        self._registry.unregister_server_tools(server_id)
        self._on_server_stopped(server_id)
        return self._get_server_detail(server_id)

    def reconnect_server(self, server_id: str) -> dict:
        """重连 = stop + start。失败时递增断路器计数。"""
        config = self._get_public_config(server_id)
        try:
            tools = self._process_manager.reconnect_server(server_id, config)
        except Exception:
            # 重连失败也递增断路器计数（与 call_tool_sync 一致）
            self._consecutive_failures[server_id] = self._consecutive_failures.get(server_id, 0) + 1
            raise
        self._register_tools_from_start(server_id, config, tools)
        self._on_server_started(server_id, config)

        # P2-MA5: 重连成功后 emit tools.changed
        emit("tools_changed", tool_id=server_id, action="mcp_server_reconnected")

        return self._get_server_detail(server_id)

    def test_connection(
        self, server_id: str
    ) -> tuple[list[McpToolInfo], str | None]:
        """测试 server 连接：临时启动 + list_tools + 立即停止。

        不触碰全局 registry、不 emit 事件、不更新 DB 状态，
        确保测试连接操作对系统无可见副作用。

        Returns:
            (tools, error) — 成功时 error 为 None，失败时 tools 为空列表。
        """
        config = self._get_public_config(server_id)
        try:
            # 仅启动进程 + list_tools，不注册到全局 registry
            tools = self._process_manager.start_server(server_id, config)
            # 测试成功后停止
            self._process_manager.stop_server(server_id)
            return tools, None
        except Exception as exc:
            # 清理：确保进程已停止
            try:
                self._process_manager.stop_server(server_id)
            except Exception:
                pass
            return [], _sanitize_error_text(str(exc))

    def enable_server(self, server_id: str) -> dict:
        """启用 server：set enabled=True + start。"""
        with McpServerRepository() as repo:
            repo.set_enabled(server_id, True)
        result = self.start_server(server_id)
        return result

    def disable_server(self, server_id: str) -> dict:
        """禁用 server：stop + set enabled=False。"""
        self.stop_server(server_id)
        with McpServerRepository() as repo:
            repo.set_enabled(server_id, False)
        return self._get_server_detail(server_id)

    def start_all_enabled(self) -> None:
        """启动所有 enabled server（非阻塞，E7 try/except）。"""
        with McpServerRepository() as repo:
            enabled_rows = repo.list_enabled()

        configs: list[tuple[str, McpServerConfigPublic]] = []
        for row in enabled_rows:
            config = McpServerConfigPublic.from_row(row)
            configs.append((row.server_id, config))

        if not configs:
            return

        loop = self._process_manager.get_or_create_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._process_manager.start_all_enabled(configs), loop
        )

        try:
            results = future.result(timeout=120)
            # 处理结果：成功则注册工具，失败则更新状态
            for i, (server_id, config) in enumerate(configs):
                result = results[i] if i < len(results) else None
                if isinstance(result, Exception):
                    suggestion = classify_startup_error(result)
                    with McpServerRepository() as repo:
                        repo.update_status(
                            server_id,
                            status="failed",
                            error=_sanitize_error_text(str(result)),
                            suggestion=suggestion,
                        )
                    # RC11: emit backend_resync_required
                    emit("backend_resync_required", reason="mcp_server_failed")
                elif isinstance(result, list):
                    # 成功：注册工具
                    self._register_tools_from_start(server_id, config, result)
        except Exception as exc:
            logger.error("[MCP] start_all_enabled failed: %s", exc)

    def stop_all(self) -> None:
        """停止所有 running server。"""
        loop = self._process_manager.get_or_create_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._process_manager.stop_all(), loop
        )
        try:
            future.result(timeout=10)
        except Exception as exc:
            logger.warning("[MCP] stop_all failed: %s", exc)

    # ─── 工具调用 ───

    def call_tool_sync(
        self, server_id: str, tool_name: str, args: dict
    ) -> McpCallResult:
        """同步调用工具，含断路器检查（E8）。"""
        # 断路器检查
        with self._lock:
            failures = self._consecutive_failures.get(server_id, 0)
            if failures >= _CIRCUIT_BREAKER_THRESHOLD:
                raise McpCircuitBreakerOpenError(server_id)

        try:
            result = self._process_manager.call_tool_sync(server_id, tool_name, args)
            # 成功：重置计数
            with self._lock:
                self._consecutive_failures[server_id] = 0
            return result
        except (McpServerDisconnectedError, McpToolTimeoutError,
                McpToolSchemaValidationError) as exc:
            # 失败：增加计数
            with self._lock:
                self._consecutive_failures[server_id] = (
                    self._consecutive_failures.get(server_id, 0) + 1
                )
                if self._consecutive_failures[server_id] >= _CIRCUIT_BREAKER_THRESHOLD:
                    with McpServerRepository() as repo:
                        repo.update_status(
                            server_id,
                            status="failed",
                            error="断路器打开：连续失败超阈值",
                            suggestion="server 连续失败，请重连后重试",
                            circuit_breaker_open=True,
                        )
            raise

    # ─── 状态查询 ───

    def get_server_status(self, server_id: str) -> dict:
        """合并 DB 状态 + 运行时状态。"""
        return self._get_server_detail(server_id)

    def list_servers(self) -> list[dict]:
        """列出所有 server 的详情。"""
        with McpServerRepository() as repo:
            rows = repo.list_all()
        return [self._row_to_detail(row) for row in rows]

    def get_server(self, server_id: str) -> dict | None:
        """获取单个 server 详情。"""
        try:
            return self._get_server_detail(server_id)
        except LookupError:
            return None

    def get_or_create_event_loop(self):
        """访问 ProcessManager 的事件循环。"""
        return self._process_manager.get_or_create_event_loop()

    # ─── 预置 server 引导 ───

    def seed_preset_servers(self) -> None:
        """N19: 在 lifespan 启动时从 mcp_presets.py upsert 缺失的预置 server。"""
        from src.business.mcp.mcp_presets import load_preset_defaults

        defaults = load_preset_defaults()

        with McpServerRepository() as repo:
            existing_slugs = set(repo.list_preset_slugs())

        for preset in defaults:
            if preset.slug in existing_slugs:
                continue  # 用户修改过的预置 server 不强制覆盖

            try:
                with McpServerRepository() as repo:
                    repo.create_server(
                        name=preset.name,
                        transport="stdio",
                        command=preset.command,
                        args=preset.args,
                        env=preset.non_secret_env,
                        secret_env_keys=[],
                        is_preset=True,
                        preset_slug=preset.slug,
                        enabled=False,  # 默认不启用
                    )
                logger.info("[MCP] seeded preset server: %s", preset.slug)
            except ValueError:
                # name 冲突（用户可能已创建同名 server），跳过
                logger.debug("[MCP] preset %s skipped (name conflict)", preset.slug)

    # ─── 内部方法 ───

    def _start_and_register(
        self, server_id: str, config: McpServerConfigPublic
    ) -> list[McpToolInfo]:
        """启动 server 并注册工具。"""
        tools = self._process_manager.start_server(server_id, config)
        self._register_tools_from_start(server_id, config, tools)
        self._on_server_started(server_id, config)
        return tools

    def _register_tools_from_start(
        self,
        server_id: str,
        config: McpServerConfigPublic,
        tools: list[McpToolInfo],
    ) -> None:
        """注册启动发现的工具到 registry 和 DB。"""
        slug = self._slugify(config.name)
        is_preset = config.is_preset

        # 注册到 registry（先注册目录项，再逐个注册 ToolDefinition）
        self._registry.register_server_tools(
            server_id, slug, tools, is_preset
        )

        # 构建 ToolDefinition 并注册
        for tool in tools:
            full_name = f"mcp__{slug}__{tool.name}"
            tool_def = self._build_tool_definition(server_id, tool.name, full_name, tool)
            self._registry.register_tool_definition(
                full_name, tool_def, server_id, is_preset
            )

        # 更新 DB 工具缓存
        tools_json = json.dumps([t.to_dict() for t in tools])
        with McpServerRepository() as repo:
            repo.update_status(
                server_id,
                status="running",
                error=None,
                suggestion=None,
                tool_count=len(tools),
                tools_json=tools_json,
            )

    def _build_tool_definition(
        self,
        server_id: str,
        tool_name: str,
        full_name: str,
        tool_info: McpToolInfo,
    ) -> "ToolDefinition":
        """构建 MCP 工具的 ToolDefinition（含 sync handler + pre_hook）。"""
        from src.business.agents.config import ToolDefinition

        # 构建 handler
        handler = self._create_sync_handler(server_id, tool_name, full_name)

        # 构建 schema
        schema = {
            "name": full_name,
            "description": (tool_info.description or "")[:500],
            "parameters": tool_info.input_schema or {
                "type": "object",
                "properties": {},
            },
        }

        # 构建 pre_hook
        pre_hook = self._create_pre_hook(full_name)

        return ToolDefinition(
            name=full_name,
            schema=schema,
            handler=handler,
            has_side_effects=True,  # N11: 保守默认
            is_concurrency_safe=False,  # N11: 一律串行
            pre_hook=pre_hook,
        )

    def _create_sync_handler(self, server_id: str, tool_name: str, full_name: str):
        """为 MCP 工具创建同步 handler。"""
        def handler(**kwargs) -> str:
            try:
                result = self.call_tool_sync(server_id, tool_name, kwargs)
                return self._format_mcp_result(full_name, result)
            except McpServerDisconnectedError:
                return _mcp_error_json(
                    full_name, "mcp_server_disconnected",
                    "MCP server 连接已断开，去工具列表重连后重试",
                    retryable=True, next_action="reconnect_server",
                )
            except McpToolTimeoutError:
                return _mcp_error_json(
                    full_name, "mcp_tool_timeout",
                    f"MCP tool '{tool_name}' 调用超时",
                    retryable=True,
                )
            except McpToolSchemaValidationError:
                return _mcp_error_json(
                    full_name, "mcp_tool_schema_validation_error",
                    f"MCP tool '{tool_name}' 输出格式异常",
                )
            except McpCircuitBreakerOpenError:
                return _mcp_error_json(
                    full_name, "mcp_circuit_open",
                    "MCP server 连续失败，请重连后重试",
                    next_action="reconnect_server",
                )
            except Exception as e:
                suggestion = classify_runtime_error(e)
                return _mcp_error_json(full_name, "mcp_tool_error", suggestion)
        return handler

    def _create_pre_hook(self, full_name: str):
        """创建 MCP 工具的 pre_hook（高危确认穿透，R5）。"""
        def pre_hook(context):
            # 从 context 提取 args（兼容 ToolCallContext 对象和裸 dict）
            try:
                args_dict = dict(context.args) if context.args else {}
            except (AttributeError, TypeError):
                args_dict = {}
            if _is_likely_write_operation(full_name, args_dict):
                # 穿透现有确认协议
                try:
                    from src.business.agents.tools.builtin_general_tools import (
                        _confirm_or_reject,
                    )
                    rejected = _confirm_or_reject(
                        full_name,
                        f"MCP 工具 {full_name} 可能是写操作，确认执行？"
                    )
                    if rejected is not None:
                        return rejected  # PreHookResult 类型，与 AgentLoop 兼容
                except ImportError:
                    # 确认模块不可用时 fail-closed：返回 PreHookResult 拒绝写操作
                    from src.business.agents.hook_models import PreHookResult
                    return PreHookResult(
                        error=f"无法确认 MCP 写操作 {full_name}，确认模块不可用",
                        error_code="confirmation_failed_closed",
                    )
            return None
        return pre_hook

    def _format_mcp_result(self, tool_name: str, result: McpCallResult) -> str:
        """适配 MCP 结果到统一 envelope（CC-005/FR-011）。

        使用标准 success_json/error_json 构建 envelope，使 AgentLoop 的
        govern_tool_result 能正确解析、压缩大输出并创建 ToolOutputRepository artifact。
        envelope 标记 source=mcp（N12 prompt injection 防御）。
        """
        from src.business.agents.tools.builtin_contracts import (
            error_json,
            success_json,
        )

        if result.is_error:
            return error_json(
                tool_name,
                code="mcp_tool_error",
                message="\n".join(result.text_parts)[:2000],
                payload={"source": "mcp"},
            )

        output = "\n".join(result.text_parts)
        return success_json(
            tool_name,
            payload={
                "content": output,
                "source": "mcp",  # N12: 标记外部不可信
            },
        )

    def _on_server_started(self, server_id: str, config: McpServerConfigPublic):
        """server 启动成功回调：更新 DB + registry + emit tools.changed。"""
        # 重置断路器计数
        with self._lock:
            self._consecutive_failures[server_id] = 0

        emit("tools_changed", tool_id=server_id, action="mcp_server_started")

    def _on_server_stopped(self, server_id: str):
        """server 停止回调：更新 DB 状态。"""
        with McpServerRepository() as repo:
            repo.update_status(server_id, status="stopped", error=None, suggestion=None)

    def _on_server_disconnected(self, sender, *, server_id: str, error: str, **kwargs):
        """ProcessManager 断连事件回调：注销工具 + 更新 DB 状态。

        由 ping 失败或 call_tool 异常触发的 _mark_disconnected emit。
        """
        self._registry.unregister_server_tools(server_id)
        with McpServerRepository() as repo:
            repo.update_status(
                server_id,
                status="disconnected",
                error=_sanitize_error_text(error),
                suggestion="server 连接断开，请重连后重试",
            )

    def _get_public_config(self, server_id: str) -> McpServerConfigPublic:
        """从 DB 获取 server 公共配置。"""
        with McpServerRepository() as repo:
            row = repo.get_by_id(server_id)
        if row is None:
            raise LookupError(f"MCP server 不存在: {server_id}")
        return McpServerConfigPublic.from_row(row)

    def get_server_detail(self, server_id: str) -> dict:
        """获取 server 详情（合并 DB + 运行时）。公共接口。"""
        return self._get_server_detail(server_id)

    def _get_server_detail(self, server_id: str) -> dict:
        """获取 server 详情（合并 DB + 运行时）。"""
        with McpServerRepository() as repo:
            row = repo.get_by_id(server_id)
        if row is None:
            raise LookupError(f"MCP server 不存在: {server_id}")
        return self._row_to_detail(row)

    def _row_to_detail(self, row) -> dict:
        """ORM 行 → 详情 dict。"""
        config = McpServerConfigPublic.from_row(row)

        # 运行时状态补充
        is_running = self._process_manager.is_server_running(row.server_id)
        runtime_status = "running" if is_running else row.last_known_status

        # 凭证存在性
        env_presence = self._compute_env_presence(config)
        header_presence = self._compute_header_presence(config)

        return {
            "serverId": row.server_id,
            "name": row.name,
            "transport": row.transport,
            "command": row.command,
            "args": config.args,
            "url": row.url,
            "envKeys": list(set(config.non_secret_env.keys()) | set(config.secret_env_keys)),
            "envMissingKeys": self._get_missing_env_keys(config),
            "envPresence": env_presence,
            "headerKeys": list(set(config.non_secret_headers.keys()) | set(config.secret_header_keys)),
            "headerMissingKeys": [],
            "headerPresence": header_presence,
            "enabled": row.enabled,
            "status": runtime_status,
            "toolCount": row.tool_count,
            "presetSlug": row.preset_slug,
            "lastError": row.last_error_message,
            "suggestion": row.suggestion,
            "circuitBreakerOpen": row.circuit_breaker_open,
            "createdAt": row.created_at.isoformat() if row.created_at else None,
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
        }

    def _compute_env_presence(self, config: McpServerConfigPublic) -> dict[str, str]:
        """计算 env 键的存在性状态。"""
        presence = {}
        all_keys = set(config.non_secret_env.keys()) | set(config.secret_env_keys)
        for key in all_keys:
            if key in config.secret_env_keys:
                # 检查 UnifiedConfigManager 是否有值
                uc_key = f"mcp.servers.{config.server_id}.env.{key}"
                val = get_unified_config().get(uc_key)
                presence[key] = "masked" if val is not None else "placeholder"
            else:
                val = config.non_secret_env.get(key, "")
                if val.startswith("${"):
                    presence[key] = "placeholder"
                else:
                    presence[key] = "set"
        return presence

    def _compute_header_presence(self, config: McpServerConfigPublic) -> dict[str, str]:
        """计算 header 键的存在性状态。"""
        presence = {}
        all_keys = set(config.non_secret_headers.keys()) | set(config.secret_header_keys)
        for key in all_keys:
            if key in config.secret_header_keys:
                uc_key = f"mcp.servers.{config.server_id}.headers.{key}"
                val = get_unified_config().get(uc_key)
                presence[key] = "masked" if val is not None else "placeholder"
            else:
                presence[key] = "set"
        return presence

    def _get_missing_env_keys(self, config: McpServerConfigPublic) -> list[str]:
        """获取"待补"的 env 键名列表。"""
        missing = []
        for key in config.secret_env_keys:
            uc_key = f"mcp.servers.{config.server_id}.env.{key}"
            if get_unified_config().get(uc_key) is None:
                missing.append(key)
        return missing

    def _save_secrets(
        self,
        server_id: str,
        secret_env: dict[str, str],
        secret_headers: dict[str, str],
    ) -> None:
        """存储 secret 值到 UnifiedConfigManager。"""
        config = get_unified_config()
        for key, value in secret_env.items():
            config.set(f"mcp.servers.{server_id}.env.{key}", value)
        for key, value in secret_headers.items():
            config.set(f"mcp.servers.{server_id}.headers.{key}", value)

    def _cleanup_secrets(self, server_id: str) -> None:
        """删除 server 的所有 app_settings 凭证条目。"""
        config = get_unified_config()
        config.delete_by_prefix(f"mcp.servers.{server_id}.")

    @staticmethod
    def _slugify(name: str) -> str:
        """规范化 server name 为 slug（压缩连续 _，禁止 __）。

        __ 会导致 mcp__<slug>__<tool> 命名消歧失败。
        """
        slug = name.lower()
        slug = re.sub(r"[^a-z0-9_]", "_", slug)
        slug = re.sub(r"_+", "_", slug)  # 压缩连续 _
        slug = slug.strip("_")
        return slug


def _mcp_error_json(
    tool_name: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    next_action: str | None = None,
) -> str:
    """构建 MCP 错误的统一 envelope（CC-005）。"""
    from src.business.agents.tools.builtin_contracts import error_json

    return error_json(
        tool_name,
        code=code,
        message=message,
        retryable=retryable,
        next_action=next_action,
        payload={"source": "mcp"},
    )


def _is_likely_write_operation(tool_name: str, args: dict) -> bool:
    """启发式判断写操作（R5/FR-015）。

    这是有意技术债务（FR-015），存在误报和漏报，不属于硬保证。
    误报只增加确认步骤不影响安全，漏报由用户在对话中自行判断。
    后续利用 MCP Tool annotations 减少对启发式的依赖。

    权威关键词集合（contracts 唯一来源）：
    误报样本：get_user_created_repos（含 'create'）
    漏报样本：star_repository / follow_user / move_file（不含任何关键词但是写操作）
    """
    write_keywords = {
        "create", "delete", "update", "write", "push", "merge",
        "remove", "add", "close", "deploy", "execute", "fork",
    }
    name_lower = tool_name.lower()
    return any(kw in name_lower for kw in write_keywords)

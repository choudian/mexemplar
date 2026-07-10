"""
MCP 环境变量解析器 — ${VAR} 占位符解析 + 系统 env 回退 + UnifiedConfigManager 合并。
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# ${VAR} 占位符正则
_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")

# 特殊值标记"待补"（env_json 中的占位符值）
_PLACEHOLDER_VALUE_PREFIX = "__placeholder__"


def resolve_env_vars(
    env: dict[str, str],
    *,
    secret_keys: set[str] | None = None,
    secrets_from_config: dict[str, str] | None = None,
) -> tuple[dict[str, str], list[str], list[str]]:
    """解析 ${VAR} 占位符，合并 secret 值。

    Args:
        env: 原始 env dict（可能含 ${VAR} 占位符）
        secret_keys: secret 键名集合
        secrets_from_config: 从 UnifiedConfigManager 读取的 secret 值

    Returns:
        (resolved_env, missing_keys, pending_keys)
        - resolved_env: 解析后的完整 env dict
        - missing_keys: 无法解析的 ${VAR} 键名列表
        - pending_keys: 仍为占位符（__placeholder__）的键名列表
    """
    secret_keys = secret_keys or set()
    secrets_from_config = secrets_from_config or {}

    resolved: dict[str, str] = {}
    missing: list[str] = []
    pending: list[str] = []

    for key, value in env.items():
        # 1. 先检查是否是 __placeholder__ 标记
        if isinstance(value, str) and value.startswith(_PLACEHOLDER_VALUE_PREFIX):
            # 提取变量名：{"__placeholder__": "VAR"} 格式由 JSON import 产生
            # 但这里 value 是字符串，说明是从 DB 读出的格式
            pending.append(key)
            continue

        # 2. 如果是 secret 键，优先从 config 中取值
        if key in secret_keys:
            secret_val = secrets_from_config.get(key)
            if secret_val:
                resolved[key] = secret_val
            else:
                pending.append(key)
            continue

        # 3. 解析 ${VAR} 占位符
        if isinstance(value, str) and _PLACEHOLDER_RE.search(value):
            resolved_value, var_missing = _resolve_placeholders(value)
            if var_missing:
                missing.extend(var_missing)
                pending.append(key)
            else:
                resolved[key] = resolved_value
        else:
            resolved[key] = value

    return resolved, missing, pending


def _resolve_placeholders(value: str) -> tuple[str, list[str]]:
    """解析字符串中的 ${VAR} 占位符。

    Returns:
        (resolved_value, missing_var_names)
    """
    missing: list[str] = []

    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is not None:
            return env_val
        missing.append(var_name)
        return match.group(0)  # 保留原占位符

    resolved = _PLACEHOLDER_RE.sub(_replace, value)
    return resolved, missing


def check_missing_placeholders(env: dict[str, str]) -> list[str]:
    """检查 env dict 中是否有未解析的 ${VAR} 占位符或 __placeholder__ 标记。

    Returns:
        未解析的键名列表（用于保存时拦截，422 返回）
    """
    missing: list[str] = []

    for key, value in env.items():
        if isinstance(value, str):
            if value.startswith(_PLACEHOLDER_VALUE_PREFIX):
                missing.append(key)
            elif _PLACEHOLDER_RE.search(value):
                # 检查系统环境变量是否存在
                for match in _PLACEHOLDER_RE.finditer(value):
                    var_name = match.group(1)
                    if var_name not in os.environ:
                        missing.append(key)
                        break

    return missing


def merge_with_config_secrets(
    non_secret_env: dict[str, str],
    secret_env_keys: list[str],
    server_id: str,
) -> dict[str, str]:
    """从 UnifiedConfigManager 读取 secret 值，与非 secret env 合并。

    Args:
        non_secret_env: 非 secret env dict
        secret_env_keys: secret 键名列表
        server_id: server ID（用于构造 config key）

    Returns:
        合并后的完整 env dict
    """
    from src.data.unified_config import get_unified_config

    config = get_unified_config()
    merged = dict(non_secret_env)

    for key in secret_env_keys:
        config_key = f"mcp.servers.{server_id}.env.{key}"
        value = config.get(config_key)
        if value is not None:
            merged[key] = value

    return merged


def merge_with_config_headers(
    non_secret_headers: dict[str, str],
    secret_header_keys: list[str],
    server_id: str,
) -> dict[str, str]:
    """从 UnifiedConfigManager 读取 secret header 值，与非 secret headers 合并。

    Args:
        non_secret_headers: 非 secret header dict
        secret_header_keys: secret 键名列表
        server_id: server ID（用于构造 config key）

    Returns:
        合并后的完整 headers dict
    """
    from src.data.unified_config import get_unified_config

    config = get_unified_config()
    merged = dict(non_secret_headers)

    for key in secret_header_keys:
        config_key = f"mcp.servers.{server_id}.headers.{key}"
        value = config.get(config_key)
        if value is not None:
            merged[key] = value

    return merged

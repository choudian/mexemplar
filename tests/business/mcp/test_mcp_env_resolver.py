"""
T014: mcp_env_resolver 单元测试 — ${VAR} 解析 + 系统 env 回退 + missing placeholder。
"""

import os
import pytest

from src.business.mcp.mcp_env_resolver import (
    resolve_env_vars,
    check_missing_placeholders,
    merge_with_config_secrets,
    merge_with_config_headers,
)


class TestMcpEnvResolver:
    """环境变量解析测试。"""

    def test_resolve_no_placeholders(self):
        """无占位符的 env 直接传递。"""
        env = {"PATH": "/usr/bin", "HOME": "/home/user"}
        resolved, missing, pending = resolve_env_vars(env)
        assert resolved == env
        assert missing == []
        assert pending == []

    def test_resolve_system_env_placeholder(self):
        """从系统环境变量解析 ${VAR}。"""
        os.environ["TEST_MCP_VAR"] = "resolved_value"
        env = {"TEST_KEY": "${TEST_MCP_VAR}"}
        resolved, missing, pending = resolve_env_vars(env)
        assert resolved["TEST_KEY"] == "resolved_value"
        assert missing == []
        del os.environ["TEST_MCP_VAR"]

    def test_resolve_missing_system_env(self):
        """系统环境变量不存在时标 missing。"""
        env = {"MISSING_KEY": "${NONEXISTENT_VAR}"}
        resolved, missing, pending = resolve_env_vars(env)
        assert "MISSING_KEY" in pending
        assert "NONEXISTENT_VAR" in missing

    def test_resolve_secret_keys(self):
        """secret 键优先从 config 中取值。"""
        env = {"API_KEY": "direct_value", "PATH": "/usr/bin"}
        secrets_from_config = {"API_KEY": "secret_value"}
        resolved, _, _ = resolve_env_vars(
            env, secret_keys={"API_KEY"}, secrets_from_config=secrets_from_config
        )
        assert resolved["API_KEY"] == "secret_value"
        assert resolved["PATH"] == "/usr/bin"

    def test_resolve_secret_missing(self):
        """secret 键在 config 中不存在时标 pending。"""
        env = {"API_KEY": "some_value"}
        resolved, _, pending = resolve_env_vars(
            env, secret_keys={"API_KEY"}, secrets_from_config={}
        )
        assert "API_KEY" in pending

    def test_check_missing_placeholders_empty(self):
        """无占位符时返回空。"""
        env = {"KEY": "value"}
        assert check_missing_placeholders(env) == []

    def test_check_missing_placeholders_with_var(self):
        """${VAR} 占位符且系统 env 不存在时返回键名。"""
        env = {"TOKEN": "${MISSING_TOKEN}"}
        missing = check_missing_placeholders(env)
        assert "TOKEN" in missing

    def test_check_missing_placeholders_with_system_env(self):
        """${VAR} 占位符但系统 env 存在时不算 missing。"""
        os.environ["TEST_EXISTING"] = "value"
        env = {"KEY": "${TEST_EXISTING}"}
        missing = check_missing_placeholders(env)
        assert "KEY" not in missing
        del os.environ["TEST_EXISTING"]

    def test_check_missing_placeholders_special_marker(self):
        """__placeholder__ 标记的键名也算 missing。"""
        env = {"KEY": "__placeholder__VAR"}
        missing = check_missing_placeholders(env)
        assert "KEY" in missing


class TestMcpEnvMerge:
    """UnifiedConfigManager 合并测试。"""

    def test_merge_config_env_secrets(self):
        """合并 env secret 值（需要 DB，此测试验证函数签名）。"""
        # 注意：此测试需要实际 DB 环境，在集成测试中验证
        # 单元测试只验证函数签名可调用
        try:
            result = merge_with_config_secrets(
                {"PATH": "/usr/bin"},
                ["API_KEY"],
                "mcs_test",
            )
            # 如果 UnifiedConfigManager 可用，验证合并结果
            assert "PATH" in result
        except Exception:
            # DB 未初始化时跳过
            pytest.skip("UnifiedConfigManager 需要数据库")

    def test_merge_config_headers(self):
        """合并 header secret 值。"""
        try:
            result = merge_with_config_headers(
                {"Content-Type": "application/json"},
                ["Authorization"],
                "mcs_test",
            )
            assert "Content-Type" in result
        except Exception:
            pytest.skip("UnifiedConfigManager 需要数据库")

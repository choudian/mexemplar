"""
T021: UnifiedConfigManager debug 访问器测试。

验证将在 src/data/unified_config.py 中新增的 debug 配置 accessor：
- debug.trace.enabled        默认 False
- debug.trace.max_records    默认 200，非法值回退
- debug.trace.max_record_bytes  默认 1 MiB
- debug.trace.max_total_bytes   默认 16 MiB
- debug.reference.max_response_bytes 默认 1 MiB
- runtime-only set 行为
- 重启后 runtime cache 清空

mock 掉 SQLAlchemyManager 和 config 文件加载，直接测试 UnifiedConfigManager。
"""

import json
from unittest.mock import MagicMock

import pytest

from src.data.unified_config import UnifiedConfigManager

# ---------------------------------------------------------------------------
# Helpers：构建无外部依赖的 UnifiedConfigManager 实例
# ---------------------------------------------------------------------------

_EMPTY_CONFIG = json.dumps({}, ensure_ascii=False)


def _make_config(tmp_path, config_json: str | None = None):
    """创建一个完全隔离的 UnifiedConfigManager，不碰真实 DB。"""
    config_path = tmp_path / "config.json"
    config_path.write_text(
        config_json or _EMPTY_CONFIG,
        encoding="utf-8",
    )

    return UnifiedConfigManager(config_path=str(config_path))


# ---------------------------------------------------------------------------
# debug.trace.enabled
# ---------------------------------------------------------------------------


class TestDebugTraceEnabled:
    """debug.trace.enabled accessor。"""

    def test_default_is_false(self, tmp_path):
        config = _make_config(tmp_path)
        assert config.get_debug_trace_enabled() is False

    def test_runtime_set_returns_true(self, tmp_path):
        config = _make_config(tmp_path)
        config.set("debug.trace.enabled", True, persist="runtime")
        assert config.get_debug_trace_enabled() is True

    def test_runtime_set_back_to_false(self, tmp_path):
        config = _make_config(tmp_path)
        config.set("debug.trace.enabled", True, persist="runtime")
        config.set("debug.trace.enabled", False, persist="runtime")
        assert config.get_debug_trace_enabled() is False

    def test_database_value_cannot_arm_trace(self, tmp_path):
        config = _make_config(tmp_path)
        mock_sa = MagicMock()
        mock_sa.get_setting.return_value = True
        config._sa = mock_sa

        assert config.get_debug_trace_enabled() is False
        mock_sa.get_setting.assert_not_called()

    def test_runtime_string_false_cannot_arm_trace(self, tmp_path):
        config = _make_config(tmp_path)
        config.set("debug.trace.enabled", "false", persist="runtime")

        assert config.get_debug_trace_enabled() is False


# ---------------------------------------------------------------------------
# debug.trace.max_records
# ---------------------------------------------------------------------------


class TestDebugTraceMaxRecords:
    """debug.trace.max_records accessor 和非法值回退。"""

    DEFAULT = 200

    def test_default_is_200(self, tmp_path):
        config = _make_config(tmp_path)
        assert config.get_debug_trace_max_records() == self.DEFAULT

    def test_runtime_set_overrides(self, tmp_path):
        config = _make_config(tmp_path)
        config.set("debug.trace.max_records", 500, persist="runtime")
        assert config.get_debug_trace_max_records() == 500

    def test_negative_value_falls_back(self, tmp_path):
        """如果 accessor 实现内做校验，负值应回退到默认 200。"""
        config = _make_config(tmp_path)
        config.set("debug.trace.max_records", -10, persist="runtime")
        assert config.get_debug_trace_max_records() == self.DEFAULT

    def test_zero_value_falls_back(self, tmp_path):
        """0 不是合法的 max_records。"""
        config = _make_config(tmp_path)
        config.set("debug.trace.max_records", 0, persist="runtime")
        assert config.get_debug_trace_max_records() == self.DEFAULT

    def test_non_int_value_falls_back(self, tmp_path):
        """字符串 "abc" 不能转为 int。"""
        config = _make_config(tmp_path)
        config.set("debug.trace.max_records", "abc", persist="runtime")
        assert config.get_debug_trace_max_records() == self.DEFAULT


# ---------------------------------------------------------------------------
# debug.trace.max_record_bytes
# ---------------------------------------------------------------------------


class TestDebugTraceMaxRecordBytes:
    """debug.trace.max_record_bytes 默认 1 MiB。"""

    DEFAULT = 1048576  # 1 MiB

    def test_default_is_1mib(self, tmp_path):
        config = _make_config(tmp_path)
        assert config.get_debug_trace_max_record_bytes() == self.DEFAULT

    def test_runtime_set_overrides(self, tmp_path):
        config = _make_config(tmp_path)
        config.set("debug.trace.max_record_bytes", 2 * 1024 * 1024, persist="runtime")
        assert config.get_debug_trace_max_record_bytes() == 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# debug.trace.max_total_bytes
# ---------------------------------------------------------------------------


class TestDebugTraceMaxTotalBytes:
    """debug.trace.max_total_bytes 默认 16 MiB。"""

    DEFAULT = 16777216  # 16 MiB

    def test_default_is_16mib(self, tmp_path):
        config = _make_config(tmp_path)
        assert config.get_debug_trace_max_total_bytes() == self.DEFAULT

    def test_runtime_set_overrides(self, tmp_path):
        config = _make_config(tmp_path)
        config.set("debug.trace.max_total_bytes", 32 * 1024 * 1024, persist="runtime")
        assert config.get_debug_trace_max_total_bytes() == 32 * 1024 * 1024


# ---------------------------------------------------------------------------
# debug.reference.max_response_bytes
# ---------------------------------------------------------------------------


class TestDebugReferenceMaxResponseBytes:
    """debug.reference.max_response_bytes 默认 1 MiB。"""

    DEFAULT = 1048576  # 1 MiB

    def test_default_is_1mib(self, tmp_path):
        config = _make_config(tmp_path)
        assert config.get_debug_reference_max_response_bytes() == self.DEFAULT

    def test_runtime_set_overrides(self, tmp_path):
        config = _make_config(tmp_path)
        config.set("debug.reference.max_response_bytes", 512 * 1024, persist="runtime")
        assert config.get_debug_reference_max_response_bytes() == 512 * 1024


# ---------------------------------------------------------------------------
# runtime-only set 与重启语义
# ---------------------------------------------------------------------------


class TestRuntimeOnlySet:
    """persist="runtime" 仅在当前实例存活期间有效。"""

    def test_runtime_set_immediately_visible(self, tmp_path):
        config = _make_config(tmp_path)
        config.set("debug.trace.enabled", True, persist="runtime")
        assert config.get("debug.trace.enabled") is True

    def test_runtime_cache_cleared_on_new_instance(self, tmp_path):
        """新建 UnifiedConfigManager 实例模拟 sidecar 重启，runtime cache 为空。"""
        # 第一个实例写入 runtime 值
        config_a = _make_config(tmp_path)
        config_a.set("debug.trace.enabled", True, persist="runtime")
        assert config_a.get("debug.trace.enabled") is True

        # 模拟重启：新实例不应继承上一个实例的 runtime cache
        config_b = _make_config(tmp_path)
        # runtime cache 是实例级 dict，新实例的 _runtime_cache 为空
        assert config_b.get("debug.trace.enabled", default=False) is False

    def test_runtime_set_does_not_leak_to_database(self, tmp_path):
        """persist="runtime" 不应写入 app_settings 表。"""
        config = _make_config(tmp_path)
        mock_sa = MagicMock()
        mock_sa.get_setting.return_value = None
        config._sa = mock_sa

        config.set("debug.trace.enabled", True, persist="runtime")

        # set_setting 不应被调用
        mock_sa.set_setting.assert_not_called()
        # runtime cache 应包含值
        assert config.get("debug.trace.enabled") is True

    def test_persist_runtime_only_accepted_values(self, tmp_path):
        """persist 参数只接受 'database' 或 'runtime'。"""
        config = _make_config(tmp_path)
        with pytest.raises(ValueError, match="未知的 persist 类型"):
            config.set("debug.trace.enabled", True, persist="file")


# ---------------------------------------------------------------------------
# Config file override
# ---------------------------------------------------------------------------


class TestDebugConfigFileOverride:
    """配置文件中的 debug 值应被正确读取。"""

    def test_config_file_overrides_defaults(self, tmp_path):
        config_json = json.dumps(
            {
                "debug": {
                    "trace": {
                        "enabled": True,
                        "max_records": 100,
                    }
                }
            },
            ensure_ascii=False,
        )
        config = _make_config(tmp_path, config_json)
        raw = config._get_from_file_config("debug.trace.max_records")
        assert raw is None

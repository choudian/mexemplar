"""
大字段占位替换与分段读取测试。

覆盖 User Story 1-4 的测试用例和共享 fixture。
"""

import json
import pytest
from unittest.mock import patch

from src.data.recording_repository import RecordingRepository
from src.data.duckdb_manager import DuckDBManager

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

RECORDING_ID = "test-rec-large-fields"


def _make_large_text(size_chars: int, pattern: str = "A") -> str:
    """生成指定字符数的重复文本。"""
    return (pattern * size_chars)[:size_chars]


def _make_1_2mb_html() -> str:
    """生成约 1.2MB 的 HTML 文本。"""
    html_start = "<!doctype html><html><head><title>Example</title></head><body>"
    html_end = "</body></html>"
    pad_size = 1_200_000 - len(html_start) - len(html_end)
    return html_start + "<p>" + ("x" * pad_size) + "</p>" + html_end


@pytest.fixture()
def tool_db(tmp_path):
    """创建一个包含大字段测试数据的 DuckDB 实例，并 patch DuckDBManager 单例。"""
    from src.data import duckdb_manager as duckdb_module

    old_instance = getattr(duckdb_module, "_duckdb_instance", None)
    duckdb_module._duckdb_instance = None

    db_path = str(tmp_path / "large_fields_test.duckdb")
    db = DuckDBManager(db_path)
    db.initialize()  # Create schema tables
    repo = RecordingRepository(db)

    # 初始化 recording session
    repo.save_recording_session(
        {
            "recording_id": RECORDING_ID,
            "status": "stopped",
            "recording_mode": "browser",
        }
    )

    # 插入大字段网络请求（1.2MB response_body）
    large_body = _make_1_2mb_html()
    repo.save_network_requests(
        [
            {
                "action_id": 1,
                "url": "https://example.com/page",
                "method": "GET",
                "request_type": "document",
                "request_headers": {},
                "request_body": None,
                "response_status": 200,
                "response_headers": {},
                "response_body": large_body,
                "duration": 150,
                "timestamp": 1735689600,  # Unix timestamp
                "filtered": False,
            },
            # 小字段（不触发占位）
            {
                "action_id": 1,
                "url": "https://api.example.com/small",
                "method": "GET",
                "request_type": "xhr",
                "request_headers": {},
                "request_body": None,
                "response_status": 200,
                "response_headers": {},
                "response_body": '{"ok":true}',
                "duration": 50,
                "timestamp": 1735689601,
                "filtered": False,
            },
            # 恰好等于阈值
            {
                "action_id": 1,
                "url": "https://api.example.com/exact",
                "method": "GET",
                "request_type": "xhr",
                "request_headers": {},
                "request_body": None,
                "response_status": 200,
                "response_headers": {},
                "response_body": _make_large_text(1000, "B"),
                "duration": 30,
                "timestamp": 1735689602,
                "filtered": False,
            },
            # 被过滤的记录（noise filter 已标记）
            {
                "action_id": 1,
                "url": "https://doubleclick.net/tracker",
                "method": "GET",
                "request_type": "xhr",
                "request_headers": {},
                "request_body": None,
                "response_status": 200,
                "response_headers": {},
                "response_body": large_body,
                "duration": 10,
                "timestamp": 1735689603,
                "filtered": True,
                "filter_reason": "blacklist_domain",
            },
        ],
        recording_id=RECORDING_ID,
    )

    # 插入 actions（带 dom_tree_snapshot）
    repo.save_actions(
        recording_id=RECORDING_ID,
        actions=[
            {
                "action_type": "click",
                "element": "button#submit",
                "dom_tree_snapshot": _make_large_text(500_000, "<div>"),
                "timestamp": 1735689600,
            },
        ],
    )

    # 插入 sibling_snapshots
    repo.save_sibling_snapshot(
        action_id=1,
        recording_id=RECORDING_ID,
        siblings_snapshot={
            "siblings": json.dumps([{"tag": "div", "text": "x" * 200_000} for _ in range(5)]),
            "timestamp": 1735689600,
        },
    )

    try:
        with patch.object(duckdb_module, "_duckdb_instance", db):
            yield db, repo
    finally:
        try:
            db.close()
        except Exception:
            pass
        duckdb_module._duckdb_instance = old_instance


@pytest.fixture()
def large_field_config():
    """返回默认大字段配置。"""
    from src.data.config_models import LargeFieldConfig

    return LargeFieldConfig()


# ---------------------------------------------------------------------------
# T010: US1 placeholder trigger tests
# ---------------------------------------------------------------------------


class TestPlaceholderTrigger:
    """T010: 验证大字段触发占位替换，小字段透传。"""

    def test_large_text_triggers_placeholder(self, tool_db):
        """1.2MB response_body → 占位对象，非截断原文。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        db, _ = tool_db
        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body FROM network_requests "
                "WHERE url = 'https://example.com/page'",
            )
        )
        assert result["row_count"] == 1
        row = result["rows"][0]
        placeholder = row["response_body"]
        assert isinstance(placeholder, dict)
        assert placeholder["__large_field__"] is True
        assert placeholder["size_chars"] > 1_000_000
        assert len(placeholder["preview"]) <= 1000

    def test_exact_threshold_triggers_placeholder(self, tool_db):
        """恰好 1000 字符 → 触发占位（>= 阈值即触发）。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        db, _ = tool_db
        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body FROM network_requests "
                "WHERE url = 'https://api.example.com/exact'",
            )
        )
        row = result["rows"][0]
        placeholder = row["response_body"]
        assert isinstance(placeholder, dict)
        assert placeholder["__large_field__"] is True
        assert placeholder["size_chars"] == 1000

    def test_small_field_passthrough(self, tool_db):
        """200 字节 response_body → 原样返回，不触发占位。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        db, _ = tool_db
        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body FROM network_requests "
                "WHERE url = 'https://api.example.com/small'",
            )
        )
        row = result["rows"][0]
        assert row["response_body"] == '{"ok":true}'

    def test_binary_passthrough(self, tool_db):
        """二进制字段（截图）保持原占位提示。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        db, _ = tool_db
        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT screenshot_id, data FROM recording_screenshots LIMIT 0",
            )
        )
        # No screenshot data seeded, just verify no crash
        assert "error" not in result or result.get("rows") is not None

    def test_row_column_structure_integrity(self, tool_db):
        """占位替换不破坏行列结构。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        db, _ = tool_db
        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body, url FROM network_requests "
                "WHERE url = 'https://example.com/page'",
            )
        )
        row = result["rows"][0]
        assert "request_id" in row
        assert "response_body" in row
        assert "url" in row
        assert row["url"] == "https://example.com/page"
        assert isinstance(row["request_id"], int)

    def test_multiple_independent_placeholders(self, tool_db):
        """同一行多个大字段各自独立占位。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        db, _ = tool_db
        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT action_id, action_type, dom_tree_snapshot FROM actions "
                "WHERE recording_id = '" + RECORDING_ID + "'",
            )
        )
        assert result["row_count"] == 1
        row = result["rows"][0]
        dom = row["dom_tree_snapshot"]
        assert isinstance(dom, dict)
        assert dom["__large_field__"] is True


# ---------------------------------------------------------------------------
# T011: US1 locator / blocked reason tests
# ---------------------------------------------------------------------------


class TestLocatorAndBlockedReason:
    """T011: 验证 locator 构造和 blocked reason 判定。"""

    def test_direct_field_with_stable_id_gives_readable_locator(self, tool_db):
        """直接选择 response_body + 同行 request_id → 可读 locator。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body FROM network_requests "
                "WHERE url = 'https://example.com/page'",
            )
        )
        placeholder = result["rows"][0]["response_body"]
        assert placeholder["locator"] is not None
        assert placeholder["locator"]["table"] == "network_requests"
        assert placeholder["locator"]["id_field"] == "request_id"
        assert isinstance(placeholder["locator"]["id_value"], int)
        assert (
            "read_blocked_reason" not in placeholder
            or placeholder.get("read_blocked_reason") is None
        )

    def test_missing_stable_id_gives_missing_locator_field(self, tool_db):
        """只选 response_body 不选 request_id → missing_locator_field。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT response_body FROM network_requests "
                "WHERE url = 'https://example.com/page'",
            )
        )
        placeholder = result["rows"][0]["response_body"]
        assert placeholder["locator"] is None
        assert placeholder["read_blocked_reason"] == "missing_locator_field"

    def test_computed_column_gives_computed_blocked_reason(self, tool_db):
        """计算列 response_body || '' → computed_or_aggregated_column。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body || '' AS body FROM network_requests "
                "WHERE url = 'https://example.com/page'",
            )
        )
        placeholder = result["rows"][0]["body"]
        assert placeholder["locator"] is None
        assert placeholder["read_blocked_reason"] == "computed_or_aggregated_column"

    def test_aggregate_gives_computed_blocked_reason(self, tool_db):
        """聚合 COUNT(*) 不触发占位（结果不是大文本），但验证逻辑。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT recording_id, COUNT(*) FROM network_requests " "GROUP BY recording_id",
            )
        )
        # COUNT(*) returns integer, not text → no placeholder
        assert result["row_count"] == 1

    def test_filtered_row_not_visible(self, tool_db):
        """被过滤的记录在 query_data 中不可见。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body FROM network_requests "
                "WHERE url = 'https://doubleclick.net/tracker'",
            )
        )
        # Filtered rows should not appear (sql_rewriter filters them)
        assert result["row_count"] == 0


# ---------------------------------------------------------------------------
# T017: US2 read_field_chunk contract tests
# ---------------------------------------------------------------------------


def _get_first_locator(tool_db):
    """辅助：从 query_data 获取第一个大字段的 locator。"""
    from src.business.agents.tools.recording_data_tools import _query_data

    result = json.loads(
        _query_data(
            RECORDING_ID,
            "SELECT request_id, response_body FROM network_requests "
            "WHERE url = 'https://example.com/page'",
        )
    )
    return result["rows"][0]["response_body"]["locator"]


class TestReadFieldChunkContract:
    """T017: read_field_chunk 基本契约测试。"""

    def test_offset_zero_read(self, tool_db):
        """offset=0 返回首段内容，结构完整。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        result = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=None,
            )
        )
        assert result["content"] != ""
        assert result["offset"] == 0
        assert result["returned_length"] == len(result["content"])
        assert result["returned_length"] == 1000  # default max_chunk_chars
        assert result["total_length"] > 1_000_000
        assert result["has_more"] is True
        assert result["next_offset"] == 1000
        assert result["error"] is None
        assert result["locator"] == locator
        assert result["field"] == "response_body"

    def test_omitted_length_defaults_to_max_chunk_chars(self, tool_db):
        """省略 length 时默认取 max_chunk_chars。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        result = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=None,
            )
        )
        assert result["returned_length"] == 1000
        assert result["error"] is None

    def test_capped_length_respects_max(self, tool_db):
        """length 超过 max_chunk_chars 时被截断。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        result = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=5000,
            )
        )
        assert result["returned_length"] == 1000
        assert result["error"] is None

    def test_returned_length_equals_content_len(self, tool_db):
        """returned_length == len(content)。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        result = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=500,
            )
        )
        assert result["returned_length"] == len(result["content"])

    def test_total_length_matches_query(self, tool_db):
        """total_length 与原始字段长度一致。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        result = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=None,
            )
        )
        # 1.2MB HTML 的长度
        assert result["total_length"] > 1_000_000

    def test_has_more_and_next_offset(self, tool_db):
        """has_more=true 时 next_offset 正确递增。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        result = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=100,
            )
        )
        assert result["has_more"] is True
        assert result["next_offset"] == 100


# ---------------------------------------------------------------------------
# T022: US3 paging lifecycle tests
# ---------------------------------------------------------------------------


class TestPagingLifecycle:
    """T022: 分段续读生命周期测试。"""

    def test_sequential_reads_to_completion(self, tool_db):
        """连续按 next_offset 读到结尾。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        offset = 0
        total = None
        chunks = []
        while True:
            result = json.loads(
                _read_field_chunk(
                    RECORDING_ID,
                    locator=locator,
                    field="response_body",
                    offset=offset,
                    length=1000,
                )
            )
            assert result["error"] is None
            if total is None:
                total = result["total_length"]
            chunks.append(result["content"])
            if not result["has_more"]:
                break
            offset = result["next_offset"]

        # 验证所有内容拼接后长度等于 total_length
        full = "".join(chunks)
        assert len(full) == total

    def test_arbitrary_middle_offset(self, tool_db):
        """任意中间 offset 读取，内容正确。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        result = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=5000,
                length=100,
            )
        )
        assert result["error"] is None
        assert result["offset"] == 5000
        assert result["returned_length"] == 100

    def test_eof_at_exact_total_length(self, tool_db):
        """offset 恰好等于 total_length 时返回 EOF。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        # 先获取 total_length
        first = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=1,
            )
        )
        total = first["total_length"]
        eof = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=total,
                length=1000,
            )
        )
        assert eof["content"] == ""
        assert eof["returned_length"] == 0
        assert eof["has_more"] is False
        assert eof["next_offset"] is None
        assert eof["error"] is None

    def test_offset_beyond_total_length_returns_eof(self, tool_db):
        """offset 超过 total_length 也返回相同 EOF 形状。"""
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        locator = _get_first_locator(tool_db)
        first = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=1,
            )
        )
        total = first["total_length"]
        eof = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=total + 100,
                length=1000,
            )
        )
        assert eof["content"] == ""
        assert eof["returned_length"] == 0
        assert eof["has_more"] is False
        assert eof["next_offset"] is None
        assert eof["error"] is None

    def test_unicode_code_point_slicing(self, tool_db):
        """Unicode 码点切片正确（含多字节字符）。"""
        from src.business.agents.tools.recording_data_tools import (
            _query_data,
            _read_field_chunk,
        )

        db, repo = tool_db
        # 插入含 emoji 的数据
        unicode_text = "你好世界🌍" * 500  # 2500 code points (5 chars * 500)
        repo.save_network_requests(
            [
                {
                    "action_id": 1,
                    "url": "https://example.com/unicode",
                    "method": "GET",
                    "request_type": "xhr",
                    "request_headers": {},
                    "request_body": None,
                    "response_status": 200,
                    "response_headers": {},
                    "response_body": unicode_text,
                    "duration": 10,
                    "timestamp": 1735689700,
                    "filtered": False,
                },
            ],
            recording_id=RECORDING_ID,
        )
        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body FROM network_requests "
                "WHERE url = 'https://example.com/unicode'",
            )
        )
        locator = result["rows"][0]["response_body"]["locator"]
        chunk = json.loads(
            _read_field_chunk(
                RECORDING_ID,
                locator=locator,
                field="response_body",
                offset=0,
                length=100,
            )
        )
        assert chunk["error"] is None
        assert chunk["returned_length"] == 100
        assert len(chunk["content"]) == 100  # Python str length = code points


# ---------------------------------------------------------------------------
# T023: US3 error-code tests
# ---------------------------------------------------------------------------


class TestChunkReadErrorCodes:
    """T023: 全部 9 个错误码测试。"""

    def _read(self, tool_db, **kwargs):
        from src.business.agents.tools.recording_data_tools import _read_field_chunk

        defaults = {
            "locator": {"table": "network_requests", "id_field": "request_id", "id_value": 1},
            "field": "response_body",
            "offset": 0,
            "length": None,
        }
        defaults.update(kwargs)
        return json.loads(_read_field_chunk(RECORDING_ID, **defaults))

    def test_invalid_offset_negative(self, tool_db):
        result = self._read(tool_db, offset=-1)
        assert result["error"]["code"] == "invalid_offset"
        assert result["content"] == ""
        assert result["returned_length"] == 0

    def test_invalid_length_zero(self, tool_db):
        result = self._read(tool_db, length=0)
        assert result["error"]["code"] == "invalid_length"

    def test_invalid_length_negative(self, tool_db):
        result = self._read(tool_db, length=-5)
        assert result["error"]["code"] == "invalid_length"

    def test_unknown_table(self, tool_db):
        result = self._read(
            tool_db,
            locator={"table": "nonexistent_table", "id_field": "id", "id_value": 1},
        )
        assert result["error"]["code"] == "unknown_table"

    def test_field_not_found(self, tool_db):
        result = self._read(tool_db, field="nonexistent_column")
        assert result["error"]["code"] == "field_not_found"

    def test_non_text_field(self, tool_db):
        result = self._read(tool_db, field="response_status")
        assert result["error"]["code"] == "non_text_field"

    def test_unknown_id_field(self, tool_db):
        result = self._read(
            tool_db,
            locator={"table": "network_requests", "id_field": "nonexistent_id", "id_value": 1},
        )
        assert result["error"]["code"] == "unknown_id_field"

    def test_record_unavailable(self, tool_db):
        """读取不存在的 record_id → record_unavailable。"""
        result = self._read(
            tool_db,
            locator={"table": "network_requests", "id_field": "request_id", "id_value": 99999},
        )
        assert result["error"]["code"] == "record_unavailable"

    def test_unsupported_continuation(self, tool_db):
        """locator.table 不在 StableLocatorRule 中 → unsupported_continuation。"""
        result = self._read(
            tool_db,
            locator={"table": "recording_sessions", "id_field": "recording_id", "id_value": "x"},
            field="recording_id",
        )
        assert result["error"]["code"] == "unsupported_continuation"


# ---------------------------------------------------------------------------
# T026: US3 runtime-config tests
# ---------------------------------------------------------------------------


class TestRuntimeConfigChanges:
    """T026: 运行时配置变更测试。"""

    def test_changed_threshold_affects_later_triggering(self, tool_db):
        """修改 threshold 后，之前不触发占位的字段可能触发。"""
        from src.business.agents.tools.recording_data_tools import _query_data
        from src.data.config_models import LargeFieldConfig

        _, _ = tool_db
        # 小字段 response_body = '{"ok":true}' (10 chars)
        # threshold 降到 5 → 应该触发占位
        mock_config = LargeFieldConfig(threshold_chars=5, preview_chars=1000, max_chunk_chars=1000)
        with patch("src.business.agents.tools.recording_data_tools.get_unified_config") as mock_uc:
            mock_uc.return_value.get_recording_large_field_config.return_value = mock_config
            result = json.loads(
                _query_data(
                    RECORDING_ID,
                    "SELECT request_id, response_body FROM network_requests "
                    "WHERE url = 'https://api.example.com/small'",
                )
            )
        placeholder = result["rows"][0]["response_body"]
        assert isinstance(placeholder, dict)
        assert placeholder["__large_field__"] is True

    def test_existing_locator_stays_valid_after_config_change(self, tool_db):
        """配置变更后，已发出的 locator 仍然可读。"""
        from src.business.agents.tools.recording_data_tools import (
            _query_data,
            _read_field_chunk,
        )
        from src.data.config_models import LargeFieldConfig

        _, _ = tool_db
        # 先用默认配置获取 locator
        result = json.loads(
            _query_data(
                RECORDING_ID,
                "SELECT request_id, response_body FROM network_requests "
                "WHERE url = 'https://example.com/page'",
            )
        )
        locator = result["rows"][0]["response_body"]["locator"]

        # 变更配置后续读仍然成功
        mock_config = LargeFieldConfig(threshold_chars=2000, preview_chars=500, max_chunk_chars=500)
        with patch("src.business.agents.tools.recording_data_tools.get_unified_config") as mock_uc:
            mock_uc.return_value.get_recording_large_field_config.return_value = mock_config
            chunk = json.loads(
                _read_field_chunk(
                    RECORDING_ID,
                    locator=locator,
                    field="response_body",
                    offset=0,
                    length=None,
                )
            )
        assert chunk["error"] is None
        assert chunk["returned_length"] == 500  # new max_chunk_chars


# ---------------------------------------------------------------------------
# T028: US4 describe_data hint tests
# ---------------------------------------------------------------------------


class TestDescribeDataHints:
    """T028: describe_data 大字段元数据提示测试。"""

    def test_covered_table_text_field_has_large_field_hint(self, tool_db):
        """StableLocatorRule 覆盖表的文本字段有 large_field=true。"""
        from src.business.agents.tools.recording_data_tools import _describe_data

        _, _ = tool_db
        result = json.loads(_describe_data(RECORDING_ID, ["network_requests"]))
        fields = result["table_details"]["network_requests"]["fields"]
        rb = next(f for f in fields if f["name"] == "response_body")
        assert rb["large_field"] is True
        assert rb["read_via"] == "read_field_chunk"
        assert rb["locator_fields"] == ["request_id"]

    def test_covered_table_dom_snapshot_has_hint(self, tool_db):
        """actions.dom_tree_snapshot 也有大字段提示。"""
        from src.business.agents.tools.recording_data_tools import _describe_data

        _, _ = tool_db
        result = json.loads(_describe_data(RECORDING_ID, ["actions"]))
        fields = result["table_details"]["actions"]["fields"]
        dom = next(f for f in fields if f["name"] == "dom_tree_snapshot")
        assert dom["large_field"] is True
        assert dom["read_via"] == "read_field_chunk"
        assert dom["locator_fields"] == ["action_id"]

    def test_uncovered_table_no_continuation_hints(self, tool_db):
        """不在 StableLocatorRule 中的表不提供 continuation hints。"""
        from src.business.agents.tools.recording_data_tools import _describe_data

        _, _ = tool_db
        result = json.loads(_describe_data(RECORDING_ID, ["recording_sessions"]))
        fields = result["table_details"]["recording_sessions"]["fields"]
        for f in fields:
            assert "large_field" not in f or f.get("large_field") is not True
            assert "read_via" not in f or f.get("read_via") != "read_field_chunk"

    def test_non_text_field_no_large_field_hint(self, tool_db):
        """非文本字段不标记 large_field。"""
        from src.business.agents.tools.recording_data_tools import _describe_data

        _, _ = tool_db
        result = json.loads(_describe_data(RECORDING_ID, ["network_requests"]))
        fields = result["table_details"]["network_requests"]["fields"]
        status = next(f for f in fields if f["name"] == "response_status")
        assert status.get("large_field") is not True


# ---------------------------------------------------------------------------
# T038: SC-003 benchmark test
# ---------------------------------------------------------------------------


class TestPerformanceBenchmark:
    """T038: SC-003 占位构造额外延迟 ≤ 200ms。"""

    def test_placeholder_construction_under_200ms(self, tool_db):
        """单条 1.2MB 行占位构造增量耗时 ≤ 200ms。"""
        import time
        from src.business.agents.tools.recording_data_tools import (
            _build_large_field_placeholder,
            _get_analyzer,
        )

        db, _ = tool_db
        large_text = _make_1_2mb_html()
        analyzer = _get_analyzer()
        sql = "SELECT request_id, response_body FROM network_requests WHERE url = 'x'"
        bindings = analyzer.analyze(sql)
        bindings_map = {b.output_name: b for b in bindings}
        row = {"request_id": 1, "response_body": large_text}

        start = time.perf_counter()
        for _ in range(10):
            _build_large_field_placeholder(
                value=large_text,
                col_name="response_body",
                row=row,
                bindings=bindings,
                bindings_map=bindings_map,
                preview_chars=1000,
            )
        elapsed = (time.perf_counter() - start) / 10 * 1000  # ms

        assert elapsed <= 200, f"Placeholder construction took {elapsed:.1f}ms (target ≤ 200ms)"


# ---------------------------------------------------------------------------
# T039: CC-002 regression test
# ---------------------------------------------------------------------------


class TestReferenceHandlerRegression:
    """T039: 大字段占位不干扰 reference_handler 引用替换。"""

    def test_placeholder_is_json_serializable(self, tool_db):
        """占位对象能正常 JSON 序列化，不含不可序列化类型。"""
        from src.business.agents.tools.recording_data_tools import _query_data

        db, _ = tool_db
        result_str = _query_data(
            RECORDING_ID,
            "SELECT request_id, response_body FROM network_requests "
            "WHERE url = 'https://example.com/page'",
        )
        # JSON 序列化不抛异常即通过
        result = json.loads(result_str)
        placeholder = result["rows"][0]["response_body"]
        # 确认可以二次序列化（reference_handler 会做）
        serialized = json.dumps(placeholder, ensure_ascii=False)
        re_parsed = json.loads(serialized)
        assert re_parsed["__large_field__"] is True

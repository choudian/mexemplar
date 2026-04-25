import json
from pathlib import Path
from unittest.mock import patch

import duckdb

import src.data.duckdb_manager as duckdb_module
from src.business.agents.tools import recording_data_tools
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository
from src.recording.filtering.filtered_conn import DATA_ACCESS_RESTRICTED_MESSAGE, SQL_PARSE_FAILED_MESSAGE


def _create_tool_db(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    old_auto_recover = RecordingRepository._auto_recover_done

    if old_instance is not None:
        try:
            old_instance.close()
        except Exception:
            pass

    duckdb_module._duckdb_instance = None
    RecordingRepository._auto_recover_done = True

    db = DuckDBManager(str(tmp_path / "tooling.duckdb"))
    db.initialize()
    repo = RecordingRepository(db_manager=db)
    repo.save_recording_session({"recording_id": "rec", "start_time": 1, "end_time": 2})
    action_id = repo.save_actions(
        "rec",
        [{"action_type": "click", "timestamp": 3, "parameters": {}, "url": "https://example.com"}],
    )[0]
    request_id_map = repo.save_network_requests(
        [
            {
                "action_id": action_id,
                "url": "https://visible.example/api",
                "method": "GET",
                "request_type": "xhr",
                "request_headers": {},
                "response_status": 200,
                "response_headers": {"content-type": "application/json"},
                "response_body": "visible",
                "timestamp": 4,
                "filtered": False,
                "filter_reason": None,
                "filtered_at": None,
            },
            {
                "action_id": action_id,
                "url": "https://hidden.example/api",
                "method": "GET",
                "request_type": "xhr",
                "request_headers": {},
                "response_status": 200,
                "response_headers": {"content-type": "application/json"},
                "response_body": "hidden",
                "timestamp": 5,
                "filtered": True,
                "filter_reason": {"decision": "filter", "source": "rule", "reason": "static_asset"},
                "filtered_at": 6,
            },
        ],
        recording_id="rec",
    )
    repo.save_filter_decisions(
        [
            __import__("src.recording.filtering.decision", fromlist=["FilterDecision"]).FilterDecision(
                decision="filter",
                source="rule",
                reason="static_asset",
                request_id=str(request_id_map[1]),
                action_id=action_id,
                recording_id="rec",
            )
        ]
    )
    return db, old_instance, old_auto_recover


def _restore_tool_db(db, old_instance, old_auto_recover):
    try:
        db.close()
    except Exception:
        pass
    duckdb_module._duckdb_instance = old_instance
    RecordingRepository._auto_recover_done = old_auto_recover


def test_query_data_rewrites_network_requests_and_masks_errors(tmp_path):
    db, old_instance, old_auto_recover = _create_tool_db(tmp_path)
    try:
        with patch("src.business.agents.tools.recording_data_tools.DuckDBManager", return_value=db):
            data = json.loads(recording_data_tools._query_data("rec", "SELECT * FROM network_requests"))
            assert data["row_count"] == 1
            assert data["rows"][0]["url"] == "https://visible.example/api"
            assert "filtered" not in data["rows"][0]

            comment_sql = json.loads(recording_data_tools._query_data("rec", "SELECT 1 -- harmless comment"))
            assert comment_sql["rows"][0]["1"] == 1

            semicolon_string = json.loads(
                recording_data_tools._query_data("rec", "SELECT 'foo;bar' AS s")
            )
            assert semicolon_string["rows"][0]["s"] == "foo;bar"

            hidden = json.loads(
                recording_data_tools._query_data("rec", "SELECT filtered FROM network_requests")
            )
            assert "error" in hidden
            assert "rows" not in hidden

            denied = json.loads(
                recording_data_tools._query_data("rec", "SELECT * FROM filter_decisions")
            )
            assert denied["error"] == SQL_PARSE_FAILED_MESSAGE
    finally:
        _restore_tool_db(db, old_instance, old_auto_recover)


def test_describe_data_hides_filtering_infrastructure(tmp_path):
    db, old_instance, old_auto_recover = _create_tool_db(tmp_path)
    try:
        with patch("src.business.agents.tools.recording_data_tools.DuckDBManager", return_value=db):
            overview = json.loads(recording_data_tools._describe_data("rec"))
            table_names = {table["name"] for table in overview["tables"]}
            assert "filter_decisions" not in table_names

            network_meta = next(table for table in overview["tables"] if table["name"] == "network_requests")
            assert network_meta["row_count"] == 1

            details = json.loads(recording_data_tools._describe_data("rec", ["network_requests"]))
            field_names = {field["name"] for field in details["table_details"]["network_requests"]["fields"]}
            assert {"filtered", "filter_reason", "filtered_at", "is_recommendation", "importance_level"} & field_names == set()
    finally:
        _restore_tool_db(db, old_instance, old_auto_recover)


def test_execute_code_uses_filtered_proxy_and_keeps_import_guard(tmp_path):
    db, old_instance, old_auto_recover = _create_tool_db(tmp_path)
    try:
        with patch("src.business.agents.tools.recording_data_tools.DuckDBManager", return_value=db):
            visible = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "print(conn.execute(\"SELECT * FROM network_requests\").fetchall())",
                )
            )
            assert "visible.example" in visible["output"]
            assert "hidden.example" not in visible["output"]

            conn_type = json.loads(
                recording_data_tools._execute_code("rec", "print(type(conn).__name__)")
            )
            assert conn_type["output"].strip() == "FilteredDuckDBConnection"

            cursor_visible = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "cur = conn.cursor()\n"
                    "print(cur.execute(\"SELECT * FROM network_requests\").fetchall())",
                )
            )
            assert "visible.example" in cursor_visible["output"]
            assert "hidden.example" not in cursor_visible["output"]

            relation_visible = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "print(conn.table(\"network_requests\").fetchall())",
                )
            )
            assert "visible.example" in relation_visible["output"]
            assert "hidden.example" not in relation_visible["output"]

            masked = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "try:\n"
                    "    conn.execute(\"SELECT filtered FROM network_requests\").fetchall()\n"
                    "except Exception as e:\n"
                    "    print(e)\n",
                )
            )
            assert masked["output"].strip() == SQL_PARSE_FAILED_MESSAGE

            hidden_table = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "try:\n"
                    "    conn.execute(\"SELECT * FROM filter_decisions\").fetchall()\n"
                    "except Exception as e:\n"
                    "    print(e)\n",
                )
            )
            assert hidden_table["output"].strip() == SQL_PARSE_FAILED_MESSAGE

            restricted = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "try:\n"
                    "    conn.view('network_requests')\n"
                    "except Exception as e:\n"
                    "    print(e)\n",
                )
            )
            assert restricted["output"].strip() == DATA_ACCESS_RESTRICTED_MESSAGE

            relation_restricted = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "try:\n"
                    "    conn.table('network_requests').query('nr', 'SELECT * FROM nr')\n"
                    "except Exception as e:\n"
                    "    print(e)\n",
                )
            )
            assert relation_restricted["output"].strip() == DATA_ACCESS_RESTRICTED_MESSAGE

            dataframe_restricted = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "try:\n"
                    "    conn.table('network_requests').fetchdf()\n"
                    "except Exception as e:\n"
                    "    print(e)\n",
                )
            )
            assert dataframe_restricted["output"].strip() == DATA_ACCESS_RESTRICTED_MESSAGE

            non_select = json.loads(
                recording_data_tools._execute_code(
                    "rec",
                    "for sql in [\n"
                    "    'SHOW TABLES',\n"
                    "    'CREATE TEMP VIEW v AS SELECT * FROM network_requests',\n"
                    "    'UPDATE network_requests SET filtered = FALSE',\n"
                    "]:\n"
                    "    try:\n"
                    "        conn.execute(sql).fetchall()\n"
                    "    except Exception as e:\n"
                    "        print(e)\n",
                )
            )
            assert non_select["output"].strip().splitlines() == [
                SQL_PARSE_FAILED_MESSAGE,
                SQL_PARSE_FAILED_MESSAGE,
                SQL_PARSE_FAILED_MESSAGE,
            ]

            import_error = json.loads(
                recording_data_tools._execute_code("rec", "import pandas")
            )
            assert "ImportError" in import_error["error"]
            assert "pandas" in import_error["error"]
    finally:
        _restore_tool_db(db, old_instance, old_auto_recover)


def test_gatekeepers_keep_business_layer_free_of_hidden_tables_and_sqlglot():
    assert "filter_decisions" not in recording_data_tools._COMMON_TABLES
    assert "filter_decisions" not in recording_data_tools._ALL_TABLE_NAMES
    assert "filtered" not in recording_data_tools._COMMON_TABLES["network_requests"]["fields"]

    source = Path("src/business/agents/tools/recording_data_tools.py").read_text(encoding="utf-8")
    assert "sqlglot" not in source
    for blocked in ["pandas", "polars", "pyarrow"]:
        assert blocked not in source[source.find("_ALLOWED_MODULES"):source.find("def _safe_import")]


def test_describe_data_masks_duckdb_errors_without_leaking_details(tmp_path):
    class _BrokenDB:
        def fetchone(self, *_args, **_kwargs):
            raise duckdb.BinderException("column xyz does not exist")

    with patch("src.business.agents.tools.recording_data_tools.DuckDBManager", return_value=_BrokenDB()):
        payload = json.loads(recording_data_tools._describe_data("rec"))
        assert payload["tables"]
        assert "xyz" not in json.dumps(payload, ensure_ascii=False)


# ---------------------------------------------------------------------------
# T018: read_field_chunk filtered-access tests
# ---------------------------------------------------------------------------


def test_read_field_chunk_cannot_reveal_filtered_network_request(tmp_path):
    """read_field_chunk 对 network_requests 走 filtered path，无法读取被过滤记录。"""
    db, old_instance, old_auto_recover = _create_tool_db(tmp_path)
    try:
        with patch("src.business.agents.tools.recording_data_tools.DuckDBManager", return_value=db):
            # 获取被过滤记录的 request_id（直接查 raw 表获取）
            filtered_row = db.fetchone(
                "SELECT request_id FROM network_requests WHERE url = ?",
                ("https://hidden.example/api",),
            )
            assert filtered_row is not None
            filtered_rid = filtered_row[0]

            # 尝试用被过滤的 request_id 做 chunk read → record_unavailable
            result = json.loads(
                recording_data_tools._read_field_chunk(
                    "rec",
                    locator={"table": "network_requests", "id_field": "request_id", "id_value": filtered_rid},
                    field="response_body",
                    offset=0,
                    length=None,
                )
            )
            assert result["error"] is not None
            assert result["error"]["code"] == "record_unavailable"
            assert result["content"] == ""
    finally:
        _restore_tool_db(db, old_instance, old_auto_recover)


def test_read_field_chunk_reads_visible_network_request(tmp_path):
    """read_field_chunk 可以读取未被过滤的 network_request。"""
    db, old_instance, old_auto_recover = _create_tool_db(tmp_path)
    try:
        with patch("src.business.agents.tools.recording_data_tools.DuckDBManager", return_value=db):
            visible_row = db.fetchone(
                "SELECT request_id FROM network_requests WHERE url = ? AND filtered = FALSE",
                ("https://visible.example/api",),
            )
            assert visible_row is not None
            visible_rid = visible_row[0]

            result = json.loads(
                recording_data_tools._read_field_chunk(
                    "rec",
                    locator={"table": "network_requests", "id_field": "request_id", "id_value": visible_rid},
                    field="response_body",
                    offset=0,
                    length=100,
                )
            )
            assert result["error"] is None
            assert result["content"] == "visible"
    finally:
        _restore_tool_db(db, old_instance, old_auto_recover)

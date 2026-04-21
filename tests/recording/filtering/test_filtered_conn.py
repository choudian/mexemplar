import duckdb
import pytest

from src.recording.filtering.filtered_conn import (
    DATA_ACCESS_RESTRICTED_MESSAGE,
    FilteredDuckDBConnection,
    FilteredDuckDBRelation,
    SQL_PARSE_FAILED_MESSAGE,
)


def _build_conn():
    conn = duckdb.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE network_requests (
            request_id INTEGER,
            action_id INTEGER,
            recording_id VARCHAR,
            url VARCHAR,
            method VARCHAR,
            request_type VARCHAR,
            request_headers JSON,
            request_body VARCHAR,
            response_status INTEGER,
            response_headers JSON,
            response_body VARCHAR,
            duration DOUBLE,
            timestamp TIMESTAMP,
            filtered BOOLEAN,
            filter_reason JSON,
            filtered_at TIMESTAMP,
            is_recommendation BOOLEAN,
            importance_level VARCHAR
        )
        """
    )
    conn.execute("CREATE TABLE filter_decisions (decision_id INTEGER)")
    conn.execute(
        """
        INSERT INTO network_requests VALUES
            (1, 1, 'rec', 'https://visible.example/api', 'GET', 'xhr', '{}', NULL, 200, '{}', 'ok', 1.0, current_timestamp, FALSE, NULL, NULL, FALSE, 'unknown'),
            (2, 1, 'rec', 'https://hidden.example/api', 'GET', 'xhr', '{}', NULL, 200, '{}', 'hidden', 1.0, current_timestamp, TRUE, '{}', current_timestamp, FALSE, 'unknown')
        """
    )
    return FilteredDuckDBConnection(conn)


def test_connection_execute_hides_filtered_rows_and_columns():
    conn = _build_conn()
    rows = conn.execute("SELECT * FROM network_requests").fetchall()

    assert len(rows) == 1
    assert rows[0][3] == "https://visible.example/api"
    assert len(rows[0]) == 13


def test_connection_leaves_plain_selects_untouched():
    conn = _build_conn()
    assert conn.execute("SELECT 1").fetchall() == [(1,)]


def test_connection_execute_masks_hidden_column_errors():
    conn = _build_conn()

    with pytest.raises(RuntimeError, match=SQL_PARSE_FAILED_MESSAGE):
        conn.execute("SELECT filtered FROM network_requests").fetchall()


def test_connection_rejects_hidden_tables_and_non_select_statements():
    conn = _build_conn()

    for sql in [
        "SELECT * FROM filter_decisions",
        "SHOW TABLES",
        "PRAGMA table_info('network_requests')",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM duckdb_tables()",
        "CREATE TEMP VIEW v AS SELECT * FROM network_requests",
        "UPDATE network_requests SET filtered = FALSE",
    ]:
        with pytest.raises(RuntimeError, match=SQL_PARSE_FAILED_MESSAGE):
            conn.execute(sql).fetchall()


def test_connection_supports_sql_cursor_and_relation_paths():
    conn = _build_conn()
    table_relation = conn.table("network_requests")
    filtered_relation = table_relation.filter("method='GET'")
    from_query_relation = conn.from_query("SELECT * FROM network_requests").filter("method='GET'")

    assert conn.sql("SELECT * FROM network_requests").fetchall() == [
        (
            1,
            1,
            "rec",
            "https://visible.example/api",
            "GET",
            "xhr",
            "{}",
            None,
            200,
            "{}",
            "ok",
            1.0,
            conn.sql("SELECT * FROM network_requests").fetchall()[0][12],
        )
    ]
    assert conn.query("SELECT * FROM network_requests").fetchall()[0][3] == "https://visible.example/api"
    assert from_query_relation.fetchall()
    cur = conn.cursor()
    assert cur.execute("SELECT * FROM network_requests").fetchall()[0][3] == "https://visible.example/api"
    assert table_relation.fetchall()[0][3] == "https://visible.example/api"
    assert isinstance(filtered_relation, FilteredDuckDBRelation)
    assert isinstance(from_query_relation, FilteredDuckDBRelation)
    assert filtered_relation.fetchall()[0][3] == "https://visible.example/api"


def test_connection_executemany_behaves_like_execute():
    conn = _build_conn()
    rows = conn.executemany(
        "SELECT * FROM network_requests WHERE method = ?",
        [("GET",)],
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][3] == "https://visible.example/api"


def test_connection_denies_high_risk_api_surfaces():
    conn = _build_conn()
    relation = conn.table("network_requests")

    for callable_name in ["view", "read_csv", "read_parquet", "from_df", "from_arrow", "register"]:
        with pytest.raises(RuntimeError, match=DATA_ACCESS_RESTRICTED_MESSAGE):
            getattr(conn, callable_name)

    with pytest.raises(RuntimeError, match=DATA_ACCESS_RESTRICTED_MESSAGE):
        conn.table("filter_decisions")
    with pytest.raises(RuntimeError, match=DATA_ACCESS_RESTRICTED_MESSAGE):
        relation.query("nr", "SELECT * FROM nr")
    for method_name in ["df", "pl", "arrow", "fetchdf", "fetch_df", "to_df"]:
        with pytest.raises(RuntimeError, match=DATA_ACCESS_RESTRICTED_MESSAGE):
            getattr(relation, method_name)()

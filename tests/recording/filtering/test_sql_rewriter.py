import duckdb
import pytest

from src.recording.filtering.sql_rewriter import SqlRewriteError, rewrite


def _build_db():
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE actions (
            action_id INTEGER,
            recording_id VARCHAR,
            sequence_number INTEGER
        )
        """)
    conn.execute("""
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
        """)
    conn.execute("""
        INSERT INTO actions VALUES
            (1, 'rec', 1),
            (2, 'rec', 2)
        """)
    conn.execute("""
        INSERT INTO network_requests VALUES
            (1, 1, 'rec', 'https://visible.example/api', 'GET', 'xhr', '{}', NULL, 200, '{}', 'ok', 1.0, current_timestamp, FALSE, NULL, NULL, FALSE, 'unknown'),
            (2, 2, 'rec', 'https://hidden.example/api', 'GET', 'xhr', '{}', NULL, 200, '{}', 'hidden', 1.0, current_timestamp, TRUE, '{}', current_timestamp, FALSE, 'unknown')
        """)
    return conn


def test_rewrite_select_star_hides_filtered_rows_and_columns():
    conn = _build_db()
    rewritten = rewrite("SELECT * FROM network_requests ORDER BY request_id")

    rows = conn.execute(rewritten).fetchall()
    columns = [desc[0] for desc in conn.description]

    assert rows == [
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
            rows[0][12],
        )
    ]
    assert "filtered" not in columns
    assert "filter_reason" not in columns
    assert "importance_level" not in columns


def test_rewrite_allows_hidden_column_query_but_duckdb_rejects_projected_column():
    conn = _build_db()
    rewritten = rewrite("SELECT filtered FROM network_requests")

    assert "WHERE filtered = FALSE" in rewritten
    with pytest.raises(duckdb.BinderException):
        conn.execute(rewritten).fetchall()


def test_rewrite_skips_cte_shadowing_but_rewrites_physical_reference_inside_cte():
    shadowed = rewrite("WITH network_requests AS (SELECT 1 AS x) SELECT * FROM network_requests")
    assert "WHERE filtered = FALSE" not in shadowed

    conn = _build_db()
    rewritten = rewrite("WITH decoy AS (SELECT * FROM network_requests) SELECT * FROM decoy")
    rows = conn.execute(rewritten).fetchall()
    assert len(rows) == 1
    assert rows[0][3] == "https://visible.example/api"


def test_rewrite_handles_case_variants_and_quoted_identifiers():
    for sql in [
        "SELECT * FROM NETWORK_REQUESTS",
        "SELECT * FROM Network_Requests",
        'SELECT * FROM "NETWORK_REQUESTS"',
        "SELECT * FROM main.network_requests",
        'SELECT * FROM "main"."network_requests"',
    ]:
        rewritten = rewrite(sql)
        assert "WHERE filtered = FALSE" in rewritten


def test_rewrite_handles_alias_subquery_union_and_recursive_cte():
    conn = _build_db()

    alias_rows = conn.execute(
        rewrite("SELECT nr.url FROM network_requests AS nr WHERE nr.method = 'GET'")
    ).fetchall()
    subquery_rows = conn.execute(
        rewrite("SELECT sub.url FROM (SELECT url FROM network_requests) AS sub")
    ).fetchall()
    union_sql = rewrite(
        "SELECT url FROM network_requests WHERE method = 'GET' "
        "UNION ALL SELECT url FROM network_requests WHERE response_status = 200"
    )
    union_rows = conn.execute(union_sql).fetchall()
    recursive_sql = rewrite("""
        WITH RECURSIVE seen AS (
            SELECT request_id, url FROM network_requests
            UNION ALL
            SELECT request_id, url FROM seen WHERE request_id < 0
        )
        SELECT * FROM seen
        """)
    recursive_rows = conn.execute(recursive_sql).fetchall()

    assert alias_rows == [("https://visible.example/api",)]
    assert subquery_rows == [("https://visible.example/api",)]
    assert union_sql.count("WHERE filtered = FALSE") == 2
    assert union_rows == [
        ("https://visible.example/api",),
        ("https://visible.example/api",),
    ]
    assert recursive_sql.count("WHERE filtered = FALSE") == 1
    assert recursive_rows == [(1, "https://visible.example/api")]


def test_rewrite_preserves_join_semantics_for_left_right_and_full_join():
    conn = _build_db()

    left_rows = conn.execute(rewrite("""
            SELECT actions.action_id, network_requests.url
            FROM actions LEFT JOIN network_requests
            ON actions.action_id = network_requests.action_id
            ORDER BY actions.action_id
            """)).fetchall()
    right_rows = conn.execute(rewrite("""
            SELECT actions.action_id, network_requests.url
            FROM actions RIGHT JOIN network_requests
            ON actions.action_id = network_requests.action_id
            ORDER BY actions.action_id, network_requests.url
            """)).fetchall()
    full_rows = conn.execute(rewrite("""
            SELECT actions.action_id, network_requests.url
            FROM actions FULL JOIN network_requests
            ON actions.action_id = network_requests.action_id
            ORDER BY actions.action_id, network_requests.url
            """)).fetchall()

    assert left_rows == [(1, "https://visible.example/api"), (2, None)]
    assert right_rows == [(1, "https://visible.example/api")]
    assert full_rows == [(1, "https://visible.example/api"), (2, None)]


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM filter_decisions",
        "WITH decoy AS (SELECT * FROM filter_decisions) SELECT * FROM decoy",
        "SHOW TABLES",
        "PRAGMA table_info('network_requests')",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM duckdb_tables()",
        "SELECT * FROM duckdb_functions()",
        "SELECT * FROM pragma_version()",
        "CREATE TEMP VIEW v AS SELECT * FROM network_requests",
        "UPDATE network_requests SET filtered = FALSE",
    ],
)
def test_rewrite_rejects_hidden_or_non_select_access(sql):
    with pytest.raises(SqlRewriteError):
        rewrite(sql)


def test_rewrite_allows_strings_and_comments_without_false_positive():
    assert rewrite("SELECT 'network_requests' AS name") == "SELECT 'network_requests' AS name"
    assert rewrite("SELECT 1 -- harmless comment").startswith("SELECT 1")
    block_comment_sql = rewrite("SELECT 1 /* filter_decisions should stay inert */")
    assert block_comment_sql.startswith("SELECT 1")
    assert "WHERE filtered = FALSE" not in block_comment_sql


def test_rewrite_preserves_parameter_placeholders():
    rewritten = rewrite("SELECT * FROM network_requests WHERE method = ? AND response_status = ?")
    assert rewritten.count("?") == 2
    assert rewritten.find("?") < rewritten.rfind("?")


def test_rewrite_rejects_invalid_sql():
    with pytest.raises(SqlRewriteError):
        rewrite("SELECT FROM")

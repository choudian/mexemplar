import json
import types
from pathlib import Path
from unittest.mock import patch

import pytest

import src.data.duckdb_manager as duckdb_module
from src.data.config_models import RecordingNoiseFilterConfig
from src.business.agents.tools import recording_data_tools
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_recovery import RecordingRecovery
from src.data.recording_repository import RecordingRepository
from src.recording.browser.duckdb_recording_persister import DuckDBRecordingPersister


def _config_stub(*, enabled: bool = True):
    return types.SimpleNamespace(
        get_recording_noise_filter_config=lambda: RecordingNoiseFilterConfig(enabled=enabled)
    )


def _temporary_repository(tmp_path, db_name: str):
    old_instance = duckdb_module._duckdb_instance
    old_auto_recover = RecordingRepository._auto_recover_done

    if old_instance is not None:
        try:
            old_instance.close()
        except Exception:
            pass

    duckdb_module._duckdb_instance = None
    RecordingRepository._auto_recover_done = True

    db = DuckDBManager(str(tmp_path / db_name))
    db.initialize()
    repo = RecordingRepository(db_manager=db)
    return repo, db, old_instance, old_auto_recover


def _restore_repository(db, old_instance, old_auto_recover):
    try:
        db.close()
    except Exception:
        pass

    duckdb_module._duckdb_instance = old_instance
    RecordingRepository._auto_recover_done = old_auto_recover


def _request(
    url: str,
    *,
    method: str = "GET",
    request_type: str = "xhr",
    response_status: int = 200,
    content_type: str = "application/json",
    response_body: str = "{}",
    timestamp: float = 1734508923.1,
):
    return {
        "url": url,
        "method": method,
        "request_type": request_type,
        "request_headers": {"accept": "application/json"},
        "request_body": None,
        "response_status": response_status,
        "response_headers": {"content-type": content_type},
        "response_body": response_body,
        "duration": 42,
        "timestamp": timestamp,
    }


def _write_noise_queue(actions_path: Path, recording_id: str) -> None:
    click_event = {
        "recording_id": recording_id,
        "action": {
            "action_type": "click",
            "timestamp": 1734508923.0,
            "recording_mode": "browser",
            "url": "https://www.example.co.uk/home",
            "parameters": {"x": 12, "y": 34},
            "siblings_snapshot": {
                "container_selector": ".menu",
                "item_selector": ".item",
                "list_type": "uniform",
                "siblings": [{"text": "A"}, {"text": "B"}],
                "structure_similarity": 0.95,
                "is_homogeneous": True,
                "clicked_index": 0,
                "total_count": 2,
                "timestamp": 1734508923.0,
            },
            "network_requests": [
                _request(
                    "https://api.example.co.uk/preflight",
                    method="OPTIONS",
                    response_status=204,
                    response_body='{"preflight": true}',
                    timestamp=1734508923.1,
                ),
                _request(
                    "https://www.example.co.uk/login",
                    response_status=302,
                    response_body="redirect",
                    timestamp=1734508923.2,
                ),
                _request(
                    "https://static.example.co.uk/logo.png",
                    content_type="image/png",
                    response_body="PNGDATA",
                    timestamp=1734508923.3,
                ),
                _request(
                    "https://www.googletagmanager.com/gtm.js",
                    content_type="application/javascript",
                    response_body="TRACK",
                    timestamp=1734508923.4,
                ),
                _request(
                    "https://analytics.other.net/pixel",
                    response_body="THIRD",
                    timestamp=1734508923.5,
                ),
                _request(
                    "https://api.example.co.uk/orders",
                    response_body='{"items":[1]}',
                    timestamp=1734508923.6,
                ),
            ],
        },
    }
    standalone_event = {
        "recording_id": recording_id,
        "action": {
            "action_type": "network_request",
            "timestamp": 1734508924.0,
            "recording_mode": "browser",
            "url": "https://www.example.co.uk/api/raw",
            "parameters": {
                "method": "POST",
                "request_type": "fetch",
                "request_headers": {"content-type": "application/json"},
                "request_body": '{"name":"demo"}',
                "response_status": 201,
                "response_headers": {"content-type": "application/json"},
                "response_body": '{"saved": true}',
                "duration": 85,
            },
        },
    }
    actions_path.write_text(
        json.dumps(click_event, ensure_ascii=False)
        + "\n"
        + json.dumps(standalone_event, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


def _network_rows(db: DuckDBManager, recording_id: str):
    return db.fetchall(
        """
        SELECT url, action_id, filtered, CAST(filter_reason AS VARCHAR), response_body,
               is_recommendation, importance_level
        FROM network_requests
        WHERE recording_id = ?
        ORDER BY request_id
        """,
        (recording_id,),
    )


def _decision_rows(db: DuckDBManager, recording_id: str):
    return db.fetchall(
        """
        SELECT request_id, action_id, decision, source, reason, pattern_matched
        FROM filter_decisions
        WHERE recording_id = ?
        ORDER BY decision_id
        """,
        (recording_id,),
    )


def _counts(db: DuckDBManager, recording_id: str) -> dict[str, int]:
    tables = [
        "recording_sessions",
        "actions",
        "sibling_snapshots",
        "network_requests",
        "filter_decisions",
    ]
    return {
        table: db.fetchone(
            f"SELECT count(*) FROM {table} WHERE recording_id = ?",
            (recording_id,),
        )[0]
        for table in tables
    }


def test_persister_writes_filtered_requests_and_decisions(tmp_path):
    repo, db, old_instance, old_auto_recover = _temporary_repository(
        tmp_path, "persister_noise.duckdb"
    )
    queue_path = tmp_path / "rec_noise_actions.jsonl"
    _write_noise_queue(queue_path, "rec_noise")

    try:
        persister = DuckDBRecordingPersister(repo_factory=lambda: repo)
        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            assert (
                persister.save_to_duckdb(
                    recording_id="rec_noise",
                    recording_start_time=1734508923.0,
                    action_queue_path=queue_path,
                    active_recording_mode="browser",
                    end_time=1734508925.0,
                )
                == 1
            )

        network_rows = _network_rows(db, "rec_noise")
        decision_rows = _decision_rows(db, "rec_noise")

        assert len(network_rows) == 7
        assert sum(1 for row in network_rows if row[2]) == 5
        assert {row[4] for row in decision_rows} == {
            "options_preflight",
            "redirect_3xx",
            "static_asset",
            "ad_tracking_blacklist",
            "third_party_cross_origin",
        }
        assert all(row[2] == "filter" for row in decision_rows)
        assert all(row[3] == "rule" for row in decision_rows)
        assert all(row[5] is False for row in network_rows)
        assert all(row[6] == "unknown" for row in network_rows)

        same_site_row = next(row for row in network_rows if row[0] == "https://api.example.co.uk/orders")
        assert same_site_row[2] is False
        assert same_site_row[3] is None

        static_row = next(row for row in network_rows if row[0] == "https://static.example.co.uk/logo.png")
        assert static_row[2] is True
        assert "static_asset" in static_row[3]
        assert static_row[4] == "PNGDATA"

        assert db.fetchone(
            """
            SELECT count(*)
            FROM filter_decisions fd
            JOIN network_requests nr ON fd.request_id = CAST(nr.request_id AS VARCHAR)
            WHERE fd.recording_id = ? AND nr.recording_id = ?
            """,
            ("rec_noise", "rec_noise"),
        )[0] == 5
        assert db.fetchone(
            "SELECT count(*) FROM filter_decisions WHERE recording_id = ? AND decision = 'keep'",
            ("rec_noise",),
        )[0] == 0
    finally:
        _restore_repository(db, old_instance, old_auto_recover)


def test_recovery_matches_persister_output_for_same_queue(tmp_path):
    left_path = tmp_path / "left"
    right_path = tmp_path / "right"
    left_path.mkdir()
    right_path.mkdir()

    queue_path_left = left_path / "rec_parity_actions.jsonl"
    queue_path_right = right_path / "rec_parity_actions.jsonl"
    _write_noise_queue(queue_path_left, "rec_parity")
    _write_noise_queue(queue_path_right, "rec_parity")

    repo_a, db_a, old_instance_a, old_auto_a = _temporary_repository(left_path, "persister_parity.duckdb")
    repo_b, db_b, old_instance_b, old_auto_b = _temporary_repository(right_path, "recovery_parity.duckdb")

    try:
        persister = DuckDBRecordingPersister(repo_factory=lambda: repo_a)
        recovery = RecordingRecovery(queues_dir=right_path, db_manager=db_b)

        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            persister.save_to_duckdb(
                recording_id="rec_parity",
                recording_start_time=1734508923.0,
                action_queue_path=queue_path_left,
                active_recording_mode="browser",
                end_time=1734508925.0,
            )

        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            assert recovery.recover_recording("rec_parity", queue_path_right) is True

        assert _network_rows(db_a, "rec_parity") == _network_rows(db_b, "rec_parity")
        assert _decision_rows(db_a, "rec_parity") == _decision_rows(db_b, "rec_parity")
    finally:
        _restore_repository(db_a, old_instance_a, old_auto_a)
        _restore_repository(db_b, old_instance_b, old_auto_b)


def test_enabled_false_short_circuits_filtering(tmp_path):
    repo, db, old_instance, old_auto_recover = _temporary_repository(
        tmp_path, "persister_disabled.duckdb"
    )
    queue_path = tmp_path / "rec_disabled_actions.jsonl"
    _write_noise_queue(queue_path, "rec_disabled")

    try:
        persister = DuckDBRecordingPersister(repo_factory=lambda: repo)
        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(enabled=False),
        ), patch(
            "src.recording.filtering.ingest_hook.NoiseFilterPipeline",
            side_effect=AssertionError("pipeline should not be instantiated"),
        ), patch(
            "src.recording.filtering.ingest_hook.LLMNoiseJudge",
            side_effect=AssertionError("judge should not be instantiated"),
        ):
            persister.save_to_duckdb(
                recording_id="rec_disabled",
                recording_start_time=1734508923.0,
                action_queue_path=queue_path,
                active_recording_mode="browser",
                end_time=1734508925.0,
            )

        assert db.fetchone(
            "SELECT count(*) FROM filter_decisions WHERE recording_id = ?",
            ("rec_disabled",),
        )[0] == 0
        assert db.fetchone(
            "SELECT count(*) FROM network_requests WHERE recording_id = ? AND filtered = TRUE",
            ("rec_disabled",),
        )[0] == 0
    finally:
        _restore_repository(db, old_instance, old_auto_recover)


def test_enabled_false_still_keeps_query_side_contracts(tmp_path):
    repo, db, old_instance, old_auto_recover = _temporary_repository(
        tmp_path, "persister_disabled_query.duckdb"
    )
    queue_path = tmp_path / "rec_disabled_query_actions.jsonl"
    _write_noise_queue(queue_path, "rec_disabled_query")

    try:
        persister = DuckDBRecordingPersister(repo_factory=lambda: repo)
        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(enabled=False),
        ):
            persister.save_to_duckdb(
                recording_id="rec_disabled_query",
                recording_start_time=1734508923.0,
                action_queue_path=queue_path,
                active_recording_mode="browser",
                end_time=1734508925.0,
            )

        with patch("src.business.agents.tools.recording_data_tools.DuckDBManager", return_value=db):
            overview = json.loads(recording_data_tools._describe_data("rec_disabled_query"))
            table_names = {table["name"] for table in overview["tables"]}
            assert "filter_decisions" not in table_names

            details = json.loads(
                recording_data_tools._describe_data("rec_disabled_query", ["network_requests"])
            )
            field_names = {
                field["name"]
                for field in details["table_details"]["network_requests"]["fields"]
            }
            assert {"filtered", "filter_reason", "filtered_at"} & field_names == set()

            visible_rows = json.loads(
                recording_data_tools._query_data(
                    "rec_disabled_query",
                    "SELECT * FROM network_requests ORDER BY url",
                )
            )
            assert visible_rows["row_count"] == 7
            assert "filtered" not in visible_rows["rows"][0]

            denied = json.loads(
                recording_data_tools._query_data(
                    "rec_disabled_query",
                    "SELECT * FROM filter_decisions",
                )
            )
            assert denied["error"] == "SQL 解析失败，请简化查询后重试"

            restricted = json.loads(
                recording_data_tools._execute_code(
                    "rec_disabled_query",
                    "try:\n"
                    "    conn.execute(\"SHOW TABLES\").fetchall()\n"
                    "except Exception as e:\n"
                    "    print(e)\n",
                )
            )
            assert restricted["output"].strip() == "SQL 解析失败，请简化查询后重试"
    finally:
        _restore_repository(db, old_instance, old_auto_recover)


def test_new_ingest_does_not_backfill_historical_rows(tmp_path):
    repo, db, old_instance, old_auto_recover = _temporary_repository(
        tmp_path, "history_guard.duckdb"
    )
    queue_path = tmp_path / "rec_new_actions.jsonl"
    _write_noise_queue(queue_path, "rec_new")

    try:
        repo.save_network_requests(
            [
                {
                    "action_id": None,
                    "url": "https://legacy.example.com/api",
                    "timestamp": 1734400000.0,
                    "filtered": False,
                    "filter_reason": None,
                    "filtered_at": None,
                }
            ],
            recording_id="rec_old",
        )

        persister = DuckDBRecordingPersister(repo_factory=lambda: repo)
        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            persister.save_to_duckdb(
                recording_id="rec_new",
                recording_start_time=1734508923.0,
                action_queue_path=queue_path,
                active_recording_mode="browser",
                end_time=1734508925.0,
            )

        old_row = db.fetchone(
            """
            SELECT filtered, filter_reason
            FROM network_requests
            WHERE recording_id = ?
            """,
            ("rec_old",),
        )
        assert old_row == (False, None)
        assert db.fetchone(
            "SELECT count(*) FROM filter_decisions WHERE recording_id = ?",
            ("rec_old",),
        )[0] == 0
    finally:
        _restore_repository(db, old_instance, old_auto_recover)


def test_smoke_persister_then_agent_query_only_sees_visible_requests(tmp_path):
    repo, db, old_instance, old_auto_recover = _temporary_repository(
        tmp_path, "smoke_query.duckdb"
    )
    queue_path = tmp_path / "rec_smoke_actions.jsonl"
    _write_noise_queue(queue_path, "rec_smoke")

    try:
        persister = DuckDBRecordingPersister(repo_factory=lambda: repo)
        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            persister.save_to_duckdb(
                recording_id="rec_smoke",
                recording_start_time=1734508923.0,
                action_queue_path=queue_path,
                active_recording_mode="browser",
                end_time=1734508925.0,
            )

        with patch("src.business.agents.tools.recording_data_tools.DuckDBManager", return_value=db):
            result = json.loads(
                recording_data_tools._query_data(
                    "rec_smoke",
                    "SELECT url FROM network_requests ORDER BY url",
                )
            )

        urls = [row["url"] for row in result["rows"]]
        assert "https://api.example.co.uk/orders" in urls
        assert "https://www.example.co.uk/api/raw" in urls
        assert "https://www.googletagmanager.com/gtm.js" not in urls
        assert "https://analytics.other.net/pixel" not in urls
    finally:
        _restore_repository(db, old_instance, old_auto_recover)


@pytest.mark.parametrize("method_name", ["save_network_requests", "save_filter_decisions"])
def test_persister_rolls_back_on_filter_write_failures_and_can_retry(tmp_path, method_name):
    repo, db, old_instance, old_auto_recover = _temporary_repository(
        tmp_path, f"persister_rollback_{method_name}.duckdb"
    )
    queue_path = tmp_path / f"rec_{method_name}_actions.jsonl"
    _write_noise_queue(queue_path, "rec_retry")

    try:
        persister = DuckDBRecordingPersister(repo_factory=lambda: repo)
        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            with patch.object(repo, method_name, side_effect=RuntimeError("boom")):
                with pytest.raises(RuntimeError, match="boom"):
                    persister.save_to_duckdb(
                        recording_id="rec_retry",
                        recording_start_time=1734508923.0,
                        action_queue_path=queue_path,
                        active_recording_mode="browser",
                        end_time=1734508925.0,
                    )

        assert _counts(db, "rec_retry") == {
            "recording_sessions": 0,
            "actions": 0,
            "sibling_snapshots": 0,
            "network_requests": 0,
            "filter_decisions": 0,
        }

        _write_noise_queue(queue_path, "rec_retry")
        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            persister.save_to_duckdb(
                recording_id="rec_retry",
                recording_start_time=1734508923.0,
                action_queue_path=queue_path,
                active_recording_mode="browser",
                end_time=1734508925.0,
            )

        assert _counts(db, "rec_retry")["network_requests"] == 7
        assert _counts(db, "rec_retry")["filter_decisions"] == 5
    finally:
        _restore_repository(db, old_instance, old_auto_recover)


@pytest.mark.parametrize("method_name", ["save_network_requests", "save_filter_decisions"])
def test_recovery_rolls_back_on_filter_write_failures_and_can_retry(tmp_path, method_name):
    repo, db, old_instance, old_auto_recover = _temporary_repository(
        tmp_path, f"recovery_rollback_{method_name}.duckdb"
    )
    queue_path = tmp_path / f"rec_recovery_{method_name}_actions.jsonl"
    _write_noise_queue(queue_path, "rec_recovery_retry")

    try:
        recovery = RecordingRecovery(queues_dir=tmp_path, db_manager=db)
        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            with patch.object(recovery.repository, method_name, side_effect=RuntimeError("boom")):
                assert recovery.recover_recording("rec_recovery_retry", queue_path) is False

        assert _counts(db, "rec_recovery_retry") == {
            "recording_sessions": 0,
            "actions": 0,
            "sibling_snapshots": 0,
            "network_requests": 0,
            "filter_decisions": 0,
        }

        with patch(
            "src.recording.filtering.ingest_hook.get_unified_config",
            return_value=_config_stub(),
        ):
            assert recovery.recover_recording("rec_recovery_retry", queue_path) is True

        assert _counts(db, "rec_recovery_retry")["network_requests"] == 7
        assert _counts(db, "rec_recovery_retry")["filter_decisions"] == 5
    finally:
        _restore_repository(db, old_instance, old_auto_recover)

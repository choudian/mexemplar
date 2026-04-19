import json

import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_recovery import RecordingRecovery
from src.data.recording_repository import RecordingRepository


def _build_queue_line(recording_id: str, action: dict) -> str:
    return json.dumps(
        {
            "type": "browser_action",
            "recording_id": recording_id,
            "action": action,
        },
        ensure_ascii=False,
    )


def _create_fresh_db(tmp_path, db_name: str):
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
    return db, old_instance, old_auto_recover


def _restore_db(db, old_instance, old_auto_recover):
    try:
        db.close()
    except Exception:
        pass

    duckdb_module._duckdb_instance = old_instance
    RecordingRepository._auto_recover_done = old_auto_recover


def test_recovery_saves_standalone_network_request_only_to_network_requests(tmp_path):
    queues_dir = tmp_path / "queues"
    queues_dir.mkdir()
    queue_file = queues_dir / "rec_network_only_actions.jsonl"
    queue_file.write_text(
        _build_queue_line(
            "rec_network_only",
            {
                "action_type": "network_request",
                "timestamp": 1734508923.0,
                "recording_mode": "browser",
                "url": "https://example.com/api/data",
                "parameters": {
                    "method": "GET",
                    "request_type": "xhr",
                    "response_status": 200,
                    "response_headers": {"content-type": "application/json"},
                    "response_body": '{"ok": true}',
                    "duration": 120,
                },
                "network_requests": [],
            },
        )
        + "\n",
        encoding="utf-8",
    )

    db, old_instance, old_auto_recover = _create_fresh_db(
        tmp_path, "recovery_network_only.duckdb"
    )

    try:
        recovery = RecordingRecovery(queues_dir=queues_dir, db_manager=db)

        assert recovery.recover_recording("rec_network_only", queue_file) is True
        assert db.fetchone(
            "SELECT count(*) FROM actions WHERE recording_id = ?",
            ("rec_network_only",),
        )[0] == 0
        assert db.fetchone(
            "SELECT count(*) FROM network_requests WHERE recording_id = ?",
            ("rec_network_only",),
        )[0] == 1

        action_id, response_body = db.fetchone(
            """
            SELECT action_id, response_body
            FROM network_requests
            WHERE recording_id = ?
            """,
            ("rec_network_only",),
        )
        assert action_id is None
        assert response_body == '{"ok": true}'
    finally:
        _restore_db(db, old_instance, old_auto_recover)


def test_recovery_restores_associated_requests_and_sibling_snapshots(tmp_path):
    queues_dir = tmp_path / "queues"
    queues_dir.mkdir()
    queue_file = queues_dir / "rec_mixed_actions.jsonl"
    queue_file.write_text(
        (
            _build_queue_line(
                "rec_mixed",
                {
                    "action_type": "click",
                    "timestamp": 1734508923.0,
                    "recording_mode": "browser",
                    "url": "https://example.com",
                    "parameters": {"x": 12, "y": 34},
                    "network_requests": [
                        {
                            "url": "https://example.com/api/list",
                            "method": "GET",
                            "request_type": "xhr",
                            "response_status": 200,
                            "response_body": '{"items": [1, 2]}',
                            "timestamp": 1734508923.1,
                        }
                    ],
                    "siblings_snapshot": {
                        "container_selector": ".list",
                        "item_selector": ".item",
                        "list_type": "uniform",
                        "siblings": [{"text": "A"}, {"text": "B"}],
                        "structure_similarity": 0.95,
                        "is_homogeneous": True,
                        "clicked_index": 1,
                        "total_count": 2,
                        "timestamp": 1734508923.0,
                    },
                },
            )
            + "\n"
            + _build_queue_line(
                "rec_mixed",
                {
                    "action_type": "network_request",
                    "timestamp": 1734508924.0,
                    "recording_mode": "browser",
                    "url": "https://example.com/api/raw",
                    "parameters": {
                        "method": "POST",
                        "request_type": "fetch",
                        "response_status": 201,
                        "response_body": '{"saved": true}',
                        "duration": 85,
                    },
                    "network_requests": [],
                },
            )
            + "\n"
        ),
        encoding="utf-8",
    )

    db, old_instance, old_auto_recover = _create_fresh_db(tmp_path, "recovery_mixed.duckdb")

    try:
        recovery = RecordingRecovery(queues_dir=queues_dir, db_manager=db)

        assert recovery.recover_recording("rec_mixed", queue_file) is True
        assert db.fetchone(
            "SELECT count(*) FROM actions WHERE recording_id = ?",
            ("rec_mixed",),
        )[0] == 1
        assert db.fetchone(
            """
            SELECT count(*)
            FROM actions
            WHERE recording_id = ? AND action_type = 'network_request'
            """,
            ("rec_mixed",),
        )[0] == 0
        assert db.fetchone(
            "SELECT count(*) FROM sibling_snapshots WHERE recording_id = ?",
            ("rec_mixed",),
        )[0] == 1
        assert db.fetchone(
            "SELECT count(*) FROM network_requests WHERE recording_id = ?",
            ("rec_mixed",),
        )[0] == 2
        assert db.fetchone(
            """
            SELECT count(*)
            FROM network_requests
            WHERE recording_id = ? AND action_id IS NOT NULL
            """,
            ("rec_mixed",),
        )[0] == 1
        assert db.fetchone(
            """
            SELECT count(*)
            FROM network_requests
            WHERE recording_id = ? AND action_id IS NULL
            """,
            ("rec_mixed",),
        )[0] == 1
    finally:
        _restore_db(db, old_instance, old_auto_recover)

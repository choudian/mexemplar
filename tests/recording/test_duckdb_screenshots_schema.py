import src.data.duckdb_manager as duckdb_module
from src.data.duckdb_manager import DuckDBManager


def test_recording_screenshots_table_creation_is_idempotent(tmp_path):
    old_instance = duckdb_module._duckdb_instance
    if old_instance is not None:
        try:
            old_instance.close()
        except Exception:
            pass

    duckdb_module._duckdb_instance = None

    try:
        db = DuckDBManager(str(tmp_path / "schema_test.duckdb"))
        db.initialize()
        db.initialize()

        assert db.fetchone(
            """
            SELECT count(*)
            FROM information_schema.tables
            WHERE table_name = 'recording_screenshots'
            """
        )[0] == 1
    finally:
        try:
            db.close()
        except Exception:
            pass
        duckdb_module._duckdb_instance = old_instance

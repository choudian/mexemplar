import pytest

from src.recording.filtering.sql_rewriter import SqlRewriteError, validate_table_against_mode_allowlist


def test_mode_allowlist_rejects_cross_mode_tables():
    validate_table_against_mode_allowlist("SELECT * FROM actions", "browser")
    validate_table_against_mode_allowlist(
        "SELECT * FROM desktop_recordings JOIN desktop_actions USING(recording_id)",
        "desktop",
    )

    with pytest.raises(SqlRewriteError, match="table_not_in_mode:desktop_actions:browser"):
        validate_table_against_mode_allowlist("SELECT * FROM desktop_actions", "browser")

    with pytest.raises(SqlRewriteError, match="table_not_in_mode:actions:desktop"):
        validate_table_against_mode_allowlist("SELECT * FROM actions", "desktop")

import os
from pathlib import Path

from src.data.config_models import ConfigFileLoader


def _case_dir(tmp_path: Path, case_name: str) -> Path:
    base_dir = tmp_path / case_name
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def test_sync_startup_config_prefers_config_json(tmp_path):
    case_dir = _case_dir(tmp_path, "prefers_config")
    working_dir = case_dir / "working"
    working_dir.mkdir()

    config_file = working_dir / "config.json"
    example_file = working_dir / "config.example.json"
    config_file.write_text('{"app_name": "from_config"}', encoding="utf-8")
    example_file.write_text('{"app_name": "from_example"}', encoding="utf-8")

    target = case_dir / "project" / "data" / "config" / "config.json"
    ConfigFileLoader._sync_startup_config(target, working_dir=working_dir)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == config_file.read_text(encoding="utf-8")


def test_sync_startup_config_uses_example_when_config_missing(tmp_path):
    case_dir = _case_dir(tmp_path, "fallback_example")
    working_dir = case_dir / "working"
    working_dir.mkdir()

    example_file = working_dir / "config.example.json"
    example_file.write_text('{"app_name": "from_example"}', encoding="utf-8")

    target = case_dir / "project" / "data" / "config" / "config.json"
    ConfigFileLoader._sync_startup_config(target, working_dir=working_dir)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == example_file.read_text(encoding="utf-8")


def test_sync_startup_config_overwrites_when_content_differs(tmp_path):
    case_dir = _case_dir(tmp_path, "overwrite_when_diff")
    working_dir = case_dir / "working"
    working_dir.mkdir()

    config_file = working_dir / "config.json"
    config_file.write_text('{"app_name": "new"}', encoding="utf-8")

    target = case_dir / "project" / "data" / "config" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"app_name": "old"}', encoding="utf-8")

    ConfigFileLoader._sync_startup_config(target, working_dir=working_dir)

    assert target.read_text(encoding="utf-8") == config_file.read_text(encoding="utf-8")


def test_sync_startup_config_skips_when_content_same(tmp_path):
    case_dir = _case_dir(tmp_path, "skip_when_same")
    working_dir = case_dir / "working"
    working_dir.mkdir()

    config_file = working_dir / "config.json"
    config_file.write_text('{"app_name": "same"}', encoding="utf-8")

    target = case_dir / "project" / "data" / "config" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"app_name": "same"}', encoding="utf-8")

    old_ts = 946684800  # 2000-01-01
    new_ts = 978307200  # 2001-01-01
    os.utime(target, (old_ts, old_ts))
    os.utime(config_file, (new_ts, new_ts))

    ConfigFileLoader._sync_startup_config(target, working_dir=working_dir)

    assert target.read_text(encoding="utf-8") == config_file.read_text(encoding="utf-8")
    assert int(target.stat().st_mtime) == old_ts


def test_sync_startup_config_skips_when_no_source_file(tmp_path):
    case_dir = _case_dir(tmp_path, "skip_when_no_source")
    working_dir = case_dir / "working"
    working_dir.mkdir()

    target = case_dir / "project" / "data" / "config" / "config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('{"app_name": "keep_existing"}', encoding="utf-8")

    ConfigFileLoader._sync_startup_config(target, working_dir=working_dir)

    assert target.read_text(encoding="utf-8") == '{"app_name": "keep_existing"}'


def test_default_loader_uses_runtime_data_dir(monkeypatch, tmp_path):
    data_dir = tmp_path / "runtime-data"
    working_dir = tmp_path / "working"
    working_dir.mkdir()
    (working_dir / "config.json").write_text('{"app_name": "from_runtime"}', encoding="utf-8")

    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(data_dir))
    monkeypatch.chdir(working_dir)

    loader = ConfigFileLoader()

    expected = data_dir / "config" / "config.json"
    assert loader.config_path == expected
    assert expected.read_text(encoding="utf-8") == '{"app_name": "from_runtime"}'


def test_loader_warns_about_deprecated_keys_without_logging_values(tmp_path, caplog):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"ai": {"compression_model_api_key": "old-secret"}}',
        encoding="utf-8",
    )

    ConfigFileLoader(str(config_path)).load()

    assert "ai.compression_model_api_key" in caplog.text
    assert "old-secret" not in caplog.text


def test_loader_warns_and_ignores_deprecated_recording_keys(tmp_path, caplog):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"recording": {"record_mouse_move": true, "websocket": {"enabled": false}}}',
        encoding="utf-8",
    )

    config = ConfigFileLoader(str(config_path)).load()

    assert "recording.record_mouse_move" in caplog.text
    assert "recording.websocket.enabled" in caplog.text
    assert not hasattr(config.recording, "record_mouse_move")
    assert not hasattr(config.recording.websocket, "enabled")


def test_loader_warns_about_runtime_only_and_unknown_keys_without_values(tmp_path, caplog):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"debug": {"trace": {"max_records": 17}}, "unsupported": {"value": "hidden"}}',
        encoding="utf-8",
    )

    ConfigFileLoader(str(config_path)).load()

    assert "debug.trace.max_records" in caplog.text
    assert "unsupported.value" in caplog.text
    assert "hidden" not in caplog.text

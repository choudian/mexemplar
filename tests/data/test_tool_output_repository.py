from datetime import datetime, timedelta, timezone

from src.data.repos.tool_output_repository import ToolOutputRepository
from src.data.unified_config import UnifiedConfigManager


def test_tool_output_repository_create_authorize_load_and_delete(tmp_path):
    repo = ToolOutputRepository(storage_root=tmp_path / "tool_outputs")
    model = repo.create_reference(
        session_id="session-1",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data="raw output",
        workspace_root=tmp_path,
        retention_days=1,
    )

    loaded = repo.load_authorized_bytes(
        model.reference_id,
        session_id="session-1",
        workspace_root=tmp_path,
    )
    denied = repo.load_authorized_bytes(
        model.reference_id,
        session_id="session-2",
        workspace_root=tmp_path,
    )

    assert loaded is not None
    assert loaded.data == b"raw output"
    assert denied is None
    assert repo.mark_deleted(model.reference_id) is True
    assert (
        repo.load_authorized_bytes(
            model.reference_id,
            session_id="session-1",
            workspace_root=tmp_path,
        )
        is None
    )


def test_tool_output_repository_cleanup_expired_and_orphaned_blobs(tmp_path):
    repo = ToolOutputRepository(storage_root=tmp_path / "tool_outputs")
    model = repo.create_reference(
        session_id="session-1",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data="raw output",
        workspace_root=tmp_path,
        retention_days=1,
    )
    model.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    repo.session.commit()
    orphan = repo.storage_root / "orphan" / "orphan.blob"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("orphan", encoding="utf-8")

    result = repo.cleanup_expired()

    assert result["expiredMetadata"] == 1
    assert result["removedBlobs"] == 1
    assert result["failedBlobDeletes"] == 0
    assert result["orphanedBlobs"] == 1
    assert repo.get_by_reference_id(model.reference_id).status == "expired"


def test_tool_output_repository_retries_failed_expired_blob_cleanup(tmp_path, monkeypatch):
    repo = ToolOutputRepository(storage_root=tmp_path / "tool_outputs")
    model = repo.create_reference(
        session_id="session-1",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data="raw output",
        workspace_root=tmp_path,
        retention_days=1,
    )
    blob_path = repo.blob_path(model)
    original_unlink = type(blob_path).unlink
    failed_once = False

    def flaky_unlink(path, *args, **kwargs):
        nonlocal failed_once
        if path == blob_path and not failed_once:
            failed_once = True
            raise OSError("locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(type(blob_path), "unlink", flaky_unlink)

    assert repo.mark_expired(model.reference_id) is True
    assert blob_path.exists()

    result = repo.cleanup_expired()

    assert result["removedBlobs"] == 1
    assert result["failedBlobDeletes"] == 0
    assert not blob_path.exists()


def test_agent_tools_unified_config_defaults_and_validation(tmp_path):
    config = UnifiedConfigManager(config_path=str(tmp_path / "missing.json"))

    assert config.get_agent_tools_file_default_max_lines() == 200
    assert config.get_agent_tools_file_max_window_chars() == 50000
    assert config.get_agent_tools_output_visible_char_cap() == 12000
    assert config.get_agent_tools_output_raw_reference_threshold_chars() == 20000
    assert config.get_agent_tools_output_retention_days() == 14
    assert config.get_agent_tools_search_default_page_size() == 100
    assert config.get_agent_tools_process_default_timeout_ms() == 30000

    config.set("agent_tools.file.default_max_lines", 5000, persist="runtime")
    config.set("agent_tools.output.visible_char_cap", 100000, persist="runtime")
    config.set("agent_tools.process.max_timeout_ms", 1, persist="runtime")

    assert config.get_agent_tools_file_default_max_lines() == 1000
    assert config.get_agent_tools_output_visible_char_cap() == 50000
    assert (
        config.get_agent_tools_process_max_timeout_ms()
        >= config.get_agent_tools_process_default_timeout_ms()
    )

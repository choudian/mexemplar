import json
from types import SimpleNamespace

import src.data.duckdb_manager as duckdb_module
from src.business.agents.tools import desktop_tools
from src.data.duckdb_manager import DuckDBManager
from src.data.recording_repository import RecordingRepository


def test_analyze_desktop_action_returns_structured_payload(tmp_path, monkeypatch):
    old_instance = duckdb_module._duckdb_instance
    duckdb_module._duckdb_instance = None
    db = DuckDBManager(str(tmp_path / "analyze.duckdb"))
    db.initialize()
    repo = RecordingRepository(db)
    repo.insert_desktop_recording({"recording_id": "rec-1", "start_time": 1, "monitor_index": 0})
    recording_root = tmp_path / "recordings" / "rec-1"
    frame_dir = recording_root / "frames" / "a1"
    frame_dir.mkdir(parents=True)
    clipboard_dir = recording_root / "clipboard"
    clipboard_dir.mkdir(parents=True)
    from PIL import Image

    Image.new("RGB", (20, 10), "red").save(frame_dir / "frame_001.png")
    clipboard_path = clipboard_dir / "rec-1_000001.png"
    Image.new("RGB", (10, 20), "blue").save(clipboard_path)
    repo.insert_desktop_action(
        {
            "action_id": "a1",
            "recording_id": "rec-1",
            "type": "typing",
            "monitor_index": 0,
            "text_content": "hello",
            "clipboard_text": "clip",
            "clipboard_image_path": str(clipboard_path),
            "timestamp": 2,
        }
    )
    monkeypatch.setattr(
        desktop_tools,
        "get_unified_config",
        lambda: SimpleNamespace(get_desktop_vision_model=lambda: "vision-x"),
    )
    monkeypatch.setattr(desktop_tools, "get_default_data_dir", lambda: tmp_path)
    captured = {}

    def fake_invoke(content, model):
        captured["content"] = content
        captured["model"] = model
        return "visual answer"

    monkeypatch.setattr(desktop_tools, "invoke_vision_model", fake_invoke)
    try:
        tools = {tool.name: tool for tool in desktop_tools.create_desktop_specific_tools("rec-1")}
        payload = json.loads(tools["analyze_desktop_action"].handler(["a1"], "what happened?"))

        assert payload["analysis"] == "visual answer"
        assert payload["model"] == "vision-x"
        assert payload["actions"][0]["text_content"] == "hello"
        assert payload["evidence"] == {"frames": 1, "clipboard_images": 1}
        assert captured["model"] == "vision-x"
        text_parts = [part["text"] for part in captured["content"] if part["type"] == "text"]
        assert text_parts[0].startswith("[动作 a1 元数据]")
        assert text_parts[1] == "[动作 a1 剪贴板图]"
        assert text_parts[2] == "[动作 a1 帧 001]"
        assert text_parts[-1] == "what happened?"
        assert len([part for part in captured["content"] if part["type"] == "image_url"]) == 2
        assert (
            json.loads(tools["analyze_desktop_action"].handler(["a1", "a2", "a3"], "?"))["error"]
            == "too_many_actions"
        )
    finally:
        db.close()
        duckdb_module._duckdb_instance = old_instance

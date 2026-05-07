from src.recording.desktop.clipboard_watcher import ClipboardWatcher


def test_clipboard_watcher_latest_snapshot_is_stable(tmp_path, monkeypatch):
    watcher = ClipboardWatcher("rec-1", tmp_path)
    monkeypatch.setattr(watcher, "_read_text", lambda: "copied")
    monkeypatch.setattr(watcher, "_read_image_bytes", lambda: None)

    latest = watcher.capture_snapshot()

    assert latest.text == "copied"
    assert latest.event_seq == 1
    assert watcher.latest() == latest


def test_clipboard_watcher_persists_image_snapshot(tmp_path, monkeypatch):
    watcher = ClipboardWatcher("rec-1", tmp_path)
    monkeypatch.setattr(watcher, "_read_text", lambda: None)
    monkeypatch.setattr(watcher, "_read_image_bytes", lambda: b"png-bytes")

    latest = watcher.capture_snapshot()

    assert latest.text is None
    assert latest.image_path is not None
    assert latest.image_path.name == "rec-1_000001.png"
    assert latest.image_path.read_bytes() == b"png-bytes"

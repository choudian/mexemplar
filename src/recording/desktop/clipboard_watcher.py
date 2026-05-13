from __future__ import annotations

import hashlib
import io
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_win32clipboard = None
_ImageGrab = None


def _lazy_import_clipboard_deps() -> None:
    global _win32clipboard, _ImageGrab
    if _win32clipboard is None:
        try:
            import win32clipboard as _wcb

            _win32clipboard = _wcb
        except Exception:
            pass
    if _ImageGrab is None:
        try:
            from PIL import ImageGrab as _ig

            _ImageGrab = _ig
        except Exception:
            pass


_lazy_import_clipboard_deps()


@dataclass(frozen=True)
class _ClipboardLatest:
    text: str | None = None
    image_path: Path | None = None
    event_seq: int = 0


class ClipboardWatcher:
    def __init__(self, recording_id: str, recording_root: Path):
        self.recording_id = recording_id
        self.recording_root = Path(recording_root)
        self.degraded_reason: str | None = None
        self._lock = threading.Lock()
        self._event_seq = 0
        self._latest = _ClipboardLatest()
        self._running = False
        self._poll_thread: threading.Thread | None = None
        self._poll_interval = 0.5
        self._last_signature: tuple[str, str | None, str | None] | None = None

    def start(self) -> None:
        self._running = True
        if _win32clipboard is None:
            self.degraded_reason = "win32clipboard_unavailable"
            return
        try:
            text, image_bytes = self._read_clipboard_payload()
            self._last_signature = self._signature(text, image_bytes)
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                daemon=True,
                name=f"ClipboardPoll-{self.recording_id}",
            )
            self._poll_thread.start()
        except Exception as exc:
            self.degraded_reason = type(exc).__name__

    def stop(self) -> None:
        self._running = False
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=1.0)
            self._poll_thread = None

    def capture_snapshot(self) -> _ClipboardLatest:
        text = self._read_text()
        image_bytes = self._read_image_bytes() if text is None else None
        with self._lock:
            self._event_seq += 1
            seq = self._event_seq
        sig = self._signature(text, image_bytes)
        with self._lock:
            if sig == self._last_signature:
                return self._latest
        image_path = self._write_image_bytes(image_bytes, seq)
        with self._lock:
            self._latest = _ClipboardLatest(
                text=text,
                image_path=image_path,
                event_seq=seq,
            )
            self._last_signature = sig
            return self._latest

    def latest(self) -> _ClipboardLatest:
        with self._lock:
            return self._latest

    def _poll_loop(self) -> None:
        while self._running:
            try:
                current = self._read_text()
                image_bytes = self._read_image_bytes() if current is None else None
                signature = self._signature(current, image_bytes)
                with self._lock:
                    if signature == self._last_signature:
                        changed = False
                    else:
                        self._event_seq += 1
                        seq = self._event_seq
                        changed = True
                if not changed:
                    time.sleep(self._poll_interval)
                    continue
                image_path = self._write_image_bytes(image_bytes, seq)
                with self._lock:
                    self._latest = _ClipboardLatest(
                        text=current,
                        image_path=image_path,
                        event_seq=seq,
                    )
                    self._last_signature = signature
            except Exception:
                pass
            time.sleep(self._poll_interval)

    def _read_clipboard_payload(self) -> tuple[str | None, bytes | None]:
        return self._read_text(), self._read_image_bytes()

    def _read_text(self) -> str | None:
        if _win32clipboard is None:
            return None
        try:
            _win32clipboard.OpenClipboard()
            try:
                if not _win32clipboard.IsClipboardFormatAvailable(_win32clipboard.CF_UNICODETEXT):
                    return None
                return _win32clipboard.GetClipboardData(_win32clipboard.CF_UNICODETEXT)
            finally:
                _win32clipboard.CloseClipboard()
        except Exception:
            return None

    def _read_image_bytes(self) -> bytes | None:
        if _ImageGrab is None:
            return None
        try:
            data = _ImageGrab.grabclipboard()
            if not hasattr(data, "save"):
                return None
            buf = io.BytesIO()
            data.save(buf, format="PNG")
            return buf.getvalue()
        except Exception:
            return None

    def _write_image_bytes(self, image_bytes: bytes | None, event_seq: int) -> Path | None:
        if not image_bytes:
            return None
        image_dir = self.recording_root / "clipboard"
        image_dir.mkdir(parents=True, exist_ok=True)
        path = image_dir / f"{self.recording_id}_{event_seq:06d}.png"
        path.write_bytes(image_bytes)
        return path

    def _signature(
        self,
        text: str | None,
        image_bytes: bytes | None,
    ) -> tuple[str, str | None, str | None]:
        image_digest = hashlib.sha256(image_bytes).hexdigest() if image_bytes else None
        kind = "image" if image_digest else "text"
        return kind, text, image_digest

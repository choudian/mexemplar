from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ClipWriteResult:
    has_clip: bool
    path: Path | None = None
    duration_ms: int = 0
    fps: int = 15
    resolution: tuple[int, int] | None = None
    reason: str | None = None


class ClipSink:
    def __init__(self, recording_root: Path, *, enable_clip: bool = True, fps: int = 15):
        self.recording_root = Path(recording_root)
        self.enable_clip = enable_clip
        self.fps = fps
        self.clip_total = 0
        self.clip_success = 0
        self._cv2 = None
        self._np = None
        if enable_clip:
            try:
                import cv2
                import numpy as np

                self._cv2 = cv2
                self._np = np
            except Exception:
                self.enable_clip = False

    def write_clip(self, action_id: str, frames: list[object]) -> ClipWriteResult:
        if not self.enable_clip:
            return ClipWriteResult(has_clip=False, reason="disabled", fps=self.fps)

        self.clip_total += 1
        if not frames:
            return ClipWriteResult(has_clip=False, reason="no_frames", fps=self.fps)

        cv2 = self._cv2
        np = self._np
        if cv2 is None or np is None:
            return ClipWriteResult(has_clip=False, reason="cv2_unavailable", fps=self.fps)

        first = getattr(frames[0], "image_data", frames[0])
        if hasattr(first, "size"):
            width, height = first.size
        elif hasattr(first, "shape"):
            height, width = first.shape[:2]
        else:
            return ClipWriteResult(has_clip=False, reason="unsupported_frame", fps=self.fps)

        clips_dir = self.recording_root / "clips"
        clips_dir.mkdir(parents=True, exist_ok=True)
        path = clips_dir / f"{action_id}.mp4"
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            float(self.fps),
            (int(width), int(height)),
        )
        if not writer.isOpened():
            return ClipWriteResult(
                has_clip=False, path=path, reason="writer_open_failed", fps=self.fps
            )

        try:
            for frame in frames:
                image = getattr(frame, "image_data", frame)
                if hasattr(image, "convert"):
                    arr = np.array(image.convert("RGB"))
                    arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                else:
                    arr = np.array(image)
                writer.write(arr)
        finally:
            writer.release()

        self.clip_success += 1
        duration_ms = int(len(frames) / self.fps * 1000)
        return ClipWriteResult(
            has_clip=True,
            path=path,
            duration_ms=duration_ms,
            fps=self.fps,
            resolution=(int(width), int(height)),
        )

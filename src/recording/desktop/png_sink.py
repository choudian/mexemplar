from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable


class PngSink:
    def __init__(self, recording_root: Path):
        self.recording_root = Path(recording_root)

    def write_frames(self, action_id: str, frames: Iterable[object]) -> list[Path]:
        action_dir = self.recording_root / "frames" / str(action_id)
        action_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        for index, frame in enumerate(frames, start=1):
            image = getattr(frame, "image_data", frame)
            path = action_dir / f"frame_{index:03d}.png"
            if hasattr(image, "save"):
                image.save(path, "PNG", compress_level=6)
            else:
                source = getattr(frame, "image_path", None)
                if source is None:
                    raise ValueError("frame must provide image_data.save() or image_path")
                shutil.copy2(source, path)
            paths.append(path)
        return paths

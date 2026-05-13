from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Any

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema, to_json, invoke_vision_model
from src.data.recording_repository import RecordingRepository
from src.data.unified_config import get_unified_config
from src.recording.desktop import DESKTOP_ACTION_TYPES
from src.utils.helpers import get_default_data_dir

logger = logging.getLogger(__name__)

MAX_FRAMES_PER_ACTION = 8


LIST_DESKTOP_ACTIONS_SCHEMA = make_tool_schema(
    name="list_desktop_actions",
    description="列出桌面录制动作。支持按动作类型过滤和分页，limit 最大 500。",
    properties={
        "action_types": {
            "type": "array",
            "items": {"type": "string"},
            "description": "可选动作类型过滤。",
        },
        "limit": {"type": "integer", "description": "返回条数，最大 500。"},
        "offset": {"type": "integer", "description": "分页偏移。"},
    },
    required=[],
)

ANALYZE_DESKTOP_ACTION_SCHEMA = make_tool_schema(
    name="analyze_desktop_action",
    description="用 vision 模型分析最多 2 个桌面动作的 PNG 帧与剪贴板图。",
    properties={
        "action_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要分析的动作 ID，最多 2 个。",
        },
        "question": {"type": "string", "description": "分析问题。"},
    },
    required=["action_ids", "question"],
)

READ_ACTION_CLIP_SCHEMA = make_tool_schema(
    name="read_action_clip",
    description="读取桌面动作 mp4 clip 路径与元数据；无 clip 时返回 clip_unavailable。",
    properties={"action_id": {"type": "string", "description": "动作 ID。"}},
    required=["action_id"],
)


def _list_desktop_actions(
    repo: RecordingRepository,
    recording_id: str,
    action_types: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    invalid = [value for value in (action_types or []) if value not in DESKTOP_ACTION_TYPES]
    if invalid:
        return to_json({"error": "invalid_action_type", "value": invalid[0]})
    if limit > 500:
        return to_json({"error": "limit_too_large", "limit": limit})
    rows = repo.list_desktop_actions(
        recording_id,
        action_types=action_types,
        limit=limit,
        offset=offset,
    )
    return to_json({"actions": rows, "count": len(rows)})


def _read_action_clip(
    repo: RecordingRepository,
    recording_id: str,
    action_id: str,
) -> str:
    row = repo.get_desktop_action_clip(recording_id, action_id)
    if row is None or not row.get("has_clip"):
        return to_json({"error": "clip_unavailable", "action_id": action_id})
    return to_json(
        {
            "action_id": action_id,
            "path": row["clip_path"],
            "duration_ms": row["clip_duration_ms"],
            "fps": row["clip_fps"],
            "resolution": row["clip_resolution"],
        }
    )


def _encode_image_for_vision(path: Path) -> dict[str, str]:
    from PIL import Image

    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1280, 1280))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
    return {
        "data": base64.standard_b64encode(buf.getvalue()).decode("ascii"),
        "media_type": "image/png",
    }


def _resolve_recording_path(recording_id: str, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return get_default_data_dir() / "recordings" / recording_id / path


def _action_frame_paths(recording_id: str, action_id: str) -> list[Path]:
    frame_dir = get_default_data_dir() / "recordings" / recording_id / "frames" / action_id
    return sorted(frame_dir.glob("*.png"))


def _append_image_part(content: list[dict[str, Any]], label: str, path: Path) -> bool:
    try:
        image = _encode_image_for_vision(path)
    except Exception as exc:
        logger.warning("[analyze_desktop_action] 图片读取失败 %s: %s", path, exc)
        content.append({"type": "text", "text": f"[{label}] [error: image_read_failed]"})
        return False
    content.append({"type": "text", "text": f"[{label}]"})
    content.append(
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:{image['media_type']};base64,{image['data']}",
            },
        }
    )
    return True


def _build_desktop_vision_content(
    recording_id: str,
    action_ids: list[str],
    rows: list[dict[str, Any]],
    question: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows_by_id = {row["action_id"]: row for row in rows}
    content: list[dict[str, Any]] = []
    counts = {"frames": 0, "clipboard_images": 0}
    for action_id in action_ids:
        row = rows_by_id[action_id]
        summary = {
            "action_id": row["action_id"],
            "type": row["type"],
            "window_title": row["window_title"],
            "text_content": row["text_content"],
            "clipboard_text": row["clipboard_text"],
        }
        content.append(
            {
                "type": "text",
                "text": (f"[动作 {action_id} 元数据]\n" f"{to_json(summary)}"),
            }
        )

        clipboard_path = _resolve_recording_path(
            recording_id,
            row.get("clipboard_image_path"),
        )
        if clipboard_path is not None:
            if clipboard_path.exists():
                if _append_image_part(content, f"动作 {action_id} 剪贴板图", clipboard_path):
                    counts["clipboard_images"] += 1
            else:
                content.append(
                    {
                        "type": "text",
                        "text": f"[动作 {action_id} 剪贴板图] [error: image_missing]",
                    }
                )

        frame_paths = _action_frame_paths(recording_id, action_id)
        if len(frame_paths) > MAX_FRAMES_PER_ACTION:
            step = len(frame_paths) / MAX_FRAMES_PER_ACTION
            frame_paths = [frame_paths[int(i * step)] for i in range(MAX_FRAMES_PER_ACTION)]
        for index, frame_path in enumerate(frame_paths, start=1):
            if _append_image_part(content, f"动作 {action_id} 帧 {index:03d}", frame_path):
                counts["frames"] += 1

    content.append({"type": "text", "text": question})
    return content, counts


def _analyze_desktop_action(
    repo: RecordingRepository,
    recording_id: str,
    action_ids: list[str],
    question: str,
) -> str:
    if not action_ids:
        return to_json({"error": "action_required"})
    if len(action_ids) > 2:
        return to_json({"error": "too_many_actions", "limit": 2})
    model = get_unified_config().get_desktop_vision_model()
    if not model:
        return to_json({"error": "vision_model_missing"})

    rows = repo.get_desktop_actions_by_ids(recording_id, action_ids)
    rows_by_id = {row["action_id"]: row for row in rows}
    missing = [action_id for action_id in action_ids if action_id not in rows_by_id]
    if missing:
        return to_json({"error": "action_not_found", "action_ids": missing})

    content, evidence_counts = _build_desktop_vision_content(
        recording_id,
        action_ids,
        rows,
        question,
    )
    if evidence_counts["frames"] == 0 and evidence_counts["clipboard_images"] == 0:
        return to_json({"error": "visual_evidence_missing", "action_ids": action_ids})

    try:
        answer = invoke_vision_model(content, model)
    except Exception as exc:
        logger.error("[analyze_desktop_action] 调用多模态模型失败: %s", exc, exc_info=True)
        return to_json({"error": f"vision_model_call_failed: {exc}"})

    ordered_rows = [rows_by_id[action_id] for action_id in action_ids]
    return to_json(
        {
            "analysis": answer,
            "model": model,
            "recording_id": recording_id,
            "actions": ordered_rows,
            "evidence": evidence_counts,
        }
    )


def create_desktop_specific_tools(recording_id: str) -> list[ToolDefinition]:
    repo = RecordingRepository()
    tools = [
        ToolDefinition(
            name="list_desktop_actions",
            schema=LIST_DESKTOP_ACTIONS_SCHEMA,
            handler=lambda action_types=None, limit=100, offset=0: _list_desktop_actions(
                repo, recording_id, action_types, limit, offset
            ),
        ),
        ToolDefinition(
            name="read_action_clip",
            schema=READ_ACTION_CLIP_SCHEMA,
            handler=lambda action_id: _read_action_clip(repo, recording_id, action_id),
        ),
    ]
    if get_unified_config().get_desktop_vision_model():
        tools.insert(
            1,
            ToolDefinition(
                name="analyze_desktop_action",
                schema=ANALYZE_DESKTOP_ACTION_SCHEMA,
                handler=lambda action_ids, question: _analyze_desktop_action(
                    repo, recording_id, action_ids, question
                ),
            ),
        )
    return tools

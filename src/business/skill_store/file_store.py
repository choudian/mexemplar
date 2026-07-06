"""受管外部技能文件目录（029 CC-174）。

写盘硬边界：相对路径规范化后不得逃出目标目录（拒绝 ``..``、绝对路径、盘符）；
单文件/总量/数量上限；仅 UTF-8 文本。原子成对：先写临时目录，全部校验通过后
rename 到最终目录，任一步失败整体清理零残留。
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from src.utils.helpers import get_default_data_dir

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_FILE_COUNT = 40

_EXTERNAL_SKILLS_DIRNAME = "external_skills"


class SkillFileStoreError(ValueError):
    """文件校验/写盘失败——消息面向用户可读。"""


@dataclass(frozen=True)
class SkillFile:
    """一个待落盘的技能文件（路径为技能内相对路径，POSIX 风格）。"""

    path: str
    content: str


def external_skills_root() -> Path:
    root = get_default_data_dir() / _EXTERNAL_SKILLS_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_files(files: list[SkillFile]) -> None:
    """校验文件集合（数量/大小/路径边界）；越界抛 SkillFileStoreError。"""
    if not files:
        raise SkillFileStoreError("技能不包含任何文件")
    if len(files) > MAX_FILE_COUNT:
        raise SkillFileStoreError(f"技能文件数超过上限（{len(files)} > {MAX_FILE_COUNT}）")
    total = 0
    for item in files:
        _assert_safe_relative_path(item.path)
        size = len(item.content.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise SkillFileStoreError(
                f"文件 {item.path} 超过单文件上限（{size} > {MAX_FILE_BYTES} 字节）"
            )
        total += size
    if total > MAX_TOTAL_BYTES:
        raise SkillFileStoreError(f"技能总大小超过上限（{total} > {MAX_TOTAL_BYTES} 字节）")


def write_install_dir(install_id: str, files: list[SkillFile]) -> Path:
    """原子写入受管目录：临时目录写全 → rename 到 external_skills/<install_id>。

    Returns 最终目录 Path；失败时清理临时目录并抛 SkillFileStoreError。
    """
    validate_files(files)
    root = external_skills_root()
    final_dir = root / install_id
    if final_dir.exists():
        raise SkillFileStoreError(f"安装目录已存在：{install_id}")
    temp_dir = root / f".tmp_{install_id}"
    try:
        temp_dir.mkdir(parents=True, exist_ok=False)
        for item in files:
            target = temp_dir / PurePosixPath(item.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item.content, encoding="utf-8")
        temp_dir.rename(final_dir)
        return final_dir
    except SkillFileStoreError:
        raise
    except Exception as exc:
        raise SkillFileStoreError(f"技能文件写入失败：{exc}") from exc
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def remove_install_dir(install_id: str) -> None:
    """整目录清理（卸载/失败回滚）；目录名再过一次安全校验防误删。"""
    _assert_safe_relative_path(install_id)
    target = external_skills_root() / install_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)


def _assert_safe_relative_path(relative_path: str) -> None:
    raw = (relative_path or "").strip()
    if not raw:
        raise SkillFileStoreError("文件路径为空")
    posix = PurePosixPath(raw.replace("\\", "/"))
    if posix.is_absolute() or raw.startswith(("/", "\\")):
        raise SkillFileStoreError(f"拒绝绝对路径：{relative_path}")
    if any(part == ".." for part in posix.parts):
        raise SkillFileStoreError(f"拒绝越界路径：{relative_path}")
    # Windows 盘符（C:）与保留冒号
    if ":" in raw:
        raise SkillFileStoreError(f"拒绝含盘符/冒号路径：{relative_path}")

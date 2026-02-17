"""
录制数据导入模块

支持从浏览器插件导出的JSON文件导入录制数据
"""

import json
import logging
from pathlib import Path
from .recorder import RecordingSession, Action, NetworkRequest

logger = logging.getLogger(__name__)


def import_recording_from_json(file_path: Path) -> RecordingSession:
    """
    从JSON文件导入录制数据

    Args:
        file_path: JSON文件路径

    Returns:
        RecordingSession对象

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON格式错误
        KeyError: 缺少必需的字段
    """
    if not file_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 使用RecordingSession.from_dict方法
        session = RecordingSession.from_dict(data)

        logger.info(
            f"成功导入录制数据: {session.recording_id}, "
            f"操作数: {len(session.actions)}, "
            f"录制模式: {session.recording_mode}"
        )

        return session

    except json.JSONDecodeError as e:
        logger.error(f"JSON解析失败: {e}")
        raise ValueError(f"JSON格式错误: {e}")
    except KeyError as e:
        logger.error(f"缺少必需的字段: {e}")
        raise KeyError(f"JSON缺少必需的字段: {e}")
    except Exception as e:
        logger.error(f"导入录制数据失败: {e}", exc_info=True)
        raise


def save_imported_recording(session: RecordingSession, storage_path: Path) -> Path:
    """
    保存导入的录制数据到标准存储位置

    Args:
        session: 录制会话对象
        storage_path: 存储目录

    Returns:
        保存的文件路径

    Raises:
        OSError: 文件写入失败
    """
    storage_path.mkdir(parents=True, exist_ok=True)

    # 保存JSON文件
    file_path = storage_path / f"{session.recording_id}.json"

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

        logger.info(f"录制数据已保存到: {file_path}")

        return file_path

    except OSError as e:
        logger.error(f"保存录制数据失败: {e}")
        raise


def validate_imported_recording(session: RecordingSession) -> tuple:
    """
    验证导入的录制数据

    Args:
        session: 录制会话对象

    Returns:
        (is_valid, error_message) 元组
    """
    if not session.recording_id:
        return False, "缺少recording_id"

    if not session.actions:
        return False, "没有录制任何操作"

    if session.recording_mode != "browser":
        return False, f"录制模式不是browser: {session.recording_mode}"

    # 验证actions的基本字段
    for i, action in enumerate(session.actions):
        if not action.action_type:
            return False, f"操作 #{i+1} 缺少action_type"
        if action.recording_mode != "browser":
            return False, f"操作 #{i+1} 的recording_mode不是browser"

    return True, None

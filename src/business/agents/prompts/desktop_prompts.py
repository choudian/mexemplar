from __future__ import annotations

from src.business.agents.prompts.pm_prompt import PM_SYSTEM_PROMPT as PM_SYSTEM_PROMPT_LEGACY
from src.business.agents.prompts.programmer_prompt import (
    PROGRAMMER_SYSTEM_PROMPT as PROGRAMMER_SYSTEM_PROMPT_LEGACY,
)
from src.data.unified_config import get_unified_config
from src.recording.browser.recorder import RecordingMode

_PM_COMMON_HEADER = "你是桌面录制需求分析 Agent，优先用结构化动作数据理解用户目标。\n"
_PM_DESKTOP_GUIDANCE = (
    "先调用 list_desktop_actions 查看头尾动作；按 window_title 聚焦关键应用窗口；"
    "跳过重复 typing / wheel 噪声；对关键视觉节点调用 analyze_desktop_action；"
    "需要回放 clip 元数据时调用 read_action_clip。\n"
)
_PM_DESKTOP_NO_VISION_GUIDANCE = (
    "先调用 read_recording 和 list_desktop_actions 查看头尾动作；按 window_title 聚焦关键应用窗口；"
    "跳过重复 typing / wheel 噪声；当前未配置桌面视觉模型，只使用结构化动作和 clip 元数据；"
    "需要回放 clip 元数据时调用 read_action_clip。\n"
)
_PM_COMMON_FOOTER = "最后通过既有终态工具把可执行 intent 交给用户确认。\n"

_PROGRAMMER_COMMON_HEADER = (
    "你是桌面自动化 Programmer Agent，输出可在真实桌面试用的 Python 代码。\n"
)
_PROGRAMMER_DESKTOP_GUIDANCE = (
    "优先寻找系统 API、命令行、pywinauto、Win32 协议等捷径；"
    "例如能直接打开文件或发送协议 URL 时，不要模拟多次鼠标点击。"
    "生成代码必须定义 async def execute() -> dict，并返回包含 ok、summary、details 的 dict。\n"
)
_PROGRAMMER_COMMON_FOOTER = "只返回完整可执行代码，不返回解释性 Markdown。\n"


def build_pm_prompt(recording_mode: str, vision_enabled: bool | None = None) -> str:
    if recording_mode == RecordingMode.BROWSER:
        return PM_SYSTEM_PROMPT_LEGACY
    if recording_mode == RecordingMode.DESKTOP:
        if vision_enabled is None:
            vision_enabled = bool(get_unified_config().get_desktop_vision_model())
        guidance = _PM_DESKTOP_GUIDANCE if vision_enabled else _PM_DESKTOP_NO_VISION_GUIDANCE
        return _PM_COMMON_HEADER + guidance + _PM_COMMON_FOOTER
    raise ValueError(f"Unknown recording_mode: {recording_mode}")


def build_programmer_prompt(recording_mode: str) -> str:
    if recording_mode == RecordingMode.BROWSER:
        return PROGRAMMER_SYSTEM_PROMPT_LEGACY
    if recording_mode == RecordingMode.DESKTOP:
        return _PROGRAMMER_COMMON_HEADER + _PROGRAMMER_DESKTOP_GUIDANCE + _PROGRAMMER_COMMON_FOOTER
    raise ValueError(f"Unknown recording_mode: {recording_mode}")

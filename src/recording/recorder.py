"""
录制器模块

负责协调数据采集、存储和管理录制过程
"""

import json
import uuid
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import os
from .data_collector import DataCollector, RecordingEvent, ScreenshotData
from src.utils.events import emit, RecordingEventData
import logging

logger = logging.getLogger(__name__)


@dataclass
class NetworkRequest:
    """网络请求信息"""

    url: str  # 请求URL
    method: str  # HTTP方法（GET、POST等）
    request_headers: Dict[str, str] = field(default_factory=dict)  # 请求头
    request_body: Optional[str] = None  # 请求体
    response_status: Optional[int] = None  # 响应状态码
    response_headers: Dict[str, str] = field(default_factory=dict)  # 响应头
    response_body: Optional[str] = None  # 响应体
    timestamp: float = 0.0  # 时间戳
    duration: Optional[float] = None  # 请求持续时间（秒）
    request_id: Optional[int] = None  # 数据库ID（从数据库读取时才有）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "url": self.url,
            "method": self.method,
            "request_headers": self.request_headers,
            "request_body": self.request_body,
            "response_status": self.response_status,
            "response_headers": self.response_headers,
            "response_body": self.response_body,
            "timestamp": self.timestamp,
            "duration": self.duration,
            "request_id": self.request_id,  # 数据库ID
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NetworkRequest":
        """从字典创建"""
        return cls(
            url=data["url"],
            method=data["method"],
            request_headers=data.get("request_headers", {}),
            request_body=data.get("request_body"),
            response_status=data.get("response_status"),
            response_headers=data.get("response_headers", {}),
            response_body=data.get("response_body"),
            timestamp=data.get("timestamp", 0.0),
            duration=data.get("duration"),
            request_id=data.get("request_id"),  # 数据库ID（可选）
        )


@dataclass
class Action:
    """操作序列"""

    action_type: str  # 'click', 'keyboard_input', 'window_switch', 'scroll'
    recording_mode: str = "desktop"  # 录制模式（'browser' 或 'desktop'）
    app_name: Optional[str] = None  # 应用显示名称
    process_name: Optional[str] = None  # 进程名
    app_path: Optional[str] = None  # 应用路径
    process_id: Optional[int] = None  # 进程ID
    window_title: Optional[str] = None  # 窗口标题
    parameters: Dict[str, Any] = field(default_factory=dict)  # 操作参数
    screenshot_before: Optional[str] = None  # 操作前截图路径
    screenshot_after: Optional[str] = None  # 操作后截图路径
    url: Optional[str] = None  # URL（浏览器地址栏或被点击链接的URL）
    dom_element: Optional[Dict[str, Any]] = None  # DOM元素信息（浏览器模式）
    network_requests: Optional[List[NetworkRequest]] = None  # 关联的网络请求列表（浏览器模式）
    timestamp: float = 0.0  # 时间戳

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        # 处理 network_requests：可能是对象列表或字典列表
        network_requests_list = []
        if self.network_requests:
            for req in self.network_requests or []:
                if isinstance(req, dict):
                    # 如果已经是字典，直接使用
                    network_requests_list.append(req)
                elif hasattr(req, "to_dict"):
                    # 如果是对象，调用 to_dict()
                    network_requests_list.append(req.to_dict())
                else:
                    # 其他类型，跳过
                    pass

        return {
            "action_type": self.action_type,
            "recording_mode": self.recording_mode,
            "app_name": self.app_name,
            "process_name": self.process_name,
            "app_path": self.app_path,
            "process_id": self.process_id,
            "window_title": self.window_title,
            "parameters": self.parameters,
            "screenshot_before": self.screenshot_before,
            "screenshot_after": self.screenshot_after,
            "url": self.url,
            "dom_element": self.dom_element,
            "network_requests": network_requests_list,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Action":
        """从字典创建"""
        # 修复：明确检查 None，而不是依赖布尔值判断
        # 这样可以正确区分 None 和空列表 []
        network_requests_data = data.get("network_requests")
        network_requests = None
        if network_requests_data is not None:
            network_requests = [NetworkRequest.from_dict(req) for req in network_requests_data]

        return cls(
            action_type=data["action_type"],
            recording_mode=data.get("recording_mode", "desktop"),  # 向后兼容，默认为desktop
            app_name=data.get("app_name"),
            process_name=data.get("process_name"),
            app_path=data.get("app_path"),
            process_id=data.get("process_id"),
            window_title=data.get("window_title"),
            parameters=data.get("parameters", {}),
            screenshot_before=data.get("screenshot_before"),
            screenshot_after=data.get("screenshot_after"),
            url=data.get("url"),
            dom_element=data.get("dom_element"),
            network_requests=network_requests,
            timestamp=data.get("timestamp", 0.0),
        )


@dataclass
class RecordingSession:
    """录制会话"""

    recording_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "idle"  # 'idle', 'recording', 'stopped', 'processing', 'completed'
    recording_mode: str = "desktop"  # 录制模式（'browser' 或 'desktop'）
    browser_type: Optional[str] = None  # 浏览器类型（如果使用浏览器模式）
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    events: List[RecordingEvent] = field(default_factory=list)  # 原始事件（保留用于向后兼容）
    actions: List[Action] = field(default_factory=list)  # 操作序列（新增）
    video_file: Optional[str] = None  # 视频文件路径
    screenshots_dir: Optional[str] = None  # 截图目录路径
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "recording_id": self.recording_id,
            "status": self.status,
            "recording_mode": self.recording_mode,
            "browser_type": self.browser_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "events": [asdict(event) for event in self.events],
            "actions": [action.to_dict() for action in self.actions],
            "video_file": self.video_file,
            "screenshots_dir": self.screenshots_dir,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecordingSession":
        """从字典创建"""
        events = []
        for event_data in data.get("events", []):
            event = RecordingEvent(
                event_type=event_data["event_type"],
                data=event_data["data"],
                timestamp=event_data["timestamp"],
            )
            events.append(event)

        actions = []
        for action_data in data.get("actions", []):
            action = Action.from_dict(action_data)
            actions.append(action)

        return cls(
            recording_id=data["recording_id"],
            status=data["status"],
            recording_mode=data.get("recording_mode", "desktop"),  # 向后兼容，默认为desktop
            browser_type=data.get("browser_type"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            events=events,
            actions=actions,
            video_file=data.get("video_file"),
            screenshots_dir=data.get("screenshots_dir"),
            metadata=data.get("metadata", {}),
        )


class Recorder:
    """录制器"""

    def __init__(
        self, storage_path: Optional[str] = None, config=None, recording_mode: Optional[str] = None
    ):
        """
        初始化录制器

        Args:
            storage_path: 录制数据存储路径，如果为None则使用默认路径
            config: RecordingConfig配置对象（已废弃，保留向后兼容）
            recording_mode: 录制模式（'browser' 或 'desktop'），如果为None则使用配置中的默认值

        注意：
            - config 参数已废弃，仅保留向后兼容
            - 所有配置现在通过 get_unified_config() 访问
        """
        # ⭐ 重构：不再直接实例化 RecordingConfig
        # 保留 config 参数以保持向后兼容，但不使用它
        # 所有配置访问都通过 get_unified_config()
        if config is not None:
            logger.warning(
                "[Recorder] config 参数已废弃，所有配置现在通过 get_unified_config() 访问"
            )

        # 使用统一配置管理器
        from src.data.unified_config import get_unified_config

        self._unified_config = get_unified_config()

        # 确定录制模式
        if recording_mode:
            self.recording_mode = recording_mode
        else:
            self.recording_mode = self._unified_config.get(
                "recording.default_recording_mode", default="desktop"
            )

        # 根据模式初始化对应的录制器
        if self.recording_mode == "browser":
            from .browser_recorder import BrowserRecorder

            self.browser_recorder = BrowserRecorder()  # 不再传递 config 参数
            self.data_collector = None  # 浏览器模式不使用DataCollector
        else:
            self.data_collector = DataCollector()  # 不再传递 config 参数
            self.browser_recorder = None

        self.current_session: Optional[RecordingSession] = None

        if storage_path is None:
            # 使用项目根目录下的data/recordings目录
            project_root = Path(
                __file__
            ).parent.parent.parent  # 从src/recording/recorder.py到项目根目录
            storage_path = project_root / "data" / "recordings"
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def start_recording(self, start_url: Optional[str] = None) -> str:
        """
        开始录制

        Args:
            start_url: 浏览器启动URL（仅浏览器模式有效）

        Returns:
            录制会话ID
        """
        if self.current_session and self.current_session.status == "recording":
            logger.warning("录制已在进行中")
            return self.current_session.recording_id

        # 创建新的录制会话
        browser_type = (
            self._unified_config.get("recording.browser_type", default=None)
            if self.recording_mode == "browser"
            else None
        )
        self.current_session = RecordingSession(
            status="recording",
            recording_mode=self.recording_mode,
            browser_type=browser_type,
            start_time=datetime.now().timestamp(),
            metadata={
                "created_at": datetime.now().isoformat(),
            },
        )

        # 根据模式启动对应的录制器
        if self.recording_mode == "browser":
            # 浏览器录制模式
            if not self.browser_recorder:
                from .browser_recorder import BrowserRecorder

                self.browser_recorder = BrowserRecorder()  # 不再传递 config

            # 设置回调函数
            self.browser_recorder.on_action = self._on_browser_action

            # 启动浏览器录制（传递 recording_id 以保持一致）
            browser_start_url = start_url or self._unified_config.get(
                "recording.browser_start_url", default=None
            )
            # ⭐ 异步重构：start_recording() 现在是同步方法（内部维护持久事件循环）
            if not self.browser_recorder.start_recording(
                start_url=browser_start_url,
                recording_id=self.current_session.recording_id,  # 传递ID
            ):
                raise RuntimeError("启动浏览器录制失败")

            logger.info(f"开始浏览器录制，会话ID: {self.current_session.recording_id}")
        else:
            # 桌面录制模式
            # 创建录制会话目录（仅桌面模式需要）
            session_dir = self.storage_path / self.current_session.recording_id
            session_dir.mkdir(parents=True, exist_ok=True)

            if not self.data_collector:
                self.data_collector = DataCollector()  # 不再传递 config

            # 创建截图目录
            screenshots_dir = session_dir / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)

            # 视频文件路径
            video_path = session_dir / "video.mp4"

            # 启动数据采集（传递截图目录和视频路径）
            self.data_collector.start_collecting(
                screenshots_dir=screenshots_dir, video_path=video_path
            )

            logger.info(f"开始桌面录制，会话ID: {self.current_session.recording_id}")

        # 发送录制开始事件
        emit(
            "recording_started",
            event_data=RecordingEventData(
                session_id=self.current_session.recording_id,
                recording_mode=self.recording_mode,
                start_time=self.current_session.start_time,
            ),
        )

        return self.current_session.recording_id

    def stop_recording(self) -> Optional[RecordingSession]:
        """
        停止录制

        Returns:
            录制会话对象
        """
        if not self.current_session or self.current_session.status != "recording":
            logger.warning("没有正在进行的录制")
            return None

        # 根据模式停止对应的录制器
        queue_file = None
        recording_result = None

        if self.recording_mode == "browser":
            # 浏览器录制模式
            # ⭐ 新架构：BrowserRecorder.stop_recording() 现在返回结果字典
            # ⭐ 异步重构：stop_recording() 现在是同步方法（内部维护持久事件循环）
            if self.browser_recorder:
                recording_result = self.browser_recorder.stop_recording()
                queue_file = recording_result.get("queue_file") if recording_result else None

            # 浏览器模式的操作已经在录制过程中写入队列文件
            # 不再通过 on_action 回调收集
            events = []  # 浏览器模式不使用events
        else:
            # 桌面录制模式
            # 停止数据采集
            if self.data_collector:
                self.data_collector.stop_collecting()

                # 获取采集的事件
                events = self.data_collector.get_events()
                self.current_session.events = events

                # 将事件转换为操作序列
                actions = self._convert_events_to_actions(events)
                self.current_session.actions = actions
            else:
                events = []

        # 设置视频文件和截图目录路径（仅桌面模式）
        if self.recording_mode == "desktop":
            session_dir = self.storage_path / self.current_session.recording_id
            video_file = session_dir / "video.mp4"
            if video_file.exists():
                self.current_session.video_file = str(video_file)
            screenshots_dir = session_dir / "screenshots"
            if screenshots_dir.exists():
                self.current_session.screenshots_dir = str(screenshots_dir)

        self.current_session.end_time = datetime.now().timestamp()
        self.current_session.status = "stopped"

        # 更新元数据
        duration = self.current_session.end_time - self.current_session.start_time

        # ⭐ 新架构：从 recording_result 获取 action_count（浏览器模式）
        if self.recording_mode == "browser" and recording_result:
            action_count = recording_result.get("action_count", 0)
            # 添加队列文件路径到元数据
            if queue_file:
                self.current_session.metadata["queue_file"] = queue_file
        else:
            # 桌面模式：从 actions 列表获取
            action_count = len(self.current_session.actions) if self.current_session.actions else 0

        self.current_session.metadata.update(
            {
                "duration": duration,
                "event_count": len(events),
                "action_count": action_count,
                "stopped_at": datetime.now().isoformat(),
            }
        )

        logger.info(
            f"录制已停止，会话ID: {self.current_session.recording_id}, 事件数: {len(events)}, 操作数: {action_count}"
        )

        # 发送录制停止事件
        emit(
            "recording_stopped",
            event_data=RecordingEventData(
                session_id=self.current_session.recording_id,
                recording_mode=self.recording_mode,
                start_time=self.current_session.start_time,
                end_time=self.current_session.end_time,
                action_count=action_count,
            ),
        )

        # ⭐ 新架构：发送轻量级录制完成事件（只包含 recording_id 和队列文件路径）
        # 监听器负责从队列文件读取完整数据
        emit(
            "recording_completed",
            event_data={
                "recording_id": self.current_session.recording_id,
                "recording_mode": self.recording_mode,
                "start_time": self.current_session.start_time,
                "end_time": self.current_session.end_time,
                "action_count": action_count,
                "queue_file": queue_file,  # ⭐ 新增：队列文件路径
                "metadata": self.current_session.metadata,
            },
        )

        return self.current_session

    def _on_browser_action(self, browser_action):
        """
        浏览器操作回调函数

        将BrowserAction转换为Action并添加到会话中
        """
        if not self.current_session:
            logger.warning("[Recorder] current_session 为空，跳过浏览器事件")
            return

        # 安全地获取窗口标题（避免跨线程访问 Playwright 对象）
        window_title = None
        try:
            # 检查浏览器是否还在运行
            if self.browser_recorder._browser and self.browser_recorder.page:
                # 检查页面是否已关闭
                if (
                    hasattr(self.browser_recorder.page, "_is_closed")
                    and not self.browser_recorder.page._is_closed
                ):
                    window_title = self.browser_recorder.page.title()
        except Exception as e:
            # 静默忽略所有错误（跨线程、页面关闭等）
            # 不记录日志，避免干扰用户
            pass

        # 转换BrowserAction为Action
        action = Action(
            action_type=browser_action.action_type,
            recording_mode="browser",
            app_name="Browser",
            process_name="browser",
            window_title=window_title,
            parameters=browser_action.parameters,
            url=browser_action.url,
            dom_element=browser_action.dom_element,
            network_requests=browser_action.network_requests,
            timestamp=browser_action.timestamp,
        )

        # 添加到会话的操作列表
        if not self.current_session.actions:
            self.current_session.actions = []
        self.current_session.actions.append(action)

    def _convert_events_to_actions(self, events: List[RecordingEvent]) -> List[Action]:
        """将事件转换为操作序列"""
        actions = []

        for event in events:
            action_type_map = {
                "mouse": "click" if event.data.get("event_type") == "click" else "scroll",
                "keyboard": "keyboard_input",
                "window_change": "window_switch",
            }

            action_type = action_type_map.get(event.event_type)
            if not action_type:
                continue

            # 提取操作参数
            parameters = {}
            if event.event_type == "mouse":
                parameters = {
                    "x": event.data.get("x"),
                    "y": event.data.get("y"),
                    "button": event.data.get("button"),
                }
                if event.data.get("event_type") == "scroll":
                    parameters["scroll_dx"] = event.data.get("scroll_dx")
                    parameters["scroll_dy"] = event.data.get("scroll_dy")
            elif event.event_type == "keyboard":
                parameters = {
                    "key": event.data.get("key"),
                }
            elif event.event_type == "window_change":
                parameters = {
                    "window_class": event.data.get("window_class"),
                    "hwnd": event.data.get("hwnd"),
                    "position": event.data.get("position"),
                }

            # 处理网络请求列表
            network_requests = None
            if event.data.get("network_requests"):
                network_requests = [
                    NetworkRequest.from_dict(req) if isinstance(req, dict) else req
                    for req in event.data.get("network_requests", [])
                ]

            action = Action(
                action_type=action_type,
                recording_mode=event.data.get("recording_mode", "desktop"),
                app_name=event.data.get("app_name"),
                process_name=event.data.get("process_name"),
                app_path=event.data.get("app_path"),
                process_id=event.data.get("process_id"),
                window_title=event.data.get("window_title"),
                parameters=parameters,
                screenshot_before=event.data.get("screenshot_before"),
                screenshot_after=event.data.get("screenshot_after"),
                url=event.data.get("url"),
                dom_element=event.data.get("dom_element"),
                network_requests=network_requests,
                timestamp=event.timestamp,
            )
            actions.append(action)

        return actions

    def save_recording(self, session: Optional[RecordingSession] = None) -> Optional[str]:
        """
        保存录制数据

        Args:
            session: 录制会话，如果为None则使用当前会话

        Returns:
            保存的文件路径
        """
        if session is None:
            session = self.current_session

        if session is None:
            logger.error("没有可保存的录制会话")
            return None

        try:
            # 保存为JSON文件
            file_path = self.storage_path / f"{session.recording_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)

            logger.info(f"录制数据已保存: {file_path}")
            return str(file_path)
        except Exception as e:
            logger.error(f"保存录制数据失败: {e}")
            raise

    def load_recording(self, recording_id: str) -> Optional[RecordingSession]:
        """
        加载录制数据

        Args:
            recording_id: 录制会话ID

        Returns:
            录制会话对象
        """
        try:
            file_path = self.storage_path / f"{recording_id}.json"
            if not file_path.exists():
                logger.error(f"录制文件不存在: {file_path}")
                return None

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            session = RecordingSession.from_dict(data)
            logger.info(f"录制数据已加载: {recording_id}")
            return session
        except Exception as e:
            logger.error(f"加载录制数据失败: {e}")
            return None

    def capture_screenshot(self) -> Optional[ScreenshotData]:
        """
        捕获屏幕截图

        Returns:
            截图数据
        """
        if self.recording_mode == "browser":
            # 浏览器模式不支持截图（可以通过Playwright截图，但暂时不实现）
            return None
        else:
            return self.data_collector.capture_screenshot() if self.data_collector else None

    def get_recording_status(self) -> str:
        """
        获取录制状态

        Returns:
            状态字符串
        """
        if self.current_session:
            return self.current_session.status
        return "idle"

    def get_current_session(self) -> Optional[RecordingSession]:
        """获取当前录制会话"""
        return self.current_session

    def clear_session(self):
        """清空当前会话"""
        self.current_session = None
        if self.data_collector:
            self.data_collector.clear_events()
        if self.browser_recorder:
            self.browser_recorder._recent_actions.clear()
            self.browser_recorder._recent_requests.clear()

    def close(self):
        """关闭录制器"""
        try:
            if self.recording_mode == "browser":
                if self.browser_recorder and self.browser_recorder.is_recording():
                    self.stop_recording()
            else:
                if (
                    self.data_collector
                    and hasattr(self.data_collector, "is_collecting")
                    and self.data_collector.is_collecting()
                ):
                    self.stop_recording()
                if self.data_collector:
                    self.data_collector.close()
        except Exception as e:
            logger.warning(f"关闭录制器时出错: {e}")


# ============================================================================
# 增强的数据类（Phase 2: DuckDB 集成）
# ============================================================================


@dataclass
class VisualFeatures:
    """视觉特征信息"""

    element_position: Dict[str, int] = field(default_factory=dict)  # {x, y, width, height}
    viewport_position: Dict[str, int] = field(default_factory=dict)  # 相对视口的位置
    background_color: Optional[str] = None
    text_color: Optional[str] = None
    font_size: Optional[int] = None
    is_visible: bool = True
    z_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "element_position": self.element_position,
            "viewport_position": self.viewport_position,
            "background_color": self.background_color,
            "text_color": self.text_color,
            "font_size": self.font_size,
            "is_visible": self.is_visible,
            "z_index": self.z_index,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualFeatures":
        """从字典创建"""
        return cls(
            element_position=data.get("element_position", {}),
            viewport_position=data.get("viewport_position", {}),
            background_color=data.get("background_color"),
            text_color=data.get("text_color"),
            font_size=data.get("font_size"),
            is_visible=data.get("is_visible", True),
            z_index=data.get("z_index"),
        )


@dataclass
class SiblingElement:
    """单个兄弟元素的信息"""

    index: int  # 在列表中的位置

    # 结构信息
    tag: str
    class_list: List[str] = field(default_factory=list)
    xpath: Optional[str] = None
    css_selector: Optional[str] = None

    # 内容摘要
    text_summary: Optional[str] = None  # 前 50 字符
    href: Optional[str] = None
    src: Optional[str] = None  # 图片/资源

    # 内部结构
    has_link: bool = False
    has_image: bool = False
    child_tags: List[str] = field(default_factory=list)

    # 视觉特征（精简）
    position: Optional[Dict[str, int]] = None  # {x, y, width, height}
    background_color: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "index": self.index,
            "tag": self.tag,
            "class_list": self.class_list,
            "xpath": self.xpath,
            "css_selector": self.css_selector,
            "text_summary": self.text_summary,
            "href": self.href,
            "src": self.src,
            "has_link": self.has_link,
            "has_image": self.has_image,
            "child_tags": self.child_tags,
            "position": self.position,
            "background_color": self.background_color,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SiblingElement":
        """从字典创建"""
        return cls(
            index=data["index"],
            tag=data["tag"],
            class_list=data.get("class_list", []),
            xpath=data.get("xpath"),
            css_selector=data.get("css_selector"),
            text_summary=data.get("text_summary"),
            href=data.get("href"),
            src=data.get("src"),
            has_link=data.get("has_link", False),
            has_image=data.get("has_image", False),
            child_tags=data.get("child_tags", []),
            position=data.get("position"),
            background_color=data.get("background_color"),
        )


@dataclass
class SiblingsSnapshot:
    """兄弟元素快照"""

    container_selector: Optional[str] = None
    item_selector: Optional[str] = None
    list_type: Optional[str] = None  # 'list', 'grid', 'table'
    structure_similarity: float = 0.0
    is_homogeneous: bool = False
    clicked_index: int = -1
    total_count: int = 0
    siblings: List[SiblingElement] = field(default_factory=list)
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "container_selector": self.container_selector,
            "item_selector": self.item_selector,
            "list_type": self.list_type,
            "structure_similarity": self.structure_similarity,
            "is_homogeneous": self.is_homogeneous,
            "clicked_index": self.clicked_index,
            "total_count": self.total_count,
            "siblings": [s.to_dict() for s in self.siblings],
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SiblingsSnapshot":
        """从字典创建"""
        siblings = []
        for sibling_data in data.get("siblings", []):
            if isinstance(sibling_data, dict):
                siblings.append(SiblingElement.from_dict(sibling_data))
            elif isinstance(sibling_data, SiblingElement):
                siblings.append(sibling_data)

        return cls(
            container_selector=data.get("container_selector"),
            item_selector=data.get("item_selector"),
            list_type=data.get("list_type"),
            structure_similarity=data.get("structure_similarity", 0.0),
            is_homogeneous=data.get("is_homogeneous", False),
            clicked_index=data.get("clicked_index", -1),
            total_count=data.get("total_count", 0),
            siblings=siblings,
            timestamp=data.get("timestamp", 0.0),
        )


@dataclass
class NetworkRequestDetail(NetworkRequest):
    """增强的网络请求（包含响应体）"""

    response_body_parsed: Optional[Dict[str, Any]] = None  # 解析后的 JSON
    is_json_response: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = super().to_dict()
        data.update(
            {
                "response_body_parsed": self.response_body_parsed,
                "is_json_response": self.is_json_response,
            }
        )
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NetworkRequestDetail":
        """从字典创建"""
        # 先创建 NetworkRequest
        base_request = NetworkRequest.from_dict(data)

        return cls(
            url=base_request.url,
            method=base_request.method,
            request_headers=base_request.request_headers,
            request_body=base_request.request_body,
            response_status=base_request.response_status,
            response_headers=base_request.response_headers,
            response_body=base_request.response_body,
            timestamp=base_request.timestamp,
            duration=base_request.duration,
            response_body_parsed=data.get("response_body_parsed"),
            is_json_response=data.get("is_json_response", False),
        )


@dataclass
class EnhancedAction(Action):
    """增强的操作类，继承自 Action"""

    # 新增字段
    dom_tree_snapshot: Optional[Dict[str, Any]] = None  # 完整 DOM 树快照
    visual_features: Optional[VisualFeatures] = None  # 视觉特征
    siblings_snapshot: Optional[SiblingsSnapshot] = None  # 兄弟元素快照
    network_requests_detail: Optional[List[NetworkRequestDetail]] = None  # 增强的网络请求

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = super().to_dict()

        # 添加新字段
        if self.dom_tree_snapshot:
            data["dom_tree_snapshot"] = self.dom_tree_snapshot

        if self.visual_features:
            data["visual_features"] = self.visual_features.to_dict()

        if self.siblings_snapshot:
            data["siblings_snapshot"] = self.siblings_snapshot.to_dict()

        if self.network_requests_detail:
            data["network_requests_detail"] = [
                req.to_dict() for req in self.network_requests_detail
            ]

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnhancedAction":
        """从字典创建"""
        # 先创建 Action 基类
        action = Action.from_dict(data)

        # 解析视觉特征
        visual_features = None
        if data.get("visual_features"):
            visual_features = VisualFeatures.from_dict(data["visual_features"])

        # 解析兄弟元素快照
        siblings_snapshot = None
        if data.get("siblings_snapshot"):
            siblings_snapshot = SiblingsSnapshot.from_dict(data["siblings_snapshot"])

        # 解析增强的网络请求
        network_requests_detail = None
        if data.get("network_requests_detail"):
            network_requests_detail = [
                NetworkRequestDetail.from_dict(req) for req in data["network_requests_detail"]
            ]

        return cls(
            action_type=action.action_type,
            recording_mode=action.recording_mode,
            app_name=action.app_name,
            process_name=action.process_name,
            app_path=action.app_path,
            process_id=action.process_id,
            window_title=action.window_title,
            parameters=action.parameters,
            screenshot_before=action.screenshot_before,
            screenshot_after=action.screenshot_after,
            url=action.url,
            dom_element=action.dom_element,
            network_requests=action.network_requests,
            timestamp=action.timestamp,
            dom_tree_snapshot=data.get("dom_tree_snapshot"),
            visual_features=visual_features,
            siblings_snapshot=siblings_snapshot,
            network_requests_detail=network_requests_detail,
        )

    @classmethod
    def from_action(cls, action: Action) -> "EnhancedAction":
        """从 Action 转换为 EnhancedAction"""
        return cls(
            action_type=action.action_type,
            recording_mode=action.recording_mode,
            app_name=action.app_name,
            process_name=action.process_name,
            app_path=action.app_path,
            process_id=action.process_id,
            window_title=action.window_title,
            parameters=action.parameters,
            screenshot_before=action.screenshot_before,
            screenshot_after=action.screenshot_after,
            url=action.url,
            dom_element=action.dom_element,
            network_requests=action.network_requests,
            timestamp=action.timestamp,
        )

"""
视频录制模块

使用OpenCV录制屏幕视频
"""

import cv2
import numpy as np
import logging
from pathlib import Path
from typing import Optional
import mss

logger = logging.getLogger(__name__)


class VideoRecorder:
    """视频录制器"""

    def __init__(self, output_path: Path, fps: int = 15, quality: int = 85):
        """
        初始化视频录制器

        Args:
            output_path: 输出视频文件路径
            fps: 帧率（默认15）
            quality: 视频质量（1-100，默认85）
        """
        self.output_path = Path(output_path)
        self.fps = fps
        self.quality = quality
        self.writer: Optional[cv2.VideoWriter] = None
        self.sct: Optional[mss.mss] = None  # 将在record_frame中创建，确保线程安全
        self.width: Optional[int] = None
        self.height: Optional[int] = None
        self._is_recording = False

    def start(self, width: int, height: int):
        """
        开始录制

        Args:
            width: 视频宽度
            height: 视频高度
        """
        if self._is_recording:
            logger.warning("视频录制已在进行中")
            return

        self.width = width
        self.height = height

        # 确保输出目录存在
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        # 使用H.264编码
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")

        try:
            self.writer = cv2.VideoWriter(str(self.output_path), fourcc, self.fps, (width, height))

            if not self.writer.isOpened():
                raise RuntimeError(f"无法打开视频文件: {self.output_path}")

            self._is_recording = True
            logger.info(f"视频录制已启动: {self.output_path} ({width}x{height} @ {self.fps}fps)")
        except Exception as e:
            logger.error(f"启动视频录制失败: {e}")
            raise

    def record_frame(self):
        """录制一帧"""
        if not self._is_recording or not self.writer:
            return

        try:
            # 在线程中创建mss实例（线程安全）
            if self.sct is None:
                self.sct = mss.mss()

            # 捕获屏幕
            monitor = self.sct.monitors[1]  # 主显示器
            screenshot = self.sct.grab(monitor)

            # 转换为numpy数组
            frame = np.array(screenshot)

            # 转换颜色格式：BGRA -> BGR
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

            # 调整大小（如果需要）
            if frame.shape[1] != self.width or frame.shape[0] != self.height:
                frame = cv2.resize(frame, (self.width, self.height))

            # 写入帧
            self.writer.write(frame)
        except Exception as e:
            logger.error(f"录制帧失败: {e}")
            # 发生错误时重置sct，下次尝试重新创建
            if self.sct:
                try:
                    self.sct.close()
                except Exception:
                    pass
                self.sct = None

    def stop(self):
        """停止录制"""
        if not self._is_recording:
            return

        self._is_recording = False

        if self.writer:
            self.writer.release()
            self.writer = None

        # 不在这里关闭sct，因为它是在录制线程中创建的
        # 线程结束时会自动清理，或者让线程自己清理
        # 如果需要清理，应该在录制线程中进行

        logger.info(f"视频录制已停止: {self.output_path}")

    def is_recording(self) -> bool:
        """检查是否正在录制"""
        return self._is_recording

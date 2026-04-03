# ⚠️ TODO: 图像定位正在开发中
# 图像匹配模块 - 多层次定位的兜底方案
# 定位策略：DOM/UI Automation → 坐标定位 → 图像识别定位
# 当前尚未集成到主工作流中

"""
图像匹配模块

用于图像识别定位中的模板匹配
"""

import logging

logger = logging.getLogger(__name__)


class ImageMatcher:
    """图像匹配器"""

    def __init__(self):
        """初始化图像匹配器"""
        try:
            import cv2
            import numpy as np

            self.cv2 = cv2
            self.np = np
            self._cv2_available = True
        except ImportError:
            logger.warning("OpenCV不可用，图像匹配功能受限")
            self._cv2_available = False


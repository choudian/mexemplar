# ⚠️ TODO: 图像定位正在开发中
# 图像匹配模块 - 多层次定位的兜底方案
# 定位策略：DOM/UI Automation → 坐标定位 → 图像识别定位
# 当前尚未集成到主工作流中

"""
图像匹配模块

用于图像识别定位中的模板匹配
"""

import logging
from typing import Optional, Tuple
import base64
import io

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

    def match_template(
        self, screenshot_base64: str, template_base64: str, threshold: float = 0.8
    ) -> Optional[Tuple[int, int]]:
        """
        在截图中匹配模板图片

        Args:
            screenshot_base64: 屏幕截图（base64编码）
            template_base64: 模板图片（base64编码）
            threshold: 匹配阈值（0-1）

        Returns:
            匹配位置 (x, y)，如果未匹配则返回None
        """
        if not self._cv2_available:
            return None

        try:
            from PIL import Image

            # 解码截图
            screenshot_data = base64.b64decode(screenshot_base64)
            screenshot_img = Image.open(io.BytesIO(screenshot_data))
            screenshot_array = self.np.array(screenshot_img)

            # 如果截图是RGBA，转换为RGB
            if len(screenshot_array.shape) == 3 and screenshot_array.shape[2] == 4:
                screenshot_array = self.cv2.cvtColor(screenshot_array, self.cv2.COLOR_RGBA2RGB)
            elif len(screenshot_array.shape) == 2:
                screenshot_array = self.cv2.cvtColor(screenshot_array, self.cv2.COLOR_GRAY2RGB)

            # 解码模板
            template_data = base64.b64decode(template_base64)
            template_img = Image.open(io.BytesIO(template_data))
            template_array = self.np.array(template_img)

            # 如果模板是RGBA，转换为RGB
            if len(template_array.shape) == 3 and template_array.shape[2] == 4:
                template_array = self.cv2.cvtColor(template_array, self.cv2.COLOR_RGBA2RGB)
            elif len(template_array.shape) == 2:
                template_array = self.cv2.cvtColor(template_array, self.cv2.COLOR_GRAY2RGB)

            # 模板匹配
            result = self.cv2.matchTemplate(
                screenshot_array, template_array, self.cv2.TM_CCOEFF_NORMED
            )
            min_val, max_val, min_loc, max_loc = self.cv2.minMaxLoc(result)

            # 检查匹配度
            if max_val >= threshold:
                # 返回匹配位置的中心点
                x = max_loc[0] + template_array.shape[1] // 2
                y = max_loc[1] + template_array.shape[0] // 2
                return (x, y)
            else:
                logger.debug(f"模板匹配度不足: {max_val:.2f} < {threshold}")
                return None

        except Exception as e:
            logger.error(f"图像匹配失败: {e}")
            return None

    def extract_region(
        self, screenshot_base64: str, x: int, y: int, width: int = 100, height: int = 100
    ) -> Optional[str]:
        """
        从截图中提取指定区域

        Args:
            screenshot_base64: 屏幕截图（base64编码）
            x: 区域中心X坐标
            y: 区域中心Y坐标
            width: 区域宽度
            height: 区域高度

        Returns:
            提取的区域图片（base64编码）
        """
        if not self._cv2_available:
            return None

        try:
            from PIL import Image

            # 解码截图
            screenshot_data = base64.b64decode(screenshot_base64)
            screenshot_img = Image.open(io.BytesIO(screenshot_data))
            screenshot_array = self.np.array(screenshot_img)

            # 计算区域边界
            left = max(0, x - width // 2)
            top = max(0, y - height // 2)
            right = min(screenshot_array.shape[1], x + width // 2)
            bottom = min(screenshot_array.shape[0], y + height // 2)

            # 提取区域
            region = screenshot_array[top:bottom, left:right]

            # 转换为PIL图片
            region_img = Image.fromarray(region)

            # 转换为base64
            img_bytes = io.BytesIO()
            region_img.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            region_base64 = base64.b64encode(img_bytes.read()).decode("utf-8")

            return region_base64

        except Exception as e:
            logger.error(f"提取区域失败: {e}")
            return None

"""
多层次定位器

实现三层定位策略：DOM/UI Automation → 坐标定位 → 图像识别
"""

import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class LocatorInfo:
    """定位信息"""

    # 第一层：DOM/UI Automation定位
    dom_xpath: Optional[str] = None
    dom_css_selector: Optional[str] = None
    dom_element_id: Optional[str] = None
    dom_text_content: Optional[str] = None

    # UI Automation定位
    automation_id: Optional[str] = None
    control_type: Optional[str] = None
    window_class: Optional[str] = None

    # 第二层：坐标定位
    viewport_x: Optional[int] = None
    viewport_y: Optional[int] = None
    scroll_top: Optional[int] = None
    scroll_left: Optional[int] = None

    # 第三层：图像识别定位
    screen_x: Optional[int] = None
    screen_y: Optional[int] = None
    screenshot_base64: Optional[str] = None
    ocr_text: Optional[str] = None

    # 上下文信息
    context_url: Optional[str] = None
    window_title: Optional[str] = None
    app_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "dom": {
                "xpath": self.dom_xpath,
                "css_selector": self.dom_css_selector,
                "element_id": self.dom_element_id,
                "text_content": self.dom_text_content,
            },
            "automation": {
                "automation_id": self.automation_id,
                "control_type": self.control_type,
                "window_class": self.window_class,
            },
            "viewport": {
                "x": self.viewport_x,
                "y": self.viewport_y,
                "scroll_top": self.scroll_top,
                "scroll_left": self.scroll_left,
            },
            "screen": {
                "x": self.screen_x,
                "y": self.screen_y,
                "screenshot_base64": self.screenshot_base64,
                "ocr_text": self.ocr_text,
            },
            "context": {
                "url": self.context_url,
                "window_title": self.window_title,
                "app_name": self.app_name,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocatorInfo":
        """从字典创建"""
        dom = data.get("dom", {})
        automation = data.get("automation", {})
        viewport = data.get("viewport", {})
        screen = data.get("screen", {})
        context = data.get("context", {})

        return cls(
            dom_xpath=dom.get("xpath"),
            dom_css_selector=dom.get("css_selector"),
            dom_element_id=dom.get("element_id"),
            dom_text_content=dom.get("text_content"),
            automation_id=automation.get("automation_id"),
            control_type=automation.get("control_type"),
            window_class=automation.get("window_class"),
            viewport_x=viewport.get("x"),
            viewport_y=viewport.get("y"),
            scroll_top=viewport.get("scroll_top"),
            scroll_left=viewport.get("scroll_left"),
            screen_x=screen.get("x"),
            screen_y=screen.get("y"),
            screenshot_base64=screen.get("screenshot_base64"),
            ocr_text=screen.get("ocr_text"),
            context_url=context.get("url"),
            window_title=context.get("window_title"),
            app_name=context.get("app_name"),
        )


@dataclass
class LocatorResult:
    """定位结果"""

    success: bool
    element: Any = None  # 定位到的元素（类型取决于具体实现）
    method: Optional[str] = None  # 使用的定位方法
    coordinates: Optional[Tuple[int, int]] = None  # 最终坐标
    error_message: Optional[str] = None


class DOMLocator:
    """DOM定位器（浏览器）"""

    def __init__(self, page=None):
        """
        初始化DOM定位器

        Args:
            page: Playwright Page对象
        """
        self.page = page

    def locate(self, locator_info: LocatorInfo) -> LocatorResult:
        """
        使用DOM定位元素

        Args:
            locator_info: 定位信息

        Returns:
            定位结果
        """
        if not self.page:
            return LocatorResult(success=False, error_message="Page对象未设置")

        try:
            element = None

            # 优先级1: XPath
            if locator_info.dom_xpath:
                try:
                    element = self.page.locator(f"xpath={locator_info.dom_xpath}")
                    if element.count() > 0:
                        return LocatorResult(success=True, element=element, method="xpath")
                except Exception as e:
                    logger.debug(f"XPath定位失败: {e}")

            # 优先级2: CSS Selector
            if locator_info.dom_css_selector:
                try:
                    element = self.page.locator(locator_info.dom_css_selector)
                    if element.count() > 0:
                        return LocatorResult(success=True, element=element, method="css_selector")
                except Exception as e:
                    logger.debug(f"CSS Selector定位失败: {e}")

            # 优先级3: Element ID
            if locator_info.dom_element_id:
                try:
                    element = self.page.locator(f"#{locator_info.dom_element_id}")
                    if element.count() > 0:
                        return LocatorResult(success=True, element=element, method="element_id")
                except Exception as e:
                    logger.debug(f"Element ID定位失败: {e}")

            # 优先级4: 文本内容
            if locator_info.dom_text_content:
                try:
                    element = self.page.get_by_text(locator_info.dom_text_content, exact=True)
                    if element.count() > 0:
                        return LocatorResult(success=True, element=element, method="text_content")
                except Exception as e:
                    logger.debug(f"文本内容定位失败: {e}")

            return LocatorResult(success=False, error_message="所有DOM定位方法均失败")

        except Exception as e:
            logger.error(f"DOM定位异常: {e}")
            return LocatorResult(success=False, error_message=str(e))


class UIAutomationLocator:
    """UI Automation定位器（桌面应用）"""

    def __init__(self, window=None):
        """
        初始化UI Automation定位器

        Args:
            window: pywinauto窗口对象
        """
        self.window = window

    def locate(self, locator_info: LocatorInfo) -> LocatorResult:
        """
        使用UI Automation定位元素

        Args:
            locator_info: 定位信息

        Returns:
            定位结果
        """
        if not self.window:
            return LocatorResult(success=False, error_message="Window对象未设置")

        try:
            element = None

            # 优先级1: Automation ID
            if locator_info.automation_id:
                try:
                    element = self.window.child_window(automation_id=locator_info.automation_id)
                    if element.exists():
                        return LocatorResult(success=True, element=element, method="automation_id")
                except Exception as e:
                    logger.debug(f"Automation ID定位失败: {e}")

            # 优先级2: Control Type + Automation ID
            if locator_info.control_type and locator_info.automation_id:
                try:
                    element = self.window.child_window(
                        control_type=locator_info.control_type,
                        automation_id=locator_info.automation_id,
                    )
                    if element.exists():
                        return LocatorResult(
                            success=True, element=element, method="control_type_automation_id"
                        )
                except Exception as e:
                    logger.debug(f"Control Type定位失败: {e}")

            return LocatorResult(success=False, error_message="所有UI Automation定位方法均失败")

        except Exception as e:
            logger.error(f"UI Automation定位异常: {e}")
            return LocatorResult(success=False, error_message=str(e))


class CoordinateLocator:
    """坐标定位器"""

    def __init__(self, page=None, window=None):
        """
        初始化坐标定位器

        Args:
            page: Playwright Page对象（浏览器）
            window: pywinauto窗口对象（桌面应用）
        """
        self.page = page
        self.window = window

    def locate(self, locator_info: LocatorInfo) -> LocatorResult:
        """
        使用坐标定位元素

        Args:
            locator_info: 定位信息

        Returns:
            定位结果
        """
        if not locator_info.viewport_x or not locator_info.viewport_y:
            return LocatorResult(success=False, error_message="坐标信息不完整")

        try:
            x = locator_info.viewport_x
            y = locator_info.viewport_y

            # 如果有滚动偏移，需要调整坐标
            if locator_info.scroll_top:
                y += locator_info.scroll_top
            if locator_info.scroll_left:
                x += locator_info.scroll_left

            coordinates = (x, y)

            # 对于浏览器，可以直接返回坐标
            # 对于桌面应用，也可以返回坐标
            # 实际执行时会使用这些坐标进行点击

            return LocatorResult(
                success=True,
                element=None,  # 坐标定位不返回元素对象
                method="coordinate",
                coordinates=coordinates,
            )

        except Exception as e:
            logger.error(f"坐标定位异常: {e}")
            return LocatorResult(success=False, error_message=str(e))


class ImageLocator:
    """图像识别定位器"""

    def __init__(self):
        """初始化图像识别定位器"""
        try:
            import cv2
            import numpy as np

            self.cv2 = cv2
            self.np = np
            self._cv2_available = True
        except ImportError:
            logger.warning("OpenCV不可用，图像识别定位功能受限")
            self._cv2_available = False

    def locate(self, locator_info: LocatorInfo) -> LocatorResult:
        """
        使用图像识别定位元素

        Args:
            locator_info: 定位信息

        Returns:
            定位结果
        """
        if not self._cv2_available:
            return LocatorResult(success=False, error_message="OpenCV不可用")

        if not locator_info.screenshot_base64:
            return LocatorResult(success=False, error_message="截图数据不存在")

        try:
            import base64

            # 解码base64图片（用于后续模板匹配）
            _image_data = base64.b64decode(locator_info.screenshot_base64)

            # 这里需要在实际屏幕截图中查找模板图片
            # 这是一个简化的实现，实际需要：
            # 1. 捕获当前屏幕截图
            # 2. 使用模板匹配算法（如cv2.matchTemplate）
            # 3. 找到匹配位置

            # 如果有绝对坐标，直接使用
            if locator_info.screen_x and locator_info.screen_y:
                coordinates = (locator_info.screen_x, locator_info.screen_y)
                return LocatorResult(
                    success=True,
                    element=None,
                    method="image_screen_coordinate",
                    coordinates=coordinates,
                )

            # 否则需要图像匹配（这里只是占位，实际实现需要更多代码）
            return LocatorResult(success=False, error_message="图像匹配功能待实现")

        except Exception as e:
            logger.error(f"图像识别定位异常: {e}")
            return LocatorResult(success=False, error_message=str(e))


class MultiLayerLocator:
    """多层次定位器（主类）"""

    def __init__(self, page=None, window=None):
        """
        初始化多层次定位器

        Args:
            page: Playwright Page对象（浏览器）
            window: pywinauto窗口对象（桌面应用）
        """
        self.dom_locator = DOMLocator(page) if page else None
        self.ui_locator = UIAutomationLocator(window) if window else None
        self.coordinate_locator = CoordinateLocator(page, window)
        self.image_locator = ImageLocator()

    def locate(self, locator_info: LocatorInfo) -> LocatorResult:
        """
        多层次定位（智能降级）

        Args:
            locator_info: 定位信息

        Returns:
            定位结果
        """
        # 策略1：DOM/UI Automation定位（优先级最高）
        if self.dom_locator:
            result = self.dom_locator.locate(locator_info)
            if result.success:
                logger.debug(f"DOM定位成功，方法: {result.method}")
                return result

        if self.ui_locator:
            result = self.ui_locator.locate(locator_info)
            if result.success:
                logger.debug(f"UI Automation定位成功，方法: {result.method}")
                return result

        # 策略2：坐标定位
        result = self.coordinate_locator.locate(locator_info)
        if result.success:
            logger.debug("坐标定位成功")
            return result

        # 策略3：图像识别定位（兜底方案）
        result = self.image_locator.locate(locator_info)
        if result.success:
            logger.debug(f"图像识别定位成功，方法: {result.method}")
            return result

        # 所有策略都失败
        logger.warning("所有定位策略均失败")
        return LocatorResult(
            success=False, error_message="所有定位策略均失败，请重新录制或手动调整定位信息"
        )

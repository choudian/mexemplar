# ⚠️ TODO: 执行引擎正在开发中
# 操作执行器 - 执行单个操作步骤

"""
操作执行器

本模块负责执行单个操作步骤，支持多种浏览器和桌面操作类型。
"""

import asyncio
from typing import Any, Dict, Optional
from datetime import datetime

from .execution_context import ExecutionContext, StepResult
from .retry_handler import RetryHandler
from ..drivers.locator.multi_layer_locator import MultiLayerLocator, LocatorInfo


class ActionExecutor:
    """
    操作执行器

    负责执行单个操作步骤，包括元素定位和操作执行。
    支持的操作类型：navigate, click, fill, select, scroll, wait, extract 等
    """

    def __init__(self, context: ExecutionContext):
        """
        初始化操作执行器

        Args:
            context: 执行上下文
        """
        self.context = context
        self.locator = MultiLayerLocator(page=context.browser_page, window=context.desktop_window)

    async def execute(self, step: Dict[str, Any]) -> StepResult:
        """
        执行单个步骤

        Args:
            step: 步骤定义（已解析参数）

        Returns:
            StepResult 执行结果
        """
        step_name = step.get("step_name", f'step_{step.get("step_number", "?")}')
        step_number = step.get("step_number", 0)
        action_type = step.get("action_type", "")
        description = step.get("description", "")

        started_at = datetime.now()
        self.context.log(f"开始执行步骤 {step_number}: {description or step_name} ({action_type})")

        # 获取重试配置
        retry_config = RetryHandler.config_from_step(step)
        retry_handler = RetryHandler(retry_config)

        # 执行操作（带重试）
        retry_result = await retry_handler.execute(self._execute_action, step)

        finished_at = datetime.now()

        if retry_result.success:
            result = StepResult(
                step_name=step_name,
                step_number=step_number,
                success=True,
                result=retry_result.result,
                started_at=started_at,
                finished_at=finished_at,
                retry_count=retry_result.attempts - 1,
            )
            self.context.log(f"步骤 {step_name} 执行成功（尝试 {retry_result.attempts} 次）")
        else:
            result = StepResult(
                step_name=step_name,
                step_number=step_number,
                success=False,
                error_message=str(retry_result.error),
                started_at=started_at,
                finished_at=finished_at,
                retry_count=retry_result.attempts - 1,
            )
            self.context.log(
                f"步骤 {step_name} 执行失败（尝试 {retry_result.attempts} 次）: {retry_result.error}"
            )

        return result

    async def _execute_action(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行具体操作（内部方法，会被重试）

        Args:
            step: 步骤定义（已解析参数）

        Returns:
            操作结果

        Raises:
            Exception: 操作失败时抛出异常
        """
        action_type = step.get("action_type", "")
        parameters = step.get("parameters", {})

        # 根据操作类型分发
        if action_type == "navigate" or action_type == "browser_navigate":
            return await self._navigate(parameters)
        elif action_type == "click" or action_type == "browser_click":
            return await self._click(step)
        elif action_type == "fill" or action_type == "browser_fill":
            return await self._fill(step)
        elif action_type == "select" or action_type == "browser_select":
            return await self._select(step)
        elif action_type == "scroll" or action_type == "browser_scroll":
            return await self._scroll(parameters)
        elif action_type == "wait" or action_type == "browser_wait":
            return await self._wait(parameters)
        elif action_type == "extract" or action_type == "browser_extract":
            return await self._extract(step)
        else:
            raise ValueError(f"不支持的操作类型: {action_type}")

    async def _navigate(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        页面导航

        Args:
            parameters: 包含 url 参数

        Returns:
            {"url": 实际导航到的 URL}
        """
        if not self.context.browser_page:
            raise RuntimeError("浏览器页面未初始化")

        url = parameters.get("url")
        if not url:
            raise ValueError("缺少 url 参数")

        await self.context.browser_page.goto(url)

        return {"url": url}

    async def _click(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        点击元素

        Args:
            step: 步骤定义，包含 locator_info

        Returns:
            {"clicked": True}
        """
        if not self.context.browser_page:
            raise RuntimeError("浏览器页面未初始化")

        # 构建 LocatorInfo
        locator_info = self._build_locator_info(step)
        if not locator_info:
            raise ValueError("缺少定位信息")

        # 定位元素
        result = self.locator.locate(locator_info)
        if not result.success:
            raise RuntimeError(f"元素定位失败: {result.error_message}")

        # 执行点击
        if result.element:
            # 使用定位到的元素
            await result.element.click()
        elif result.coordinates:
            # 使用坐标点击
            x, y = result.coordinates
            await self.context.browser_page.mouse.click(x, y)
        else:
            raise RuntimeError("无法执行点击操作：无元素对象或坐标")

        return {"clicked": True}

    async def _fill(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        填充输入框

        Args:
            step: 步骤定义，包含 locator_info 和 parameters.value

        Returns:
            {"filled": True, "value": 输入的值}
        """
        if not self.context.browser_page:
            raise RuntimeError("浏览器页面未初始化")

        # 构建 LocatorInfo
        locator_info = self._build_locator_info(step)
        if not locator_info:
            raise ValueError("缺少定位信息")

        # 定位元素
        result = self.locator.locate(locator_info)
        if not result.success:
            raise RuntimeError(f"元素定位失败: {result.error_message}")

        # 获取要输入的值
        parameters = step.get("parameters", {})
        value = parameters.get("value")
        if value is None:
            raise ValueError("缺少 value 参数")

        # 执行填充
        if result.element:
            # 先清空再填充
            await result.element.fill(value)
        else:
            raise RuntimeError("无法执行填充操作：无元素对象")

        return {"filled": True, "value": value}

    async def _select(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        选择下拉选项

        Args:
            step: 步骤定义

        Returns:
            {"selected": True, "value": 选中的值}
        """
        if not self.context.browser_page:
            raise RuntimeError("浏览器页面未初始化")

        # 构建 LocatorInfo
        locator_info = self._build_locator_info(step)
        if not locator_info:
            raise ValueError("缺少定位信息")

        # 定位元素
        result = self.locator.locate(locator_info)
        if not result.success:
            raise RuntimeError(f"元素定位失败: {result.error_message}")

        # 获取要选择的值
        parameters = step.get("parameters", {})
        value = parameters.get("value")
        if value is None:
            raise ValueError("缺少 value 参数")

        # 执行选择
        if result.element:
            await result.element.select_option(value=value)
        else:
            raise RuntimeError("无法执行选择操作：无元素对象")

        return {"selected": True, "value": value}

    async def _scroll(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        滚动页面

        Args:
            parameters: 包含 direction（up/down）或 pixels 的参数

        Returns:
            {"scrolled": True}
        """
        if not self.context.browser_page:
            raise RuntimeError("浏览器页面未初始化")

        direction = parameters.get("direction", "down")
        pixels = parameters.get("pixels", 500)

        if direction == "up":
            pixels = -pixels

        await self.context.browser_page.evaluate(f"window.scrollBy(0, {pixels})")

        return {"scrolled": True, "pixels": pixels}

    async def _wait(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        等待

        Args:
            parameters: 包含 duration（毫秒）的参数

        Returns:
            {"waited": True, "duration": 等待时长}
        """
        duration = parameters.get("duration", 1000)
        duration_seconds = duration / 1000

        await asyncio.sleep(duration_seconds)

        return {"waited": True, "duration": duration}

    async def _extract(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """
        提取数据

        Args:
            step: 步骤定义

        Returns:
            提取的数据（根据 extract_type 返回不同内容）
        """
        if not self.context.browser_page:
            raise RuntimeError("浏览器页面未初始化")

        parameters = step.get("parameters", {})
        extract_type = parameters.get("extract_type", "text")

        # 构建 LocatorInfo
        locator_info = self._build_locator_info(step)

        if not locator_info:
            # 提取页面级数据
            if extract_type == "url":
                return {"value": self.context.browser_page.url}
            elif extract_type == "title":
                return {"value": await self.context.browser_page.title()}
            else:
                raise ValueError(f"不支持的页面级提取类型: {extract_type}")

        # 提取元素级数据
        result = self.locator.locate(locator_info)
        if not result.success:
            raise RuntimeError(f"元素定位失败: {result.error_message}")

        if not result.element:
            raise RuntimeError("无法提取数据：无元素对象")

        if extract_type == "text":
            value = await result.element.inner_text()
        elif extract_type == "html":
            value = await result.element.inner_html()
        elif extract_type == "attribute":
            attr_name = parameters.get("attribute")
            if not attr_name:
                raise ValueError("缺少 attribute 参数")
            value = await result.element.get_attribute(attr_name)
        else:
            raise ValueError(f"不支持的提取类型: {extract_type}")

        return {"value": value, "extract_type": extract_type}

    def _build_locator_info(self, step: Dict[str, Any]) -> Optional[LocatorInfo]:
        """
        从步骤定义中构建 LocatorInfo

        Args:
            step: 步骤定义

        Returns:
            LocatorInfo 对象，如果无定位信息则返回 None
        """
        locator_info_data = step.get("locator_info")
        if not locator_info_data:
            return None

        # 处理不同的数据格式
        if isinstance(locator_info_data, dict):
            # 检查是否已经是我们的标准格式
            if "dom" in locator_info_data:
                return LocatorInfo.from_dict(locator_info_data)

            # 否则尝试从其他格式转换
            return self._convert_to_locator_info(locator_info_data)

        return None

    def _convert_to_locator_info(self, data: Dict[str, Any]) -> Optional[LocatorInfo]:
        """
        将各种格式的定位信息转换为 LocatorInfo

        Args:
            data: 定位信息数据

        Returns:
            LocatorInfo 对象
        """
        locator_type = data.get("type", "")
        value = data.get("value", "")

        if locator_type == "xpath" or locator_type == "css_selector":
            # DOM 定位
            if locator_type == "xpath":
                return LocatorInfo(dom_xpath=value)
            else:
                return LocatorInfo(dom_css_selector=value)

        elif locator_type == "coordinate":
            # 坐标定位
            return LocatorInfo(viewport_x=data.get("x"), viewport_y=data.get("y"))

        elif locator_type == "image":
            # 图像识别
            return LocatorInfo(
                screenshot_base64=value, screen_x=data.get("x"), screen_y=data.get("y")
            )

        else:
            # 尝试从 parameters 中提取
            selector = data.get("selector")
            if selector:
                if selector.startswith("//") or selector.startswith("("):
                    return LocatorInfo(dom_xpath=selector)
                else:
                    return LocatorInfo(dom_css_selector=selector)

        return None

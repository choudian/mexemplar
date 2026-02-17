"""
视觉理解模块

使用 Claude Vision API 分析截图和界面
"""

import base64
from typing import List, Dict, Any, Optional
from pathlib import Path
import logging

from anthropic import Anthropic

from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)


class VisionAnalyzer:
    """视觉分析器 - 使用 Claude Vision API"""

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化视觉分析器

        Args:
            api_key: Anthropic API 密钥，如果不提供则从配置管理器获取
        """
        if api_key is None:
            api_key = get_unified_config().get_ai_api_key()

        if not api_key:
            raise ValueError("Anthropic API 密钥未设置，请先配置 API 密钥")

        self.client = Anthropic(api_key=api_key)
        # ⭐ 从统一配置读取模型
        self.model = get_unified_config().get_ai_vision_model()

    def analyze_screenshot(
        self, image_path: str, task: str = "describe", context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        分析单个截图

        Args:
            image_path: 截图文件路径
            task: 分析任务类型
                - "describe": 描述界面内容
                - "elements": 识别可交互元素
                - "intent": 理解用户意图
            context: 额外上下文信息

        Returns:
            Dict[str, Any]: 分析结果
        """
        if not Path(image_path).exists():
            logger.error(f"截图文件不存在: {image_path}")
            return {}

        # 读取并编码图片
        image_data = self._encode_image(image_path)

        # 构建提示词
        prompt = self._build_prompt(task, context)

        try:
            # 调用 Claude Vision API
            message = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_data,
                                },
                            },
                        ],
                    }
                ],
            )

            # 解析响应
            response_text = message.content[0].text
            result = self._parse_response(response_text, task)

            logger.info(f"成功分析截图: {image_path}, 任务: {task}")
            return result

        except Exception as e:
            logger.error(f"分析截图失败: {image_path}, 错误: {e}")
            return {}

    def analyze_screenshots_sequence(
        self, image_paths: List[str], context: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        分析截图序列，理解操作流程

        Args:
            image_paths: 截图文件路径列表（按时间顺序）
            context: 额外上下文信息

        Returns:
            Dict[str, Any]: 分析结果
        """
        if not image_paths:
            logger.warning("没有提供截图路径")
            return {}

        if len(image_paths) > 10:
            logger.warning(f"截图数量过多 ({len(image_paths)})，只分析前10张")
            image_paths = image_paths[:10]

        results = []

        for idx, image_path in enumerate(image_paths):
            logger.info(f"分析截图 {idx + 1}/{len(image_paths)}: {image_path}")

            task_context = f"这是操作序列中的第 {idx + 1} 步"
            if context:
                task_context = f"{context}\n{task_context}"

            result = self.analyze_screenshot(
                image_path=image_path, task="elements", context=task_context
            )

            if result:
                results.append({"step": idx + 1, "image_path": image_path, "analysis": result})

        # 综合分析
        summary = self._summarize_sequence(results)

        return {"individual_results": results, "summary": summary}

    def _encode_image(self, image_path: str) -> str:
        """将图片编码为 base64"""
        with open(image_path, "rb") as f:
            image_data = f.read()
        return base64.b64encode(image_data).decode("utf-8")

    def _build_prompt(self, task: str, context: Optional[str] = None) -> str:
        """构建分析提示词"""
        base_prompt = """你是一个智能 UI 分析助手。请分析这张截图，提供准确的信息。"""

        task_prompts = {
            "describe": """
请详细描述这张截图中的内容：
1. 应用类型（浏览器/桌面应用/系统界面等）
2. 主要界面元素（按钮、输入框、菜单等）
3. 当前界面状态
4. 任何可见的文字内容

请以结构化的方式回答，使用清晰的分类。
""",
            "elements": """
请识别这张截图中所有可交互的元素：
1. 按钮及其标签
2. 输入框及其占位符或标签
3. 链接及其文本
4. 菜单项
5. 其他可点击的元素

对于每个元素，请提供：
- 元素类型
- 可见的文本或标签
- 位置信息（上/下/左/右/中间）
- 推荐的定位方式（如果可见）

请以 JSON 格式返回：
{
  "elements": [
    {
      "type": "button|input|link|menu|other",
      "text": "可见文本",
      "position": "top|bottom|left|right|center",
      "locator_suggestion": "建议的定位方式",
      "confidence": "high|medium|low"
    }
  ],
  "application_type": "浏览器|桌面应用|其他",
  "page_title": "页面或窗口标题",
  "summary": "简要描述"
}
""",
            "intent": """
根据这张截图，分析用户可能想要完成的操作：
1. 当前界面的主要用途
2. 用户可能想要执行的操作
3. 下一步可能的动作

请提供清晰的分析。
""",
        }

        prompt = task_prompts.get(task, task_prompts["describe"])

        if context:
            prompt = f"{context}\n\n{prompt}"

        return f"{base_prompt}\n\n{prompt}"

    def _parse_response(self, response_text: str, task: str) -> Dict[str, Any]:
        """解析 API 响应"""
        import json
        import re

        result = {"raw_response": response_text, "task": task}

        # 尝试提取 JSON
        if task == "elements":
            # 查找 JSON 代码块
            json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
            if json_match:
                try:
                    json_data = json.loads(json_match.group(1))
                    result["parsed"] = json_data
                except json.JSONDecodeError:
                    # 如果解析失败，尝试直接解析整个响应
                    try:
                        json_data = json.loads(response_text)
                        result["parsed"] = json_data
                    except json.JSONDecodeError:
                        logger.warning("无法解析 JSON 响应")
                        result["parsed"] = None
            else:
                result["parsed"] = None

        return result

    def _summarize_sequence(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """总结截图序列的分析结果"""
        if not results:
            return {}

        summary = {
            "total_steps": len(results),
            "detected_elements": [],
            "application_types": set(),
            "possible_workflow": [],
        }

        for result in results:
            analysis = result.get("analysis", {})
            parsed = analysis.get("parsed")

            if parsed:
                # 收集元素
                elements = parsed.get("elements", [])
                summary["detected_elements"].extend(elements)

                # 收集应用类型
                app_type = parsed.get("application_type")
                if app_type:
                    summary["application_types"].add(app_type)

        # 转换 set 为 list
        summary["application_types"] = list(summary["application_types"])

        # 统计元素类型
        element_types = {}
        for element in summary["detected_elements"]:
            elem_type = element.get("type", "unknown")
            element_types[elem_type] = element_types.get(elem_type, 0) + 1

        summary["element_type_counts"] = element_types

        return summary

    def close(self) -> None:
        """关闭客户端"""
        if self.client:
            self.client = None

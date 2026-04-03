"""
视觉理解模块

使用 Claude Vision API 分析截图和界面
"""

import base64
from typing import Dict, Any, Optional
from pathlib import Path
import logging

from anthropic import Anthropic

from src.data.unified_config import get_unified_config
from src.utils.llm_helpers import extract_json_from_response

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
        result = {"raw_response": response_text, "task": task}

        if task == "elements":
            try:
                result["parsed"] = extract_json_from_response(
                    response_text, require_dict=False, log_prefix="Vision"
                )
            except ValueError:
                logger.warning("无法解析 JSON 响应")
                result["parsed"] = None

        return result

    def close(self) -> None:
        """关闭客户端"""
        if self.client:
            self.client = None

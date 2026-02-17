"""
语义理解模块

使用 Claude Sonnet API 进行意图识别、参数提取和工作流分析

架构：统一使用 LangChainLLMClient（与压缩模型一致）
"""

import json
from typing import List, Dict, Any, Optional
import logging

from src.data.unified_config import get_unified_config
from src.recording.recorder import Action
from src.business.ai.llm_client import create_llm_client

logger = logging.getLogger(__name__)


class SemanticAnalyzer:
    """语义分析器 - 使用 Claude Sonnet API"""

    def __init__(self, api_key: Optional[str] = None):
        """
        初始化语义分析器

        Args:
            api_key: API 密钥（可选，优先从配置读取）
        """
        config = get_unified_config()

        # 构建 LLM 客户端配置
        client_config = {
            "provider": config.get_ai_provider(),
            "model": config.get_ai_model(),
            "api_key": api_key or config.get_ai_api_key(),
            "temperature": config.get_ai_temperature(),
            "max_tokens": config.get_ai_max_tokens(),
        }

        # 添加 base_url（如果配置了）
        base_url = config.get_ai_base_url()
        if base_url:
            client_config["base_url"] = base_url

        # 验证 API 密钥
        if not client_config["api_key"]:
            raise ValueError("API 密钥未设置，请先配置 API 密钥")

        # 创建统一的 LangChain 客户端
        self.client = create_llm_client(client_config)
        self.api_key = client_config["api_key"]
        self.model = client_config["model"]
        self.temperature = client_config["temperature"]
        self.max_tokens = client_config["max_tokens"]

        logger.info(f"[语义分析器] 已初始化: {client_config['provider']}/{self.model}")

    def analyze_intent(
        self, actions: List[Action], metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        分析录制数据的意图

        Args:
            actions: 操作序列
            metadata: 预处理元数据

        Returns:
            Dict[str, Any]: 意图分析结果
            {
                'task_name': str,           # 任务名称
                'task_description': str,    # 任务描述
                'task_category': str,       # 任务类别
                'user_intent': str,         # 用户意图
                'confidence': float,        # 置信度
            }
        """
        # 构建操作序列描述
        actions_description = self._describe_actions(actions)

        # 构建提示词
        prompt = self._build_intent_analysis_prompt(actions_description, metadata)

        try:
            # 调用 LLM（使用统一的 LangChain 客户端）
            response_text = self.client.chat(
                prompt=prompt,
                max_tokens=2048,
            )

            result = self._parse_intent_response(response_text)

            logger.info(f"成功分析意图: {result.get('task_name', 'unknown')}")
            return result

        except Exception as e:
            logger.error(f"意图分析失败: {e}")
            return self._get_default_intent()

    def extract_parameters(
        self, actions: List[Action], intent: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        从操作序列中提取参数

        Args:
            actions: 操作序列
            intent: 意图分析结果

        Returns:
            List[Dict[str, Any]]: 参数定义列表
            [
                {
                    'name': str,              # 参数名称
                    'type': str,              # 参数类型
                    'description': str,       # 参数描述
                    'required': bool,         # 是否必填
                    'default_value': Any,     # 默认值
                    'example_value': Any,     # 示例值
                    'source_action_index': int, # 来源操作索引
                }
            ]
        """
        # 构建操作序列描述
        actions_description = self._describe_actions(actions)

        # 构建提示词
        prompt = self._build_parameter_extraction_prompt(actions_description, intent)

        try:
            # 调用 LLM（使用统一的 LangChain 客户端）
            response_text = self.client.chat(
                prompt=prompt,
                max_tokens=4096,
            )

            result = self._parse_parameters_response(response_text)

            logger.info(f"成功提取 {len(result)} 个参数")
            return result

        except Exception as e:
            logger.error(f"参数提取失败: {e}")
            return []

    def generate_workflow(
        self,
        actions: List[Action],
        intent: Optional[Dict[str, Any]] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        vision_analysis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        生成工作流定义

        Args:
            actions: 操作序列
            intent: 意图分析结果
            parameters: 参数定义
            vision_analysis: 视觉分析结果

        Returns:
            Dict[str, Any]: 工作流定义
            {
                'tool_name': str,
                'description': str,
                'parameters': List[Dict],
                'steps': List[Dict],
                'metadata': Dict,
            }
        """
        # 构建完整的上下文
        context = {
            "actions_description": self._describe_actions(actions),
            "intent": intent or {},
            "parameters": parameters or [],
            "vision_analysis": vision_analysis or {},
        }

        # 构建提示词
        prompt = self._build_workflow_generation_prompt(context)

        try:
            # 调用 LLM（使用统一的 LangChain 客户端）
            response_text = self.client.chat(
                prompt=prompt,
                max_tokens=8192,
            )

            result = self._parse_workflow_response(response_text)

            logger.info(f"成功生成工作流: {result.get('tool_name', 'unknown')}")
            return result

        except Exception as e:
            logger.error(f"工作流生成失败: {e}")
            return {}

    def _describe_actions(self, actions: List[Action]) -> str:
        """将操作序列转换为文本描述"""
        if not actions:
            return "没有操作"

        lines = []
        for idx, action in enumerate(actions, 1):
            # 基本操作类型
            action_desc = f"步骤 {idx}: {action.action_type}"
            lines.append(action_desc)

            # 添加关键信息
            if action.url:
                lines.append(f"  URL: {action.url}")
            if action.window_title:
                lines.append(f"  窗口标题: {action.window_title}")
            if action.app_name:
                lines.append(f"  应用: {action.app_name}")

            # 添加参数信息（更详细）
            if action.parameters:
                for key, value in action.parameters.items():
                    if key not in ["x", "y", "button", "offsetX", "offsetY"]:  # 过滤掉坐标信息
                        # 特殊处理一些重要的参数
                        if key == "text":
                            lines.append(f"  输入内容: {value}")
                        elif key == "link" or key == "button":
                            lines.append(f"  点击元素: {value}")
                        elif key == "section":
                            lines.append(f"  浏览章节: {value}")
                        elif key == "scroll_position":
                            lines.append(f"  滚动位置: {value}")
                        else:
                            lines.append(f"  {key}: {value}")

            # 添加 DOM 元素信息（浏览器模式）
            if action.dom_element:
                dom = action.dom_element
                if dom.get("text"):
                    lines.append(f"  元素文本: {dom['text']}")
                if dom.get("tag_name"):
                    lines.append(f"  元素标签: {dom['tag_name']}")
                if dom.get("id"):
                    lines.append(f"  元素ID: {dom['id']}")
                if dom.get("class"):
                    lines.append(f"  元素类名: {dom['class']}")

            # 添加网络请求信息
            if action.network_requests:
                lines.append(f"  关联网络请求: {len(action.network_requests)} 个")
                # 如果有关键的 API 请求，显示 URL
                for req in action.network_requests[:3]:  # 只显示前3个
                    if hasattr(req, "url") and req.url:
                        lines.append(f"    - {getattr(req, 'method', 'GET')}: {req.url}")

        return "\n".join(lines)

    def _build_intent_analysis_prompt(
        self, actions_description: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """构建意图分析提示词"""
        prompt = """你是一个智能工作流分析专家。请详细分析用户的操作序列，识别任务意图。

【重要】你必须仔细分析每一步操作，提取出所有的关键细节。

操作序列：
```
{actions_description}
```

"""

        if metadata:
            prompt += """
额外信息：
```json
{metadata_json}
```

"""

        prompt += """
请以 JSON 格式返回分析结果：
```json
{{
  "task_name": "简洁的任务名称（2-6个字）",
  "task_description": "超详细的任务描述，必须包含所有关键操作细节",
  "task_category": "任务类别（数据采集、表单填写、自动化测试、数据抓取等）",
  "user_intent": "用户想要达成的目标（一句话描述）",
  "confidence": 0.9,
  "keywords": ["关键词1", "关键词2"]
}}
```

【核心要求 - 必须严格遵守】

**1. task_description（任务描述）- 最重要**

必须包含以下完整信息：
- **每一步的具体操作**：不要遗漏任何操作
  - 输入了什么内容（保留输入值）
  - 点击了什么元素（保留元素文本或标签）
  - 选择了什么选项（保留选项值）
  - 滚动了到哪里（滚动位置或目标元素）

- **页面跳转的完整路径**：
  - 从哪个 URL 跳转到哪个 URL
  - 页面标题的变化
  - 页面内容的切换

- **查看内容的详细信息**：
  - 浏览了哪些章节（列出具体章节名）
  - 查看了哪些内容区块
  - 点击了哪些内部链接
  - 展开了哪些折叠内容

- **时间顺序和操作链**：
  - 使用连接词："首先...然后...接着...最后..."
  - 明确标注操作的先后顺序
  - 突出操作之间的因果关系

【示例对比】

❌ 太概括（不可接受）：
- "用户进行了一次搜索"
- "用户浏览了网页"
- "用户填写了表单"
- "用户在百度搜索框输入关键词'测试'，点击搜索结果中的百度百科词条，并在百科页面内浏览不同章节内容。"

✅ 详细完整（必须达到这个水平）：
- "用户在百度搜索框（https://www.baidu.com）中输入关键词'iPhone 15'，点击'百度一下'
  按钮，在搜索结果页面点击第一个产品链接（https://item.jd.com/...），然后在商品详情页向下滚动浏览
  商品图片、价格信息和参数配置，最后点击'加入购物车'按钮"
- "用户在注册页面（https://example.com/signup）依次输入：姓名'张三'、邮箱'zhangsan@example.com'、
  密码'Pass123!'，从国家下拉框选择'中国'，勾选'同意服务条款'复选框，最后点击'立即注册'按钮，
  跳转到欢迎页面"
- "用户在搜索框输入'Python'并点击搜索，点击搜索结果中的'百度百科'链接，进入百度百科页面后依次
  浏览了'简介'章节、'历史发展'章节、'应用领域'章节的内容，然后点击页面底部的'参考来源'链接查看更多资料"

【模板参考】

对于搜索类任务：
"用户在[网站]搜索框输入'[关键词]'，点击搜索按钮，在结果页面点击[具体链接标题]，进入[目标页面]，依次浏览了[章节1]、[章节2]、[章节3]的内容"

对于表单类任务：
"用户在[页面名称]依次填写：[字段1]='[值1]'、[字段2]='[值2]'，选择[选项字段]='[选项值]'，最后点击'[按钮文本]'按钮"

对于浏览类任务：
"用户访问[URL]，向下滚动页面浏览[内容区块1]、[内容区块2]，点击[链接文本]查看更多内容，最后返回上一页"

**2. task_name（任务名称）**
- 2-6个字
- 使用动词开头
- 示例："搜索并查看百科"、"填写注册表单"、"浏览商品详情"

**3. task_category（任务类别）**
- 常见类别：数据采集、表单填写、自动化测试、数据抓取、网页浏览、数据处理、信息查询

**4. confidence（置信度）**
- 根据操作序列的明确程度（0-1）
- 操作清晰、目标明确：0.8-1.0
- 操作模糊、目标不明确：0.5-0.7

**5. keywords（关键词）**
- 3-5个关键词
- 提取关键动词和名词
- 示例：["搜索", "百度百科", "信息查询", "浏览", "数据采集"]
"""

        # 先格式化，再插入 metadata JSON（避免 metadata 中的花括号被错误解析）
        if metadata:
            metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2)
            return prompt.format(
                actions_description=actions_description, metadata_json=metadata_json
            )
        else:
            return prompt.format(actions_description=actions_description)

    def _build_parameter_extraction_prompt(
        self, actions_description: str, intent: Optional[Dict[str, Any]] = None
    ) -> str:
        """构建参数提取提示词"""
        prompt = """你是一个参数提取专家。请分析以下操作序列，识别哪些数据是参数（可变的数据）。

操作序列：
```
{actions_description}
```

"""

        if intent:
            prompt += """
任务意图：
```json
{intent_json}
```

"""

        prompt += """
请识别操作中的参数，即用户可能在不同执行中想要改变的数据。

参数类型包括：
- text: 文本输入
- number: 数字
- url: 网址
- selector: 选择器或选项
- file: 文件路径
- date: 日期

请以 JSON 格式返回参数列表：
```json
{{
  "parameters": [
    {{
      "name": "参数名（英文，snake_case）",
      "display_name": "显示名称（中文）",
      "type": "text|number|url|selector|file|date",
      "description": "参数说明",
      "required": true,
      "default_value": "示例值",
      "source_action_index": 1,
      "extraction_pattern": "如何从操作中提取此参数"
    }}
  ]
}}
```

注意：
1. 只提取真正会变化的参数，不要提取固定的配置
2. name 应该使用英文 snake_case 格式
3. source_action_index 是参数来源的操作索引（从1开始）
4. extraction_pattern 描述如何识别此参数（例如："从步骤3的输入内容中提取"）
"""

        # 先格式化，再插入 intent JSON（避免 intent 中的花括号被错误解析）
        if intent:
            intent_json = json.dumps(intent, ensure_ascii=False, indent=2)
            return prompt.format(actions_description=actions_description, intent_json=intent_json)
        else:
            return prompt.format(actions_description=actions_description)

    def _build_workflow_generation_prompt(self, context: Dict[str, Any]) -> str:
        """构建工作流生成提示词"""
        prompt = """你是一个工作流生成专家。请根据以下信息生成一个标准化的工作流定义。

任务信息：
```
操作序列：
{actions_description}
```

"""

        if context.get("intent"):
            prompt += """
意图分析：
```json
{intent_json}
```

"""

        if context.get("parameters"):
            prompt += """
参数定义：
```json
{parameters_json}
```

"""

        if context.get("vision_analysis"):
            prompt += """
视觉分析：
```json
{vision_analysis_json}
```

"""

        prompt += """
请生成一个标准的工作流定义，包含以下内容：

1. 工具名称：基于任务意图生成
2. 工具描述：清晰描述工具的功能
3. 参数定义：使用上面分析的参数
4. 执行步骤：将操作序列转换为可执行的步骤

步骤类型定义：
- browser_navigate: 浏览器导航到 URL
- browser_click: 点击浏览器元素
- browser_input: 在浏览器输入框输入文本
- browser_select: 下拉选择
- browser_extract: 提取数据
- browser_wait: 等待条件满足
- desktop_launch: 启动桌面应用
- desktop_click: 点击桌面元素
- desktop_input: 输入文本
- desktop_wait: 等待
- data_extract: 提取数据
- data_save: 保存数据

请以 JSON 格式返回：
```json
{{
  "tool_name": "工具名称",
  "description": "工具描述",
  "category": "工具类别",
  "parameters": [
    {{
      "name": "参数名",
      "display_name": "显示名",
      "type": "text|number|url|selector|file|date",
      "description": "说明",
      "required": true,
      "default_value": "默认值"
    }}
  ],
  "steps": [
    {{
      "step_number": 1,
      "step_name": "步骤名称",
      "action_type": "browser_navigate|browser_click|...",
      "description": "步骤描述",
      "parameters": {{
        "url": "https://example.com",
        "selector": "xpath或css选择器",
        "text": "输入的文本",
        "wait_condition": "等待条件"
      }},
      "locator_info": {{
        "type": "xpath|css_selector|coordinate|image",
        "value": "定位值",
        "fallback": ["备用定位方式"]
      }},
      "error_handling": {{
        "retry_times": 3,
        "retry_interval": 1000,
        "on_failure": "continue|abort"
      }}
    }}
  ],
  "expected_output": {{
    "type": "data|status|confirmation",
    "description": "期望的输出结果"
  }},
  "metadata": {{
    "recording_mode": "browser|desktop",
    "estimated_duration": "预计执行时间（秒）",
    "complexity": "simple|medium|complex",
    "reliability": "high|medium|low"
  }}
}}
```

注意：
1. 步骤参数中的变量应该使用 {{{{参数名}}}} 的格式
2. locator_info 应该包含完整的定位策略
3. error_handling 定义了错误处理方式
4. metadata 提供了工作流的元信息
"""

        # 先格式化，再插入 JSON 数据（避免 JSON 中的花括号被错误解析）
        format_params = {"actions_description": context["actions_description"]}

        if context.get("intent"):
            format_params["intent_json"] = json.dumps(
                context["intent"], ensure_ascii=False, indent=2
            )

        if context.get("parameters"):
            format_params["parameters_json"] = json.dumps(
                context["parameters"], ensure_ascii=False, indent=2
            )

        if context.get("vision_analysis"):
            format_params["vision_analysis_json"] = json.dumps(
                context["vision_analysis"], ensure_ascii=False, indent=2
            )

        return prompt.format(**format_params)

    def _parse_intent_response(self, response_text: str) -> Dict[str, Any]:
        """解析意图分析响应"""
        import re

        # 查找 JSON 代码块
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试直接解析
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # 返回默认值
        return self._get_default_intent()

    def _parse_parameters_response(self, response_text: str) -> List[Dict[str, Any]]:
        """解析参数提取响应"""
        import re

        # 查找 JSON 代码块
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return data.get("parameters", [])
            except json.JSONDecodeError:
                pass

        # 尝试直接解析
        try:
            data = json.loads(response_text)
            return data.get("parameters", [])
        except json.JSONDecodeError:
            pass

        return []

    def _parse_workflow_response(self, response_text: str) -> Dict[str, Any]:
        """解析工作流生成响应"""
        import re

        # 查找 JSON 代码块
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试直接解析
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        return {}

    def _get_default_intent(self) -> Dict[str, Any]:
        """获取默认意图"""
        return {
            "task_name": "未知任务",
            "task_description": "无法识别任务意图",
            "task_category": "其他",
            "user_intent": "未知",
            "confidence": 0.0,
            "keywords": [],
        }

    def close(self) -> None:
        """关闭客户端"""
        if self.client:
            self.client = None

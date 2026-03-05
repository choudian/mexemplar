"""
代码生成提示词

用于根据意图生成可执行代码。

从 SemanticAnalyzer._build_workflow_generation_prompt 迁移。
"""

import json
from typing import List, Dict, Any


def get_code_generation_prompt(
    intent_data: Dict[str, Any],
    actions: List[Any]
) -> str:
    """
    生成代码生成提示词

    要求 LLM 生成完全独立的 Python 代码，不依赖 src 模块
    """
    # 构建操作描述
    actions_description = _describe_actions(actions)

    prompt = """你是一个工作流生成专家。请根据以下信息生成一个标准化的工作流定义。

任务信息：
```
操作序列：
{actions_description}
```

意图分析：
```json
{intent_json}
```

【重要 - 代码要求】

1. **完全独立**：代码必须独立运行，不能导入 src 或 exemplar 相关模块

2. **使用标准库**：只允许使用以下库：
   - playwright / playwright.async_api（浏览器自动化）
   - asyncio（异步支持）
   - json（数据序列化）
   - typing（类型注解）
   - 其他 Python 标准库

3. **代码结构**：
```python
# -*- coding: utf-8 -*-
import asyncio
import json
import sys
from playwright.async_api import async_playwright

async def execute(**kwargs) -> Dict[str, Any]:
    \"\"\"执行工具\"\"\"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            # 执行步骤（使用 page.goto, page.click, page.fill 等）
            # ...

            return {"success": True, "message": "执行完成", "data": None}

        except Exception as e:
            return {"success": False, "message": str(e)}

        finally:
            await browser.close()

if __name__ == '__main__':
    # 从命令行参数读取
    params = {}
    for arg in sys.argv[1:]:
        if '=' in arg:
            key, value = arg.split('=', 1)
            params[key] = value

    # 执行并输出 JSON
    result = asyncio.run(execute(**params))
    print(json.dumps(result, ensure_ascii=False))
```

4. **返回格式**：必须返回 JSON 格式：
   ```json
   {
     "success": boolean,
     "message": string,
     "data": any
   }
   ```

请生成标准的工作流定义，包含以下内容：

1. 工具名称：基于任务意图生成
2. 工具描述：清晰描述工具的功能
3. 参数定义：识别可变参数
4. 执行步骤：将操作序列转换为可执行的步骤

步骤类型定义：
- browser_navigate: 浏览器导航到 URL
- browser_click: 点击浏览器元素
- browser_input: 在浏览器输入框输入文本
- browser_select: 下拉选择
- browser_extract: 提取数据
- browser_wait: 等待条件满足

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
        "text": "输入的文本"
      }},
      "locator_info": {{
        "type": "xpath|css_selector|coordinate",
        "value": "定位值",
        "fallback": ["备用定位方式"]
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
3. metadata 提供了工作流的元信息
4. 生成的代码会通过 subprocess 独立执行，不要依赖任何 src 模块
"""

    intent_json = json.dumps(intent_data, ensure_ascii=False, indent=2)
    return prompt.format(
        actions_description=actions_description,
        intent_json=intent_json
    )


def _describe_actions(actions: List[Any]) -> str:
    """将操作序列转换为文本描述"""
    if not actions:
        return "没有操作"

    lines = []
    for idx, action in enumerate(actions, 1):
        action_desc = f"步骤 {idx}: {action.action_type}"
        lines.append(action_desc)

        if hasattr(action, 'url') and action.url:
            lines.append(f"  URL: {action.url}")

        if hasattr(action, 'parameters') and action.parameters:
            for key, value in action.parameters.items():
                if key not in ["x", "y", "button", "offsetX", "offsetY"]:
                    lines.append(f"  {key}: {value}")

    return "\n".join(lines)

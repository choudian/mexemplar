"""
代码生成提示词

基于执行蓝图生成可执行的 Playwright 代码。
"""

from typing import Dict, Any


def get_code_generation_prompt(
    blueprint: 'ExecutionBlueprint',
    recording_data: Dict[str, Any] = None
) -> str:
    """
    生成代码生成提示词

    基于执行蓝图生成代码，不再做需求分析。

    Args:
        blueprint: 执行蓝图
        recording_data: 录制数据（可选，用于获取原始操作）

    Returns:
        提示词字符串
    """
    # 格式化输入参数
    input_params_desc = _format_input_parameters(blueprint.input_parameters)

    # 格式化输出规范
    output_spec_desc = _format_output_spec(blueprint.output_spec)

    # 格式化执行步骤
    execution_steps_desc = _format_execution_steps(blueprint.execution_steps)

    # 获取录制数据描述（如果有）
    recording_desc = ""
    if recording_data:
        actions = recording_data.get("actions", [])
        recording_desc = _format_recording_data(actions)

    prompt = """你是一个 Python 程序员。
根据以下【执行蓝图】，生成可执行的 Playwright 代码。

【执行蓝图】

**工具名称**: {tool_name}

**功能描述**: {tool_summary}

**输入参数**:
{input_params}

**输出规范**:
{output_spec}

**执行步骤**:
{execution_steps}

**执行环境**:
- 需要的库: {libraries}
- Python 版本: {python_version}

**隐含需求**:
{implicit_requirements}

**边界情况**:
{edge_cases}

{recording_section}

【代码要求】

1. **代码必须独立运行**（不依赖 src 或 exemplar 模块）

2. **使用的库**:
   - playwright / playwright.async_api（浏览器自动化）
   - asyncio（异步支持）
   - json（数据序列化）
   - 其他 Python 标准库

3. **代码结构**:
```python
# -*- coding: utf-8 -*-
import asyncio
import json
import sys
from playwright.async_api import async_playwright
from typing import Dict, Any


async def execute(**kwargs) -> Dict[str, Any]:
    \"\"\"执行工具\"\"\"
    result = {{
        "success": False,
        "message": "",
        "data": None
    }}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            # 从 kwargs 获取参数
            # ... 实现你的功能 ...

            result["success"] = True
            result["message"] = "执行完成"
            result["data"] = ... # 按照输出规范设置

        except Exception as e:
            result["message"] = f"执行错误: {{str(e)}}"

        finally:
            await browser.close()

    return result


if __name__ == '__main__':
    # 从命令行参数读取
    params = {{}}
    for arg in sys.argv[1:]:
        if '=' in arg:
            key, value = arg.split('=', 1)
            params[key] = value

    # 执行并输出 JSON 结果
    result = asyncio.run(execute(**params))
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

4. **返回格式**: 必须返回 JSON 格式：
   ```json
   {{
     "success": boolean,
     "message": string,
     "data": any
   }}
   ```

5. **处理隐含需求和边界情况**:
   - 确保隐含需求中的注意事项都被正确处理
   - 对边界情况有适当的错误处理

【请生成完整的 Python 代码】
"""

    return prompt.format(
        tool_name=blueprint.tool_name,
        tool_summary=blueprint.tool_summary,
        input_params=input_params_desc,
        output_spec=output_spec_desc,
        execution_steps=execution_steps_desc,
        libraries=", ".join(blueprint.execution_environment.required_libraries),
        python_version=blueprint.execution_environment.python_version,
        implicit_requirements="\n".join(
            f"- {req}" for req in blueprint.implicit_requirements
        ) if blueprint.implicit_requirements else "无",
        edge_cases="\n".join(
            f"- {case}" for case in blueprint.edge_cases
        ) if blueprint.edge_cases else "无",
        recording_section=f"\n**录制数据参考**:\n{recording_desc}" if recording_desc else ""
    )


def _format_input_parameters(parameters: list) -> str:
    """格式化输入参数"""
    if not parameters:
        return "无"

    lines = []
    for param in parameters:
        required_mark = "（必填）" if param.required else f"（可选，默认: {param.default_value}）"
        lines.append(f"- **{param.name}**: {param.label} {required_mark}")
        if param.description:
            lines.append(f"  描述: {param.description}")
        if param.example:
            lines.append(f"  示例: {param.example}")
        lines.append("")

    return "\n".join(lines)


def _format_output_spec(output_spec: 'OutputSpec') -> str:
    """格式化输出规范"""
    lines = [
        f"**数据类型**: {output_spec.data_type}",
        f"**描述**: {output_spec.description}"
    ]

    if output_spec.item_fields:
        lines.append("**字段**:")
        for field_name, field_spec in output_spec.item_fields.items():
            required_mark = "（必填）" if field_spec.required else ""
            lines.append(f"- {field_name}: {field_spec.type} - {field_spec.description} {required_mark}")

    return "\n".join(lines)


def _format_execution_steps(steps: list) -> str:
    """格式化执行步骤"""
    if not steps:
        return "无"

    lines = []
    for step in steps:
        lines.append(f"步骤 {step.step_number}: {step.step_name}")
        lines.append(f"  操作类型: {step.action_type}")
        lines.append(f"  描述: {step.description}")
        if step.parameters:
            lines.append("  参数:")
            for key, value in step.parameters.items():
                lines.append(f"    {key}: {value}")
        lines.append("")

    return "\n".join(lines)


def _format_recording_data(actions: list) -> str:
    """格式化录制数据"""
    if not actions:
        return "无录制数据"

    lines = []
    for idx, action in enumerate(actions[:10], 1):  # 只显示前10个操作
        action_desc = f"步骤 {idx}: {action.action_type}"
        lines.append(action_desc)

        if hasattr(action, 'url') and action.url:
            lines.append(f"  URL: {action.url}")

        if hasattr(action, 'parameters') and action.parameters:
            for key, value in action.parameters.items():
                if key not in ["x", "y", "button", "offsetX", "offsetY"]:
                    lines.append(f"  {key}: {value}")

        if hasattr(action, 'dom_element') and action.dom_element:
            dom = action.dom_element
            if dom.get("text"):
                lines.append(f"  文本: {dom['text']}")
            if dom.get("selector"):
                lines.append(f"  选择器: {dom['selector']}")

    if len(actions) > 10:
        lines.append(f"... 还有 {len(actions) - 10} 个操作")

    return "\n".join(lines)
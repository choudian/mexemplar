"""
参数解析器

本模块负责处理工作流执行中的动态参数替换，包括：
1. 用户参数替换：{{param_name}} → 用户提供的值
2. 步骤输出引用：${step_name.output_key} → 前续步骤的输出
3. 运行时变量：${variable.key} → 动态变量
"""

import re
from typing import Any, Dict, List
from .execution_context import ExecutionContext


# 参数引用正则模式：匹配 {{param}} 或 ${param}
PARAM_PATTERN = re.compile(r"\{\{([^}]+)\}\}|\$\{([^}]+)\}")


class ParameterResolver:
    """
    参数解析器

    负责解析和替换步骤中的参数引用，支持递归解析和复杂类型处理。
    """

    def __init__(self):
        """初始化参数解析器"""
        self._param_pattern = PARAM_PATTERN

    def resolve(self, value: Any, context: ExecutionContext) -> Any:
        """
        解析值中的参数引用

        Args:
            value: 需要解析的值（可以是字符串、列表、字典等）
            context: 执行上下文

        Returns:
            解析后的值
        """
        if isinstance(value, str):
            return self._resolve_string(value, context)
        elif isinstance(value, list):
            return [self.resolve(item, context) for item in value]
        elif isinstance(value, dict):
            return {k: self.resolve(v, context) for k, v in value.items()}
        else:
            return value

    def resolve_step(self, step: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        """
        解析步骤中的所有参数引用

        Args:
            step: 步骤定义
            context: 执行上下文

        Returns:
            解析后的步骤
        """
        resolved_step = {}
        for key, value in step.items():
            resolved_step[key] = self.resolve(value, context)
        return resolved_step

    def _resolve_string(self, value: str, context: ExecutionContext) -> Any:
        """
        解析字符串中的参数引用

        Args:
            value: 字符串值
            context: 执行上下文

        Returns:
            解析后的值（如果整个字符串就是一个引用，则返回引用的值；否则返回替换后的字符串）
        """
        matches = list(self._param_pattern.finditer(value))

        if not matches:
            return value

        # 如果整个字符串就是一个引用（例如 "{{param}}" 或 "${step.output}"）
        # 则返回引用的原始值（保持类型）
        if len(matches) == 1 and matches[0].group(0) == value:
            ref = self._extract_reference(value)
            resolved = self._resolve_reference(ref, context)
            return resolved

        # 否则替换字符串中的引用
        result = value
        for match in reversed(matches):  # 反向替换以保持位置正确
            ref = self._extract_reference(match.group(0))
            resolved_value = self._resolve_reference(ref, context)
            result = result[: match.start()] + str(resolved_value) + result[match.end() :]

        return result

    def _extract_reference(self, placeholder: str) -> str:
        """
        从占位符中提取引用名称

        Args:
            placeholder: 占位符字符串（例如 "{{param}}" 或 "${step.output}"）

        Returns:
            引用名称（例如 "param" 或 "step.output"）
        """
        # 移除 {{ }} 或 ${ }
        if placeholder.startswith("{{") and placeholder.endswith("}}"):
            return placeholder[2:-2].strip()
        elif placeholder.startswith("${") and placeholder.endswith("}"):
            return placeholder[2:-1].strip()
        return placeholder

    def _resolve_reference(self, ref: str, context: ExecutionContext) -> Any:
        """
        解析单个引用

        Args:
            ref: 引用名称（可能是 "param" 或 "step.output" 或 "variable.key"）
            context: 执行上下文

        Returns:
            引用的值

        Raises:
            ValueError: 引用无法解析
        """
        # 检查是否是步骤输出引用（格式：step_name.output_key）
        if "." in ref:
            parts = ref.split(".", 1)
            source = parts[0]
            key = parts[1]

            # 检查是否是变量引用（格式：variable.key）
            if source == "variable":
                value = context.get_variable(key)
                if value is None:
                    raise ValueError(f"变量 '{key}' 不存在")
                return value

            # 否则认为是步骤输出引用（格式：step_name.output_key）
            value = context.get_step_output(source, key)
            if value is None:
                raise ValueError(f"步骤 '{source}' 的输出 '{key}' 不存在")
            return value

        # 单个引用，优先从用户参数中查找
        value = context.get_parameter(ref)
        if value is not None:
            return value

        # 尝试从变量中查找
        value = context.get_variable(ref)
        if value is not None:
            return value

        raise ValueError(f"无法解析引用: '{ref}'")

    def extract_dependencies(self, step: Dict[str, Any]) -> List[str]:
        """
        提取步骤的依赖关系（前续步骤名称）

        Args:
            step: 步骤定义

        Returns:
            依赖的步骤名称列表
        """
        dependencies = set()

        def extract_from_value(value: Any):
            if isinstance(value, str):
                matches = self._param_pattern.finditer(value)
                for match in matches:
                    ref = self._extract_reference(match.group(0))
                    # 只提取步骤引用（不提取用户参数和变量）
                    if "." in ref and not ref.startswith("variable."):
                        step_name = ref.split(".")[0]
                        dependencies.add(step_name)
            elif isinstance(value, list):
                for item in value:
                    extract_from_value(item)
            elif isinstance(value, dict):
                for v in value.values():
                    extract_from_value(v)

        extract_from_value(step)
        return list(dependencies)

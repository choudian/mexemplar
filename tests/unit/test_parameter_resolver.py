"""
参数解析器单元测试
"""

import pytest
from src.execution.parameter_resolver import ParameterResolver
from src.execution.execution_context import ExecutionContext


class TestParameterResolver:
    """参数解析器测试类"""

    def setup_method(self):
        """测试方法前置设置"""
        self.resolver = ParameterResolver()
        self.context = ExecutionContext(
            execution_id="test-exec-1",
            tool_id="tool-1",
            tool_name="测试工具",
            parameters={"keyword": "python", "url": "https://www.baidu.com", "count": 10},
        )

    def test_resolve_user_parameter_string(self):
        """测试字符串中的用户参数替换"""
        result = self.resolver.resolve("Search for {{keyword}}", self.context)
        assert result == "Search for python"

    def test_resolve_user_parameter_whole_string(self):
        """测试整个字符串就是参数引用的情况"""
        result = self.resolver.resolve("{{keyword}}", self.context)
        assert result == "python"

    def test_resolve_user_parameter_multiple(self):
        """测试多个参数替换"""
        result = self.resolver.resolve("Search {{keyword}} at {{url}}", self.context)
        assert result == "Search python at https://www.baidu.com"

    def test_resolve_no_parameters(self):
        """测试无参数的字符串"""
        result = self.resolver.resolve("Hello World", self.context)
        assert result == "Hello World"

    def test_resolve_integer_parameter(self):
        """测试整数类型参数"""
        result = self.resolver.resolve("{{count}}", self.context)
        assert result == 10

    def test_resolve_list_parameter(self):
        """测试列表中的参数替换"""
        result = self.resolver.resolve(["{{keyword}}", "static", "{{url}}"], self.context)
        assert result == ["python", "static", "https://www.baidu.com"]

    def test_resolve_dict_parameter(self):
        """测试字典中的参数替换"""
        result = self.resolver.resolve(
            {"search_term": "{{keyword}}", "target_url": "{{url}}", "static_value": "unchanged"},
            self.context,
        )
        assert result == {
            "search_term": "python",
            "target_url": "https://www.baidu.com",
            "static_value": "unchanged",
        }

    def test_resolve_nested_dict(self):
        """测试嵌套字典中的参数替换"""
        result = self.resolver.resolve(
            {"search": {"term": "{{keyword}}", "url": "{{url}}"}}, self.context
        )
        assert result == {"search": {"term": "python", "url": "https://www.baidu.com"}}

    def test_resolve_step(self):
        """测试步骤参数解析"""
        step = {
            "step_name": "search",
            "action_type": "fill",
            "parameters": {"value": "{{keyword}}"},
            "locator_info": {"type": "css_selector", "value": "#input"},
        }
        resolved = self.resolver.resolve_step(step, self.context)
        assert resolved["parameters"]["value"] == "python"
        assert resolved["locator_info"]["value"] == "#input"

    def test_resolve_variable_reference(self):
        """测试变量引用解析"""
        self.context.set_variable("extracted_value", "test_value_123")

        result = self.resolver.resolve("${variable.extracted_value}", self.context)
        assert result == "test_value_123"

    def test_resolve_step_output_reference(self):
        """测试步骤输出引用解析"""
        from src.execution.execution_context import StepResult
        from datetime import datetime

        # 添加一个模拟的步骤结果
        step_result = StepResult(
            step_name="extract_data",
            step_number=1,
            success=True,
            result={"price": "99.99"},
            started_at=datetime.now(),
            finished_at=datetime.now(),
        )
        self.context.add_step_result(step_result)

        result = self.resolver.resolve("${extract_data.price}", self.context)
        assert result == "99.99"

    def test_resolve_unknown_reference(self):
        """测试未知引用抛出异常"""
        with pytest.raises(ValueError, match="无法解析引用"):
            self.resolver.resolve("{{unknown_param}}", self.context)

    def test_resolve_unknown_step_output(self):
        """测试未知步骤输出引用抛出异常"""
        with pytest.raises(ValueError, match="步骤.*的输出.*不存在"):
            self.resolver.resolve("${unknown_step.output}", self.context)

    def test_extract_dependencies(self):
        """测试提取步骤依赖"""
        step = {
            "step_name": "final_step",
            "action_type": "fill",
            "parameters": {"value": "${extract_data.price}"},
        }

        dependencies = self.resolver.extract_dependencies(step)
        assert dependencies == ["extract_data"]

    def test_extract_dependencies_multiple(self):
        """测试提取多个步骤依赖"""
        step = {
            "step_name": "final_step",
            "parameters": {
                "value1": "${step1.output1}",
                "value2": "${step2.output2}",
                "user_param": "{{keyword}}",
            },
        }

        dependencies = self.resolver.extract_dependencies(step)
        assert set(dependencies) == {"step1", "step2"}

    def test_extract_dependencies_no_dependencies(self):
        """测试无依赖的步骤"""
        step = {
            "step_name": "independent_step",
            "action_type": "navigate",
            "parameters": {"url": "https://example.com"},
        }

        dependencies = self.resolver.extract_dependencies(step)
        assert dependencies == []

    def test_dollar_sign_syntax(self):
        """测试 ${} 语法"""
        self.context.set_variable("test_var", "value123")

        result = self.resolver.resolve("${variable.test_var}", self.context)
        assert result == "value123"

    def test_mixed_syntax(self):
        """测试混合使用 {{}} 和 ${} 语法"""
        self.context.set_variable("var", "world")
        self.context.parameters["param"] = "hello"

        result = self.resolver.resolve("{{param}} ${variable.var}", self.context)
        assert result == "hello world"

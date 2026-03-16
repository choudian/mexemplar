"""
测试参数验证机制
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.business.agents.validation import validate_parameters


class TestValidation:
    """参数验证测试"""

    def test_required_parameter_present(self):
        """测试必填参数存在时通过验证"""

        @validate_parameters({
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}}
        })
        def query_data(id: str) -> str:
            return f"Query {id}"

        result = query_data(id="123")
        assert result == "Query 123"

    def test_required_parameter_missing(self):
        """测试缺少必填参数时返回错误"""

        @validate_parameters({
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "string"}}
        })
        def query_data(id: str) -> str:
            return f"Query {id}"

        result = query_data()
        assert "错误" in result
        assert "缺少必填参数" in result

    def test_type_validation_pass(self):
        """测试类型验证通过"""

        @validate_parameters({
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer"}}
        })
        def process_items(count: int) -> str:
            return f"Processing {count} items"

        result = process_items(count=10)
        assert result == "Processing 10 items"

    def test_type_validation_fail(self):
        """测试类型验证失败"""

        @validate_parameters({
            "type": "object",
            "required": ["count"],
            "properties": {"count": {"type": "integer"}}
        })
        def process_items(count: int) -> str:
            return f"Processing {count} items"

        result = process_items(count="ten")
        assert "错误" in result
        assert "count" in result
        assert "int" in result

    def test_optional_parameter(self):
        """测试可选参数"""

        @validate_parameters({
            "type": "object",
            "required": [],
            "properties": {"name": {"type": "string"}}
        })
        def greet(name: str = "World") -> str:
            return f"Hello, {name}!"

        # 不传参数，使用默认值
        result = greet()
        assert result == "Hello, World!"

        # 传入参数
        result = greet(name="Alice")
        assert result == "Hello, Alice!"

    def test_optional_with_none(self):
        """测试 Optional 类型允许 None"""

        from typing import Optional

        @validate_parameters({
            "type": "object",
            "required": [],
            "properties": {"value": {"type": "string"}}
        })
        def process(value: Optional[str] = None) -> str:
            return f"Value: {value}"

        # 传入 None
        result = process(value=None)
        assert result == "Value: None"

        # 传入字符串
        result = process(value="test")
        assert result == "Value: test"

    def test_multiple_required_parameters(self):
        """测试多个必填参数"""

        @validate_parameters({
            "type": "object",
            "required": ["id", "action"],
            "properties": {
                "id": {"type": "string"},
                "action": {"type": "string"}
            }
        })
        def perform_action(id: str, action: str) -> str:
            return f"{action} on {id}"

        # 缺少 action
        result = perform_action(id="123")
        assert "缺少必填参数" in result
        assert "action" in result

        # 两个参数都存在
        result = perform_action(id="123", action="delete")
        assert result == "delete on 123"
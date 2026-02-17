"""
测试 JSON 提取功能
"""

import pytest
from src.business.ai.preprocessing.analyzers.intelligence_analyzer import RequestIntelligenceAnalyzer


class TestJSONExtraction:
    """测试 JSON 提取方法"""

    def setup_method(self):
        """初始化分析器"""
        self.analyzer = RequestIntelligenceAnalyzer()

    def test_extract_simple_json(self):
        """测试提取简单的 JSON 对象"""
        response = '{"is_meaningful": true, "reason": "test"}'
        result = self.analyzer._extract_json_from_response(response)
        assert result["is_meaningful"] is True
        assert result["reason"] == "test"

    def test_extract_json_from_code_block(self):
        """测试从代码块中提取 JSON"""
        response = '```json\n{"is_meaningful": true, "reason": "test"}\n```'
        result = self.analyzer._extract_json_from_response(response)
        assert result["is_meaningful"] is True

    def test_extract_json_with_nested_arrays(self):
        """测试提取包含嵌套数组的 JSON"""
        response = '{"is_meaningful": true, "items": [{"id": 1}, {"id": 2}]}'
        result = self.analyzer._extract_json_from_response(response)
        assert result["is_meaningful"] is True
        assert len(result["items"]) == 2

    def test_extract_json_with_nested_objects(self):
        """测试提取包含嵌套对象的 JSON"""
        response = '{"is_meaningful": true, "data": {"nested": {"value": 123}}}'
        result = self.analyzer._extract_json_from_response(response)
        assert result["is_meaningful"] is True
        assert result["data"]["nested"]["value"] == 123

    def test_extract_json_from_mixed_text(self):
        """测试从混合文本中提取 JSON"""
        response = '这是分析结果：\n{"is_meaningful": true, "reason": "test"}\n分析完成。'
        result = self.analyzer._extract_json_from_response(response)
        assert result["is_meaningful"] is True

    def test_extract_complete_json_object(self):
        """测试括号匹配算法提取完整 JSON"""
        # 测试包含预期字段的 JSON
        text = '前缀文本 {"is_meaningful": true, "reason": "test", "items": [{"id": 1}, {"id": 2}]} 后缀文本'
        result = self.analyzer._extract_complete_json_object(text)
        assert result is not None
        assert '{"is_meaningful":' in result
        assert '"reason": "test"' in result

    def test_extract_complete_json_with_strings_containing_braces(self):
        """测试处理包含花括号的字符串"""
        # 字符串内的 { 不应该影响匹配
        text = '{"is_meaningful": true, "pattern": "{id}"}'
        result = self.analyzer._extract_complete_json_object(text)
        assert result is not None
        assert '"pattern": "{id}"' in result

    def test_extract_json_with_escape_sequences(self):
        """测试处理转义字符"""
        text = r'{"is_meaningful": true, "path": "C:\\Users\\test"}'
        result = self.analyzer._extract_complete_json_object(text)
        assert result is not None
        assert "is_meaningful" in result

    def test_extract_json_fails_on_invalid_json(self):
        """测试无效 JSON 抛出异常"""
        with pytest.raises(ValueError) as exc_info:
            self.analyzer._extract_json_from_response("not a json")
        assert "无法从响应中提取有效 JSON" in str(exc_info.value)

    def test_extract_json_from_string_only(self):
        """测试只返回字符串的情况应该失败"""
        # 字符串 "items" 会被 json.loads 解析成功，但我们的方法要求返回字典
        with pytest.raises(ValueError) as exc_info:
            self.analyzer._extract_json_from_response('"items"')
        assert "不是 JSON 对象（字典），而是 str" in str(exc_info.value)

    def test_extract_complete_json_empty_response(self):
        """测试空响应"""
        result = self.analyzer._extract_complete_json_object("")
        assert result is None

    def test_extract_complete_json_no_braces(self):
        """测试没有花括号的响应"""
        result = self.analyzer._extract_complete_json_object("just plain text")
        assert result is None

    def test_extract_complete_json_unmatched_braces(self):
        """测试不匹配的花括号"""
        result = self.analyzer._extract_complete_json_object('{"is_meaningful": true')
        # 应该返回 None（因为括号不匹配）
        assert result is None

    def test_extract_json_multiple_candidates(self):
        """测试多个 JSON 对象，应该提取第一个包含预期字段的完整对象"""
        text = """
        第一个部分 {"incomplete": true, "data": {"x": 1}}
        第二个部分 {"is_meaningful": true, "reason": "valid"}
        第三个部分 {"another": "object", "is_meaningful": false}
        """
        result = self.analyzer._extract_json_from_response(text)
        # 应该提取到第一个包含预期字段的完整对象（第二个部分）
        assert result["is_meaningful"] is True
        assert result["reason"] == "valid"

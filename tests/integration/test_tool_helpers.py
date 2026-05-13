"""
make_error_result / is_standardized_error 单元测试

覆盖边界情况：
- 空 / 非 JSON / 截断 JSON
- 纯文本含 "error" 关键词
- {"success": false} 无 message（不应触发）
- {"success": false, "message": "..."}（应触发）
- {"error": "code", "message": "..."}（应触发）
- error 值为非字符串（不应触发）
- error 值为空字符串（不应触发）
- extra 参数覆盖防护
"""

import json

from src.business.agents.tool_helpers import (
    error_json,
    is_standardized_error,
    make_error_result,
)

# -- make_error_result --


class TestMakeErrorResult:
    def test_basic(self):
        r = make_error_result("not_executed", "skipped")
        obj = json.loads(r)
        assert obj["error"] == "not_executed"
        assert obj["message"] == "skipped"

    def test_extra_fields(self):
        r = make_error_result("handler_exception", "boom", tool_name="t1")
        obj = json.loads(r)
        assert obj["tool_name"] == "t1"

    def test_no_unicode_escape(self):
        r = make_error_result("code", "中文消息")
        assert "中文消息" in r


# -- is_standardized_error --


class TestIsStandardizedError:
    # 正例：error_json 格式
    def test_error_json_format(self):
        assert is_standardized_error(error_json("fail")) is True

    def test_error_json_raw(self):
        s = json.dumps({"success": False, "message": "bad", "data": None})
        assert is_standardized_error(s) is True

    # 正例：make_error_result 格式
    def test_make_error_result_format(self):
        assert is_standardized_error(make_error_result("not_executed", "skip")) is True

    def test_error_field_string(self):
        s = json.dumps({"error": "unknown_tool", "message": "nope"})
        assert is_standardized_error(s) is True

    # 反例：{"success": false} 无 message —— 不应触发级联
    def test_success_false_without_message(self):
        s = json.dumps({"success": False})
        assert is_standardized_error(s) is False

    def test_success_false_data_only(self):
        s = json.dumps({"success": False, "data": {"rows": []}})
        assert is_standardized_error(s) is False

    # 反例：error 值为非字符串 / 空字符串
    def test_error_non_string(self):
        s = json.dumps({"error": 42, "message": "nope"})
        assert is_standardized_error(s) is False

    def test_error_empty_string(self):
        s = json.dumps({"error": "", "message": "nope"})
        assert is_standardized_error(s) is False

    # 反例：纯文本包含 error / success 关键词
    def test_plain_text_with_error_word(self):
        assert is_standardized_error("An error occurred") is False

    def test_plain_text_with_success_word(self):
        assert is_standardized_error("success: true!") is False

    # 反例：非字符串输入
    def test_non_string_input(self):
        assert is_standardized_error(None) is False
        assert is_standardized_error(42) is False
        assert is_standardized_error({"error": "x"}) is False

    # 反例：截断 / 无效 JSON
    def test_truncated_json(self):
        assert is_standardized_error('{"error": "not_ex') is False

    def test_empty_string(self):
        assert is_standardized_error("") is False

    # 反例：嵌套结构中的 success:false（顶层不含）
    def test_nested_success_false(self):
        s = json.dumps({"data": {"success": False}})
        assert is_standardized_error(s) is False

    # 边界：success 为 true 不应触发
    def test_success_true(self):
        s = json.dumps({"success": True, "message": "ok"})
        assert is_standardized_error(s) is False

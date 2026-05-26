"""
LLM 代码质量 Reviewer

调用 LLM 对程序员生成的代码进行质量评审，返回通过/失败和反馈。
"""

import logging
from dataclasses import dataclass

from src.business.ai.llm_client import LangChainLLMClient
from src.business.debug.context import TraceContext
from src.business.agents.prompts.trial_prompt import format_parameters_text
from src.utils.llm_helpers import extract_json_from_response
from src.utils.helpers import safe_format_template

logger = logging.getLogger(__name__)

REVIEW_PROMPT_TEMPLATE = """你是 Exemplar 的代码审查员。程序员刚刚生成了一个工具代码，请审查是否存在明显的硬伤。

## 工具信息

工具描述：{description}

参数列表：
{parameters_text}

## 待审查代码

```python
{code}
```

## 审查范围

只关注以下 5 类硬伤，发现任意一类才判定不通过：

1. **语法错误** — 代码无法被 Python 解析执行
2. **参数漏用** — 参数列表中的参数有未在代码中使用的（参数名未出现在代码里）
3. **函数签名错误** — 入口函数不是 `async def execute(**kwargs)`
4. **返回格式错误** — 没有返回 `{"success": ..., "message": ..., "data": ...}` 格式的字典
5. **必崩逻辑** — 存在明显会导致运行时崩溃的逻辑（如对 None 直接调用方法、明确的除零等）

代码有小问题、风格不完美、注释不够完整、实现方式不够优雅，都不是打回的理由。

## 不在审查范围内

**以下内容不要质疑**，这些是程序员从录制数据中验证过的技术决策：
- 具体的 URL、API 路径、请求参数名称和格式
- HTTP 响应体的字段结构（如 `response.json()["data"]["items"]`）
- CSS 选择器、DOM 元素属性、页面结构
- 选择 Playwright 还是 requests 的技术方案
- 任何具体的数值、字符串常量

## 输出格式

以 JSON 格式返回，不要包含其他内容：
{"passed": true/false, "feedback": "通过时一句话说明代码可用；不通过时说明具体是哪条硬伤、在代码的哪里"}"""


@dataclass
class ReviewResult:
    """LLM Review 结果"""

    passed: bool
    feedback: str


class LLMReviewer:
    """LLM 代码质量审查器"""

    def __init__(self, llm_client: LangChainLLMClient):
        self._llm = llm_client

    def review(self, code: str, requirement: dict) -> ReviewResult:
        """
        审查代码质量

        Args:
            code: 待审查的 Python 代码
            requirement: 需求上下文，含 description 和 parameters 字段

        Returns:
            ReviewResult（passed + feedback）
        """
        try:
            prompt = safe_format_template(
                REVIEW_PROMPT_TEMPLATE,
                description=requirement.get("description", ""),
                parameters_text=format_parameters_text(requirement.get("parameters", [])),
                code=code,
            )
            with TraceContext(
                source="llm_review",
                agent_type="reviewer",
                workflow_id=str(requirement.get("workflow_id") or requirement.get("recording_id") or ""),
            ):
                response = self._llm.chat(prompt)
            return self._parse_result(response)
        except Exception as e:
            logger.error(f"[LLMReviewer] Review 调用失败: {e}")
            return ReviewResult(passed=True, feedback=f"Review 服务异常，默认通过: {e}")

    def _parse_result(self, response: str) -> ReviewResult:
        """解析 LLM 返回的 JSON 结果"""
        try:
            data = extract_json_from_response(response, require_dict=True, log_prefix="Review")
            return ReviewResult(
                passed=bool(data.get("passed", True)), feedback=str(data.get("feedback", ""))
            )
        except ValueError:
            # 解析失败，检查关键词
            lower = response.lower()
            passed = "passed: false" not in lower and "failed" not in lower
            return ReviewResult(passed=passed, feedback=response[:200])

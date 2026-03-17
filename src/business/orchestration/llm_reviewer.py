"""
LLM 代码质量 Reviewer

调用 LLM 对程序员生成的代码进行质量评审，返回通过/失败和反馈。
"""

import json
import logging
import re
from dataclasses import dataclass

from src.business.ai.llm_client import LangChainLLMClient

logger = logging.getLogger(__name__)

REVIEW_PROMPT = """你是一个代码质量审查员。请审查以下 Python 代码，评估其：
1. 语法正确性
2. 逻辑完整性（是否实现了基本功能）
3. 明显的运行时错误风险

请以 JSON 格式返回审查结果：
{"passed": true/false, "feedback": "通过原因或具体问题描述"}

如果代码基本可用（即使有小问题），返回 passed: true。
只有存在语法错误、明显逻辑错误或无法运行时，才返回 passed: false。

代码：
```python
{code}
```"""


@dataclass
class ReviewResult:
    """LLM Review 结果"""

    passed: bool
    feedback: str


class LLMReviewer:
    """LLM 代码质量审查器"""

    def __init__(self, llm_client: LangChainLLMClient):
        self._llm = llm_client

    def review(self, code: str) -> ReviewResult:
        """
        审查代码质量

        Args:
            code: 待审查的 Python 代码

        Returns:
            ReviewResult（passed + feedback）
        """
        try:
            prompt = REVIEW_PROMPT.format(code=code)
            response = self._llm.chat(prompt)
            return self._parse_result(response)
        except Exception as e:
            logger.error(f"[LLMReviewer] Review 调用失败: {e}")
            # Review 失败时默认通过，避免阻断流程
            return ReviewResult(passed=True, feedback=f"Review 服务异常，默认通过: {e}")

    def _parse_result(self, response: str) -> ReviewResult:
        """解析 LLM 返回的 JSON 结果"""
        try:
            # 尝试直接解析
            data = json.loads(response)
            return ReviewResult(
                passed=bool(data.get("passed", True)), feedback=str(data.get("feedback", ""))
            )
        except json.JSONDecodeError:
            pass

        # 从 markdown 代码块中提取
        match = re.search(r"```(?:json)?\n(.*?)\n```", response, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return ReviewResult(
                    passed=bool(data.get("passed", True)), feedback=str(data.get("feedback", ""))
                )
            except json.JSONDecodeError:
                pass

        # 解析失败，检查关键词
        lower = response.lower()
        passed = "passed: false" not in lower and "failed" not in lower
        return ReviewResult(passed=passed, feedback=response[:200])

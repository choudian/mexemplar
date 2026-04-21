from typing import Any, Mapping

from .decision import FilterDecision


class LLMNoiseJudge:
    def judge(self, request: Mapping[str, Any]) -> FilterDecision | None:
        del request
        return None

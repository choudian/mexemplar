from __future__ import annotations

import ast
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyntaxGateResult:
    ok: bool
    feedback: str | None = None
    lineno: int | None = None
    message: str | None = None


def check_code(code: str) -> SyntaxGateResult:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return SyntaxGateResult(
            ok=False,
            feedback=build_feedback(code, exc),
            lineno=exc.lineno,
            message=exc.msg,
        )
    return SyntaxGateResult(ok=True)


def _snippet(code: str, lineno: int | None, radius: int = 2) -> str:
    if lineno is None:
        return ""
    lines = code.splitlines()
    start = max(1, lineno - radius)
    end = min(len(lines), lineno + radius)
    return "\n".join(f"{index}: {lines[index - 1]}" for index in range(start, end + 1))


def build_feedback(code: str, exc: SyntaxError) -> str:
    lineno = exc.lineno or 1
    return (
        f"你之前生成的代码在 line {lineno} 出现语法错误：{exc.msg}\n\n"
        "出错位置（含上下 2 行）：\n"
        f"{_snippet(code, lineno)}\n\n"
        "请重新输出修复后的完整 `async def execute() -> dict` 函数。"
    )


def should_retry(attempt_index: int, max_retries: int = 2) -> bool:
    return attempt_index <= max_retries


def log_terminal_failure(workflow_id: str, attempts: list[str], feedbacks: list[str]) -> None:
    logger.error(
        "[desktop syntax gate] workflow=%s attempts=%d feedbacks=%d",
        workflow_id,
        len(attempts),
        len(feedbacks),
    )

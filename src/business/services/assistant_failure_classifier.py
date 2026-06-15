"""Safe, deterministic classification for terminal Assistant failures."""

from __future__ import annotations

from dataclasses import dataclass

from src.business.agents.config import ResultType


@dataclass(frozen=True)
class ClassifiedAssistantFailure:
    category: str
    message: str
    suggestion: str
    internal_code: str
    exception_type: str | None = None


_SAFE_COPY = {
    "authentication": (
        "模型服务的身份验证没有通过。",
        "请到设置中检查 API Key 或账号权限后重试。",
    ),
    "invalid_request": (
        "模型服务无法处理这次请求。",
        "可以编辑并简化请求后重试；如果持续出现，请查看调试信息。",
    ),
    "quota": (
        "模型服务当前无法继续处理额度请求。",
        "请检查额度、账单或限流状态，稍后再重试。",
    ),
    "network": (
        "连接模型服务时中断了。",
        "请检查网络连接后重试。",
    ),
    "provider": (
        "模型服务暂时不可用。",
        "请稍后重试；如果持续出现，可以查看调试信息。",
    ),
    "iteration_limit": (
        "这次处理没有在允许的步骤内完成。",
        "可以直接重试，或编辑请求以缩小任务范围。",
    ),
    "internal": (
        "处理这条消息时发生了内部错误。",
        "请重试；如果持续出现，可以查看调试信息。",
    ),
}


def classify_assistant_failure(
    *,
    result_type: ResultType | None = None,
    error: str | None = None,
    exception: BaseException | None = None,
) -> ClassifiedAssistantFailure:
    category = _classify_category(result_type=result_type, error=error, exception=exception)
    message, suggestion = _SAFE_COPY[category]
    return ClassifiedAssistantFailure(
        category=category,
        message=message,
        suggestion=suggestion,
        internal_code=f"assistant_{category}",
        exception_type=type(exception).__name__ if exception is not None else None,
    )


def _classify_category(
    *,
    result_type: ResultType | None,
    error: str | None,
    exception: BaseException | None,
) -> str:
    if result_type == ResultType.MAX_ITERATIONS_REACHED:
        return "iteration_limit"

    status_codes: list[int] = []
    names: list[str] = []
    current = exception
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        names.append(type(current).__name__.lower())
        for attr in ("status_code", "http_status", "status"):
            value = getattr(current, attr, None)
            if isinstance(value, int):
                status_codes.append(value)
        current = current.__cause__ or current.__context__

    if any(code in (401, 403) for code in status_codes):
        return "authentication"
    if 429 in status_codes:
        return "quota"
    if any(code in (400, 404, 409, 422) for code in status_codes):
        return "invalid_request"
    if any(code >= 500 for code in status_codes):
        return "provider"

    text = " ".join([error or "", *names]).lower()
    if _contains_any(
        text,
        "unauthorized",
        "authentication",
        "invalid api key",
        "api key invalid",
        "permission denied",
    ):
        return "authentication"
    if _contains_any(
        text,
        "rate limit",
        "ratelimit",
        "quota",
        "billing",
        "insufficient_quota",
        "too many requests",
    ):
        return "quota"
    if _contains_any(
        text,
        "timeout",
        "timed out",
        "connection",
        "network",
        "dns",
        "connecterror",
    ):
        return "network"
    if _contains_any(
        text,
        "bad request",
        "invalid request",
        "unprocessable",
        "context length",
        "serialization",
    ):
        return "invalid_request"
    if _contains_any(
        text,
        "service unavailable",
        "server error",
        "internal server",
        "bad gateway",
        "gateway timeout",
    ):
        return "provider"
    return "internal"


def _contains_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)

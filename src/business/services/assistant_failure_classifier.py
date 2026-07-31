"""Safe, deterministic classification for terminal Assistant failures."""

from __future__ import annotations

from dataclasses import dataclass

from src.business.agents.config import ResultType
from src.utils.helpers import walk_exception_chain


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
    # 与上面每一条的区别：那些都在说"可以再试"，这一条明说再试没用。
    # 判成这一档之后系统会停掉所有自动重试，所以文案里不能留任何重试暗示。
    "code_defect": (
        "这一步撞上程序缺陷，重试不会改变结果。",
        "可以跳过这一步或放弃这个任务；把问题上报能帮助修复。",
    ),
}


#: 分类器可能产出的全部 category。**每一个都必须能落库** —— 落不进去就意味着
#: "记录失败"这件事本身失败，而那是最坏的一类：出了事，连出事这件事都记不下来。
#: 由 tests/data/test_assistant_run_failure_repository.py 的守卫测试钉住。
KNOWN_FAILURE_CATEGORIES = frozenset(_SAFE_COPY)


# ── 代码缺陷判定 ────────────────────────────────────────────────────────
#
# 这一档回答的不是"出了什么错"，是**"再试一次有没有用"**。
# 判据：系统自己的内部契约被违反，没有外部世界参与——环境怎么变都引发不了它。
#
# 认出来之后的处置是「停止一切自动重试」，所以宁可漏不可错：
#   漏报 → 走原有分类 → 主助理试一次 → 撞重派上限才转缺陷，代价是多烧一次运行
#   误报 → 立刻停掉重试、活钉在等人，而它本来重试一次就过去了
# 因此只收「类型名本身就是证据」的那几个。FileNotFoundError（路径拼错 or 文件
# 真不在）、TimeoutError（死锁 or 网络慢）、OSError、ValueError 这类"同一个表现
# 对应多种原因"的一律不收——判不出来就交给主助理分析，别自己拍板。
_CODE_DEFECT_EXCEPTION_NAMES = (
    "typeerror",  # 类型契约被违反，而那个契约是代码写的
    "attributeerror",  # 同上，最常见的形态是在 None 上取属性
    "assertionerror",  # 定义上就是
)

# CHECK 约束是代码自己定的取值范围，写出范围外的值只可能是代码错——环境再怎么
# 变也不会让一个值突然变得不合法。7/28 实跑死在这一条上。
#
# ⚠️ UNIQUE 冲突绝不能混进来：那是并发，项目里已有 5 处把它当正常语义处理
# （assistant_task_attempt_repository.py:77 的 active attempt 抢占、board.py:116
# 的认领冲突等）。把并发判成缺陷会停掉本该重试的活。
_DEFECT_DB_MARKER = "check constraint failed"


def _is_code_defect(exception: BaseException | None) -> bool:
    """整条异常链上只要有一个确定性缺陷，就算缺陷。

    走全链是因为异常常被上层重新包装——委派执行的外层就会把任何异常裹进一个
    通用 RuntimeError，只看最外层什么都判不出来。

    按类型**名**匹配而不是 isinstance，是为了不让业务层 import SQLAlchemy；
    这也跟 ``agent_loop._is_recoverable_llm_failure`` 的既有写法一致。
    """
    for node in walk_exception_chain(exception):
        type_name = type(node).__name__.lower()
        if type_name in _CODE_DEFECT_EXCEPTION_NAMES:
            return True
        if "integrityerror" in type_name and _DEFECT_DB_MARKER in str(node).lower():
            return True
    return False


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

    # 放在所有其他判定之前：它的处置（停掉重试）跟其余每一档都相反，判错方向的
    # 代价最大；而它的判据是确定性的，不依赖 status_code 或消息关键词。
    if _is_code_defect(exception):
        return "code_defect"

    status_codes: list[int] = []
    names: list[str] = []
    for node in walk_exception_chain(exception):
        names.append(type(node).__name__.lower())
        for attr in ("status_code", "http_status", "status"):
            value = getattr(node, attr, None)
            if isinstance(value, int):
                status_codes.append(value)

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

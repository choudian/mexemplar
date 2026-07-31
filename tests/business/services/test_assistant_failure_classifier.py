from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from src.business.agents.config import ResultType
from src.business.services.assistant_failure_classifier import classify_assistant_failure


class ProviderError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _integrity_error(orig_message: str) -> IntegrityError:
    """构造一个形状与 SQLAlchemy 真实抛出物一致的 IntegrityError。"""
    return IntegrityError("UPDATE assistant_tasks SET ...", {}, Exception(orig_message))


def test_classifier_maps_failure_categories_without_exposing_raw_details() -> None:
    fixtures = [
        (ProviderError("key=sk-secret endpoint=https://provider.test", 401), "authentication"),
        (ProviderError("raw request body", 422), "invalid_request"),
        (ProviderError("billing secret", 429), "quota"),
        (TimeoutError("socket payload secret"), "network"),
        (ProviderError("upstream response secret", 503), "provider"),
    ]

    for exception, expected in fixtures:
        classified = classify_assistant_failure(exception=exception)
        public_text = " ".join(
            [
                classified.category,
                classified.message,
                classified.suggestion,
                classified.internal_code,
                classified.exception_type or "",
            ]
        )
        assert classified.category == expected
        assert "secret" not in public_text
        assert "provider.test" not in public_text
        assert "sk-" not in public_text


def test_classifier_handles_iteration_limit_and_internal_fallback() -> None:
    iteration = classify_assistant_failure(
        result_type=ResultType.MAX_ITERATIONS_REACHED,
        error="raw loop detail",
    )
    internal = classify_assistant_failure(error="unknown raw body")

    assert iteration.category == "iteration_limit"
    assert internal.category == "internal"
    assert "raw" not in iteration.message + iteration.suggestion
    assert "unknown raw body" not in internal.message + internal.suggestion


# ── 代码缺陷这一档 ──────────────────────────────────────────
#
# 判据是「系统自己的内部契约被违反，没有外部世界参与」——环境怎么变都引发不了它。
# 认出这一类的**唯一目的**是不再说"要不要再试一次"：它一定还是同一个结果。


def test_a_check_constraint_violation_is_a_code_defect() -> None:
    """CHECK 约束是代码自己定的，违反它只能是代码写错了。

    7/28 实跑就死在这条上：写 suspend_reason='budget_exhausted' 撞 CHECK 约束，
    被包装成"内部错误，需上级检查后决定是否重试"，主助理照着建议重试 7 次——
    每次都必然失败，因为代码没变。1 小时 13 分钟，0 产出。
    """
    classified = classify_assistant_failure(
        exception=_integrity_error("CHECK constraint failed: ck_assistant_tasks_suspend_reason")
    )
    assert classified.category == "code_defect"


def test_a_unique_violation_is_not_a_code_defect() -> None:
    """UNIQUE 冲突是并发，不是缺陷——项目里 5 处已把它当正常语义处理。

    两种误判的代价不对称：漏报只是多试一次；**误报会立刻停掉所有重试、把活
    钉在等人**，而它本来重试一次就过去了。所以这条边界必须守住。
    """
    classified = classify_assistant_failure(
        exception=_integrity_error("UNIQUE constraint failed: uq_one_active_attempt")
    )
    assert classified.category != "code_defect"


def test_type_contract_violations_are_code_defects() -> None:
    """这些错的共同点：被违反的契约是代码自己写的。"""
    for exception in (
        TypeError("unsupported operand type(s)"),
        AttributeError("'NoneType' object has no attribute 'status'"),
        AssertionError("invariant broken"),
    ):
        assert classify_assistant_failure(exception=exception).category == "code_defect", exception


def test_environment_failures_stay_out_of_the_defect_bucket() -> None:
    """宁可漏不可错：这些同一个表现对应多种原因，判成缺陷会误停。

    文件找不到可能是路径拼错（缺陷）也可能文件真的不在（环境）；超时可能是
    死锁（缺陷）也可能网络慢（环境）。判不出来就交给主助理分析，别自己拍板。
    """
    for exception in (
        TimeoutError("read timed out"),
        FileNotFoundError("no such file"),
        PermissionError("access denied"),
        OSError("disk full"),
        ValueError("bad value"),
    ):
        assert classify_assistant_failure(exception=exception).category != "code_defect", exception


def test_a_defect_wrapped_deeper_in_the_chain_still_counts() -> None:
    """异常常被上层重新包装，判定必须走整条 __cause__ / __context__ 链。"""
    try:
        try:
            raise TypeError("the real cause")
        except TypeError as inner:
            raise RuntimeError("委派执行内部错误") from inner
    except RuntimeError as outer:
        assert classify_assistant_failure(exception=outer).category == "code_defect"


def test_defect_copy_tells_the_reader_that_retrying_is_pointless() -> None:
    """这句文案是给主助理和用户看的。硬保证在自愈动作表（不含 retry），
    但文案本身也不能留"要不要再试"这种暗示。"""
    classified = classify_assistant_failure(exception=TypeError("x"))
    assert "重试" in classified.message
    assert "重试" not in classified.suggestion or "无用" in classified.suggestion


def test_defect_classification_leaks_nothing_from_the_original() -> None:
    classified = classify_assistant_failure(
        exception=TypeError(r"token=sk-abc123 at C:\Users\someone\config.json")
    )
    public_text = " ".join(
        [
            classified.category,
            classified.message,
            classified.suggestion,
            classified.internal_code,
            classified.exception_type or "",
        ]
    )
    assert "sk-abc123" not in public_text
    assert "someone" not in public_text
    assert "config.json" not in public_text

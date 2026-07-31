"""撞上代码缺陷时，原始异常正文只进 ERROR 日志，不进任何面向用户/主助理的字段。

这一档跟其他失败分类有个要命的差别：**它的诊断信息最有价值，因此最想被带出去**。
异常正文里往往就是出事那一刻的现场——参数值、路径、连接串。开发者需要它，
所以 ``orchestrator`` 会把完整 traceback 写进 ERROR 日志和 Debug Inspector；
但用户卡片、回流 payload、attempt 落库字段是另一回事，那几条路上只能走结论。

分类器的安全模型是"输出全部来自静态常量表"，这些测试钉的就是**那个模型没有被
绕过**——任何一次"顺手把 str(exc) 塞进 payload 让主助理多点判断依据"的改动，
都会在这里当场变红。
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.business.services.assistant_failure_classifier import classify_assistant_failure
from src.business.task_collaboration.dispatcher import _paused_reentry_payload
from src.business.task_collaboration.models import SuspendReason, WaitingOn

ROOT = Path(__file__).resolve().parents[2]

# 异常正文里塞两类真实会出事的东西：凭证和用户私有路径。
_SECRET = "sk-live-DO-NOT-LEAK"
_PRIVATE_PATH = "E:/private/customer-list.xlsx"


def _defect_exception() -> TypeError:
    """一个正文里带敏感信息的确定性缺陷。

    TypeError 走 ``_CODE_DEFECT_EXCEPTION_NAMES`` 那一档，判定不看消息内容——
    正是因为不看，才更要证明它也没把消息**带出去**。
    """
    return TypeError(f"api_key={_SECRET} while writing {_PRIVATE_PATH}")


def _leaks(text: str) -> bool:
    return _SECRET in text or _PRIVATE_PATH in text or "api_key" in text


def _all_strings(value: object) -> list[str]:
    """把嵌套结构里所有字符串摊平——payload 将来长出嵌套字段也一样被扫到。"""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.items() for v in item for s in _all_strings(v)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [s for item in value for s in _all_strings(item)]
    return []


def test_classified_defect_carries_type_name_but_never_the_message() -> None:
    classified = classify_assistant_failure(exception=_defect_exception())

    assert classified.category == "code_defect"
    # 唯一允许从异常带出去的东西：类名。它不含现场数据，却能让主助理和开发者对齐是哪一类。
    assert classified.exception_type == "TypeError"
    for field in (
        classified.category,
        classified.message,
        classified.suggestion,
        classified.internal_code,
        classified.exception_type or "",
    ):
        assert not _leaks(field), f"缺陷分类结果泄漏了异常正文: {field!r}"


def test_defect_reentry_payload_is_built_from_a_whitelist_not_passed_through() -> None:
    """主助理侧：它拿到的是"撞上缺陷了、这几个动作可选"，不是崩溃现场。

    这里**故意在上游 result 里塞满泄漏源**——模拟将来某次改动顺手加了
    ``result["raw_error"] = str(exc)`` 想给主助理多点判断依据。payload 是逐个键
    挑出来组的，不是原样透传，所以这些字段必须一个都出不去。原样透传的写法会让
    这个测试当场变红，而那正是最容易被"就加一个字段而已"绕过去的地方。
    """
    exception = _defect_exception()
    classified = classify_assistant_failure(exception=exception)

    payload = _paused_reentry_payload(
        {
            "task_id": "tsk_defect_guard",
            "suspend_reason": SuspendReason.BLOCKED_BY_DEFECT.value,
            "reentry_type": "blocked_by_defect",
            "safe_summary": "记录这一步的结果时撞上程序缺陷，重试不会改变结果。",
            "failure_exception_type": classified.exception_type,
            # ↓ 以下都是崩溃现场，任何一条都不该到达主助理
            "raw_error": str(exception),
            "error_detail": repr(exception),
            "stack": f"Traceback ...\n  File {_PRIVATE_PATH}\nTypeError: api_key={_SECRET}",
            "nested": {"provider_response": {"key": _SECRET}},
        }
    )

    assert payload is not None, "缺陷暂停必须叫醒主助理——没人被告知是最坏的结局"
    for text in _all_strings(payload):
        assert not _leaks(text), f"回流 payload 泄漏了异常正文: {text!r}"
    # 正向：该带的结论带到了，否则上面的"没泄漏"可能只是因为 payload 是空的。
    assert payload["failureExceptionType"] == "TypeError"
    assert "retry" not in payload["healingActions"]


def test_defect_pause_reaches_the_assistant_not_the_user() -> None:
    """用户处理不了代码缺陷，所以这条通知不该指向他——他只被告知，不被要求动作。"""
    assert (
        _paused_reentry_payload(
            {
                "task_id": "tsk_defect_route",
                "suspend_reason": SuspendReason.BLOCKED_BY_DEFECT.value,
                "reentry_type": "blocked_by_defect",
            }
        )
        is not None
    )

    from src.business.task_collaboration.models import waiting_on_for_reason

    assert waiting_on_for_reason(SuspendReason.BLOCKED_BY_DEFECT) == WaitingOn.ASSISTANT


def test_user_facing_defect_copy_is_a_constant_free_of_internal_terms() -> None:
    """用户卡片上那一句：不含现场数据，也不含内部词汇。"""
    from src.business.task_collaboration.service import _DEFECT_EXPLANATION

    assert not _leaks(_DEFECT_EXPLANATION)
    for internal_term in ("defect", "exception", "TypeError", "traceback", "attempt"):
        assert internal_term.lower() not in _DEFECT_EXPLANATION.lower(), (
            f"用户文案出现内部术语 {internal_term!r}：{_DEFECT_EXPLANATION!r}"
        )


def _module_level_assignment(source: str, name: str) -> ast.expr:
    tree = ast.parse(source)
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        for target in targets:
            if isinstance(target, ast.Name) and target.id == name:
                return node.value
    raise AssertionError(f"找不到模块级赋值 {name}")


def test_crash_recovery_copy_is_a_literal_not_an_interpolation() -> None:
    """记账崩溃时的收尾文案必须是**字面量**。

    那次崩溃很可能正是因为某个动态值有问题（写了违约的值、拼了个序列化不了的
    对象）。收尾时再去拼一个新的字符串，等于拿同一把枪再开一次——而这一次没有
    人接着了，活会一直卡在那儿。
    """
    source = (ROOT / "src/business/task_collaboration/dispatcher.py").read_text(encoding="utf-8")

    for name in ("_DEFECT_RECORDING_SUMMARY", "_DEFECT_RECOVERY_HINT"):
        value = _module_level_assignment(source, name)
        assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
            f"{name} 必须是纯字符串字面量，不能是 f-string / .format / % 拼接"
        )
        assert not _leaks(value.value)

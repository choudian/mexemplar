"""SafetyGovernor 行为单测（026 测试审查 I5）。

check_rate_limit / record_effectiveness_delta / check_regressive_change /
should_allow_action 此前零直接行为测试（仅被 MagicMock 替身）。覆盖 None
metric、阈值边界、3 点收敛窗口、无效配置默认值等高风险分支。

注：SafetyGovernor 是 fail-open 策略——rate limit 配置异常时放行（避免一次拼写
错误瘫痪所有自我改进），但回滚检测仍独立评估（review errors 审查确认非 fail-open）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.business.self_improvement import safety_governor as sg_module
from src.business.self_improvement.safety_governor import SafetyGovernor


def _config(
    *,
    max_prompt: int = 10,
    max_tool: int = 5,
    max_reflection: int = 20,
    convergence: float = 0.01,
    degradation: float = 0.10,
) -> MagicMock:
    cfg = MagicMock()
    cfg.get_self_improvement_max_prompt_supplements_per_day = lambda: max_prompt
    cfg.get_self_improvement_max_tool_creations_per_day = lambda: max_tool
    cfg.get_self_improvement_max_reflections_per_session = lambda: max_reflection
    cfg.get_self_improvement_convergence_threshold = lambda: convergence
    cfg.get_self_improvement_degradation_threshold = lambda: degradation
    return cfg


def _governor(
    monkeypatch, *, count_today: int = 0, config: MagicMock | None = None
) -> SafetyGovernor:
    repo = MagicMock()
    repo.count_actions_today.return_value = count_today
    monkeypatch.setattr(sg_module, "get_unified_config", lambda: config or _config())
    return SafetyGovernor(repo=repo)


# --- check_rate_limit ---


def test_rate_limit_unknown_action_unrestricted(monkeypatch) -> None:
    gov = _governor(monkeypatch)
    assert gov.check_rate_limit("not_a_real_action") is True


def test_rate_limit_under_cap_allowed(monkeypatch) -> None:
    gov = _governor(monkeypatch, count_today=4)
    assert gov.check_rate_limit(SafetyGovernor.TOOL_AUTO_CREATED) is True


def test_rate_limit_at_cap_blocked(monkeypatch) -> None:
    """current >= max 即阻断（边界：恰好等于）。"""
    gov = _governor(monkeypatch, count_today=5)
    assert gov.check_rate_limit(SafetyGovernor.TOOL_AUTO_CREATED) is False


def test_rate_limit_invalid_config_fail_open(monkeypatch) -> None:
    """无效 rate 配置不得瘫痪自我改进 -> fail-open 放行（026 I5）。"""
    gov = _governor(monkeypatch, config=_config(max_tool="not-a-number"))  # type: ignore[arg-type]
    assert gov.check_rate_limit(SafetyGovernor.TOOL_AUTO_CREATED) is True


# --- record_effectiveness_delta / convergence ---


def test_convergence_needs_three_samples(monkeypatch) -> None:
    gov = _governor(monkeypatch)
    assert gov.record_effectiveness_delta(0.001) is True
    assert gov.record_effectiveness_delta(0.001) is True  # 仅 2 个采样，仍 improving


def test_convergence_detected_when_last_three_below_threshold(monkeypatch) -> None:
    gov = _governor(monkeypatch)
    gov.record_effectiveness_delta(0.5)  # 早期大改进不影响
    gov.record_effectiveness_delta(0.005)
    gov.record_effectiveness_delta(0.005)
    # 第 3 个低于阈值的小 delta -> 收敛
    assert gov.record_effectiveness_delta(0.005) is False


def test_convergence_not_triggered_when_third_delta_large(monkeypatch) -> None:
    """3 点窗口边界：最后一个 delta 大于阈值 -> 仍未收敛。"""
    gov = _governor(monkeypatch)
    gov.record_effectiveness_delta(0.005)
    gov.record_effectiveness_delta(0.005)
    assert gov.record_effectiveness_delta(0.5) is True


def test_convergence_invalid_threshold_defaults_to_zero_dot_01(monkeypatch) -> None:
    """无效 convergence 配置回退默认 0.01（026 I5）。"""
    gov = _governor(monkeypatch, config=_config(convergence="bad"))
    gov.record_effectiveness_delta(0.005)
    gov.record_effectiveness_delta(0.005)
    # 默认 0.01 下，0.005 < 0.01 -> 收敛
    assert gov.record_effectiveness_delta(0.005) is False


# --- check_regressive_change ---


def test_regressive_none_metrics_skip(monkeypatch) -> None:
    gov = _governor(monkeypatch)
    assert gov.check_regressive_change(None, 0.5) is False
    assert gov.check_regressive_change(0.5, None) is False


def test_regressive_small_drop_not_triggered(monkeypatch) -> None:
    """6.25% 降幅 (< 10% 阈值) -> 不回滚。"""
    gov = _governor(monkeypatch)
    assert gov.check_regressive_change(0.8, 0.75) is False


def test_regressive_large_drop_triggered(monkeypatch) -> None:
    """12.5% 降幅 (> 10% 阈值) -> 回滚。"""
    gov = _governor(monkeypatch)
    assert gov.check_regressive_change(0.8, 0.7) is True


def test_regressive_exactly_at_threshold_not_triggered(monkeypatch) -> None:
    """边界：恰好等于阈值降幅不触发（严格小于才回滚）。

    用 10.0 -> 9.0 避免 0-1 区间的浮点误差：(9-10)/10 精确等于 -0.1。
    """
    gov = _governor(monkeypatch)
    assert gov.check_regressive_change(10.0, 9.0) is False


def test_regressive_improvement_not_triggered(monkeypatch) -> None:
    gov = _governor(monkeypatch)
    assert gov.check_regressive_change(0.5, 0.8) is False


def test_regressive_invalid_threshold_defaults_to_zero_dot_10(monkeypatch) -> None:
    """无效 degradation 配置回退默认 0.10（026 I5）。"""
    gov = _governor(monkeypatch, config=_config(degradation="bad"))
    # 12.5% 降幅在默认 0.10 下触发回滚
    assert gov.check_regressive_change(0.8, 0.7) is True


# --- should_allow_action (combined) ---


def test_should_allow_action_allowed(monkeypatch) -> None:
    gov = _governor(monkeypatch, count_today=0)
    allowed, reason = gov.should_allow_action(SafetyGovernor.PROMPT_SUPPLEMENT_CREATED)
    assert allowed is True
    assert reason == ""


def test_should_allow_action_blocked_by_rate_limit(monkeypatch) -> None:
    gov = _governor(monkeypatch, count_today=10)
    allowed, reason = gov.should_allow_action(SafetyGovernor.PROMPT_SUPPLEMENT_CREATED)
    assert allowed is False
    assert "Rate limit" in reason


def test_should_allow_action_blocked_by_convergence(monkeypatch) -> None:
    gov = _governor(monkeypatch)
    gov.record_effectiveness_delta(0.005)
    gov.record_effectiveness_delta(0.005)
    gov.record_effectiveness_delta(0.005)  # 第 3 次触发收敛
    allowed, reason = gov.should_allow_action(SafetyGovernor.PROMPT_SUPPLEMENT_CREATED)
    assert allowed is False
    assert "Convergence" in reason

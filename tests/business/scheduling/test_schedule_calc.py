"""Tests for schedule_calc.compute_next_fire / describe_schedule（033）。

覆盖 one_shot 立即意图（'now' 兜底，US1）、ISO 解析、interval / daily / weekly /
weekdays 滚动，与 describe_schedule 人话输出。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.business.scheduling import schedule_calc as schedule_calc_module
from src.business.scheduling.schedule_calc import (
    compute_next_fire,
    describe_schedule,
    validate_schedule_payload,
)
from src.utils.timezone import utc_now_naive

# ---------------------------------------------------------------------------
# one_shot 立即意图（US1 关键：LLM 拿不到当前 ISO，'now' 由函数兜底）
# ---------------------------------------------------------------------------


def test_one_shot_now_resolves_to_current_moment():
    before = utc_now_naive()
    fired = compute_next_fire({"run_at": "now"}, after_local=utc_now_naive())
    after = utc_now_naive()
    assert fired is not None
    # 立即触发时刻落在 [before, after] 内
    assert before - timedelta(seconds=1) <= fired <= after + timedelta(seconds=1)


def test_one_shot_immediate_synonyms_resolve_to_now():
    for synonym in ["now", "NOW", "immediate", "immediately", "asap", "立即", "立刻", "马上"]:
        fired = compute_next_fire({"run_at": synonym}, after_local=utc_now_naive())
        assert fired is not None, f"synonym {synonym!r} should resolve to now"


def test_one_shot_iso_naive_uses_system_local_timezone(monkeypatch):
    """无 offset / tz 的 ISO 按桌面用户本地时区解释，与工具契约一致。"""
    monkeypatch.setattr(
        schedule_calc_module,
        "_get_localzone",
        lambda: ZoneInfo("Asia/Shanghai"),
    )

    fired = compute_next_fire({"run_at": "2026-07-19T17:00:00"}, after_local=utc_now_naive())
    assert fired == datetime(2026, 7, 19, 9, 0, 0)


def test_system_local_timezone_runtime_dependency_is_available():
    """生产缺省路径必须有真实时区发现器，不能靠 UTC fallback 伪装成功。"""
    assert schedule_calc_module._get_localzone is not None
    resolved = schedule_calc_module._resolve_tz(None)
    assert resolved.utcoffset(datetime.now()) is not None


@pytest.mark.parametrize("failure_mode", ["missing", "raises"])
def test_system_local_timezone_resolution_failure_is_fail_closed(
    monkeypatch,
    caplog,
    failure_mode,
):
    if failure_mode == "missing":
        monkeypatch.setattr(schedule_calc_module, "_get_localzone", None)
    else:

        def _raise_lookup_error():
            raise RuntimeError("timezone lookup failed")

        monkeypatch.setattr(schedule_calc_module, "_get_localzone", _raise_lookup_error)

    with caplog.at_level("ERROR", logger=schedule_calc_module.__name__):
        with pytest.raises(ValueError, match="schedule_payload does not produce"):
            validate_schedule_payload(
                "one_shot",
                {"run_at": "2026-07-19T17:00:00"},
                after=utc_now_naive(),
            )

    assert "system local timezone" in caplog.text


def test_one_shot_iso_with_tz_converted_to_utc_naive():
    # 带偏移的 ISO → UTC naive（+08:00 的 18:00 = UTC 10:00）
    fired = compute_next_fire({"run_at": "2026-07-19T18:00:00+08:00"}, after_local=utc_now_naive())
    assert fired is not None
    assert fired.hour == 10
    assert fired.tzinfo is None  # naive UTC


def test_one_shot_naive_iso_with_named_timezone_is_interpreted_as_local():
    fired = compute_next_fire(
        {
            "run_at": "2026-07-19T18:00:00",
            "tz": "Asia/Shanghai",
        },
        after_local=utc_now_naive(),
    )

    assert fired == datetime(2026, 7, 19, 10, 0, 0)
    assert (
        describe_schedule(
            "one_shot",
            {
                "run_at": "2026-07-19T18:00:00",
                "tz": "Asia/Shanghai",
            },
        )
        == "一次性 7月19日 18:00"
    )


def test_one_shot_nonexistent_dst_time_moves_forward_and_logs(caplog):
    """春季跳时中的本地时刻按 DST gap 向后推进，不生成 imaginary datetime。"""
    with caplog.at_level("WARNING", logger=schedule_calc_module.__name__):
        fired = compute_next_fire(
            {
                "run_at": "2026-03-08T02:30:00",
                "tz": "America/New_York",
            },
            after_local=utc_now_naive(),
        )

    assert fired == datetime(2026, 3, 8, 7, 30)
    local = fired.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (3, 30)
    assert "nonexistent local time" in caplog.text


def test_one_shot_invalid_run_at_returns_none():
    assert compute_next_fire({"run_at": "next tuesday"}, after_local=utc_now_naive()) is None
    assert compute_next_fire({"run_at": ""}, after_local=utc_now_naive()) is None


def test_explicit_invalid_timezone_is_rejected_by_business_validator():
    with pytest.raises(ValueError, match="valid IANA"):
        validate_schedule_payload(
            "one_shot",
            {
                "run_at": "2099-01-01T12:00:00",
                "tz": "Mars/Olympus_Mons",
            },
            after=utc_now_naive(),
        )


# ---------------------------------------------------------------------------
# interval / daily / weekly / weekdays 滚动
# ---------------------------------------------------------------------------


def test_interval_seconds_rolls_to_future():
    after = utc_now_naive()
    fired = compute_next_fire({"interval_seconds": 3600}, after_local=after)
    assert fired is not None
    assert fired > after
    assert (fired - after) <= timedelta(seconds=3600 + 1)


def test_interval_contract_kind_is_accepted():
    after = utc_now_naive()
    fired = validate_schedule_payload(
        "recurring",
        {"kind": "interval", "interval_seconds": 60},
        after=after,
    )
    assert fired == after + timedelta(seconds=60)


@pytest.mark.parametrize(
    "payload",
    [
        {"interval_seconds": 1.5},
        {"interval_seconds": "1.5"},
        {"interval_seconds": True},
        {"interval_seconds": 0},
        {"interval_seconds": 10**100},
        {"kind": "weekly", "weekdays": 1, "time_of_day": "09:00"},
        {"kind": "weekly", "weekdays": ["Monday"], "time_of_day": "09:00"},
    ],
)
def test_invalid_boundary_payload_returns_none_without_throwing(payload):
    assert compute_next_fire(payload, after_local=utc_now_naive()) is None


def test_daily_time_of_day_returns_future_local_occurrence():
    # 用固定 tz（Asia/Shanghai UTC+8）；每天 09:00 本地
    after = utc_now_naive()
    fired = compute_next_fire(
        {"kind": "daily", "time_of_day": "09:00", "tz": "Asia/Shanghai"},
        after_local=after,
    )
    assert fired is not None
    # 未来时刻
    from datetime import timezone

    asia = timezone(timedelta(hours=8))
    local = fired.replace(tzinfo=timezone.utc).astimezone(asia)
    assert local.hour == 9 and local.minute == 0


def test_daily_ambiguous_dst_time_uses_fold_zero_and_logs(caplog):
    """秋季重复时刻取 fold=0（较早实例），并留下可诊断记录。"""
    with caplog.at_level("WARNING", logger=schedule_calc_module.__name__):
        fired = compute_next_fire(
            {
                "kind": "daily",
                "time_of_day": "01:30",
                "tz": "America/New_York",
            },
            after_local=datetime(2026, 10, 31, 12, 0),
        )

    assert fired == datetime(2026, 11, 1, 5, 30)
    local = fired.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute, local.fold) == (1, 30, 0)
    assert "ambiguous local time" in caplog.text


def test_daily_nonexistent_dst_time_moves_forward_and_logs(caplog):
    """日历任务遇到春季 DST gap 时推进到 gap 后等距的真实时刻。"""
    with caplog.at_level("WARNING", logger=schedule_calc_module.__name__):
        fired = compute_next_fire(
            {
                "kind": "daily",
                "time_of_day": "02:30",
                "tz": "America/New_York",
            },
            after_local=datetime(2026, 3, 7, 12, 0),
        )

    assert fired == datetime(2026, 3, 8, 7, 30)
    local = fired.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/New_York"))
    assert (local.hour, local.minute) == (3, 30)
    assert "nonexistent local time" in caplog.text


def test_weekdays_returns_monday_through_friday_only():
    asia = timezone(timedelta(hours=8))
    # 选一个周六作为 after，下次应是周一
    saturday_utc = (
        datetime(2026, 7, 18, 12, 0, 0, tzinfo=asia).astimezone(timezone.utc).replace(tzinfo=None)
    )
    fired = compute_next_fire(
        {"kind": "weekdays", "time_of_day": "09:00", "tz": "Asia/Shanghai"},
        after_local=saturday_utc,
    )
    assert fired is not None
    local = fired.replace(tzinfo=timezone.utc).astimezone(asia)
    assert local.weekday() == 0  # Monday
    assert local.hour == 9


def test_weekly_specific_weekday():
    asia = timezone(timedelta(hours=8))
    # weekly 周一/三/五 08:00，从周一 12:00 后应滚到周三
    after = (
        datetime(2026, 7, 13, 12, 0, 0, tzinfo=asia).astimezone(timezone.utc).replace(tzinfo=None)
    )
    fired = compute_next_fire(
        {"kind": "weekly", "weekdays": [1, 3, 5], "time_of_day": "08:00", "tz": "Asia/Shanghai"},
        after_local=after,
    )
    assert fired is not None
    local = fired.replace(tzinfo=timezone.utc).astimezone(asia)
    assert local.weekday() == 2  # Wednesday
    assert local.hour == 8


# ---------------------------------------------------------------------------
# describe_schedule 人话输出（确认卡核对）
# ---------------------------------------------------------------------------


def test_describe_one_shot_now():
    desc = describe_schedule("one_shot", {"run_at": "now"})
    assert "一次性" in desc


def test_describe_daily():
    desc = describe_schedule(
        "daily", {"kind": "daily", "time_of_day": "09:00", "tz": "Asia/Shanghai"}
    )
    assert "每天" in desc and "09:00" in desc


def test_describe_interval():
    assert describe_schedule("recurring", {"interval_seconds": 3600}) == "每隔 1 小时"
    assert describe_schedule("recurring", {"interval_seconds": 1800}) == "每隔 30 分钟"
    assert describe_schedule("recurring", {"interval_seconds": 1.5}) == "周期任务（间隔非法）"


def test_describe_invalid_weekdays_never_throws():
    assert (
        describe_schedule(
            "recurring",
            {"kind": "weekly", "weekdays": "1", "time_of_day": "09:00"},
        )
        == "每周 09:00"
    )

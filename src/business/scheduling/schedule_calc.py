"""调度时刻计算与人话描述（纯函数，无 IO）。

本模块是 033 调度中心的「时间算盘」：

- ``compute_next_fire``：根据 ``schedule_payload`` 计算严格晚于参考时刻的首个触发时刻
  （UTC naive）。支持 one_shot / interval / daily / weekly / weekdays 五种形态。
- ``describe_schedule``：把调度参数翻译成用户可核对的人话（用于创建确认卡展示）。

时区语义：``time_of_day`` / ``weekdays`` 是用户本地时区语义（「每天 9 点」=本地 9 点）。
``tz`` 字段提供 IANA 名；缺省由 ``tzlocal.get_localzone()`` 发现系统本地时区，发现失败
则 fail-closed。用 ``zoneinfo`` 把本地时点转 UTC naive 存储。DST ambiguous 取
``fold=0``；nonexistent 按 gap 向后推进；两者均记 warning（research.md R2）。

``schedule_payload.run_at`` 保留用户意图：naive 值按显式 ``tz`` 或系统本地时区解释，
aware 值服从自身 offset；持久化的 ``next_fire_at`` / ``last_fired_at`` 才统一为 UTC
naive（项目 ``utc_now_naive``）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from tzlocal import get_localzone as _get_localzone
except ImportError:  # pragma: no cover - 打包/安装漏依赖时由 _resolve_tz fail-closed
    _get_localzone = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _resolve_tz(tz_name: str | None):
    """解析 IANA 时区名；缺失或非法时使用桌面系统本地时区。

    本地时区发现不可用时抛 ``ValueError``，绝不静默回退 UTC；否则非 UTC 用户的
    naive wall time 会在错误时刻执行。
    """
    if tz_name:
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning("schedule_calc: unknown tz %r, falling back to local", tz_name)
        except Exception:  # pragma: no cover - 防御性
            logger.warning("schedule_calc: invalid tz %r, falling back to local", tz_name)
    if _get_localzone is None:
        logger.error(
            "schedule_calc: system local timezone unavailable because tzlocal is not installed"
        )
        raise ValueError("system local timezone could not be resolved")
    try:
        local_tz = _get_localzone()
        if isinstance(local_tz, ZoneInfo):
            return local_tz
        return ZoneInfo(str(local_tz))
    except Exception as exc:
        logger.error("schedule_calc: system local timezone resolution failed", exc_info=True)
        raise ValueError("system local timezone could not be resolved") from exc


def _is_valid_tz_name(value: Any) -> bool:
    """显式 tz 必须是可解析的非空 IANA 名；缺省由调用方走本地时区。"""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        ZoneInfo(value.strip())
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return False
    return True


def _to_utc_naive(dt: datetime) -> datetime:
    """aware datetime → naive UTC；naive 视为 UTC naive 原样返回。"""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def _localize_wall_time(value: datetime, tz) -> datetime:
    """把本地 wall time 确定性绑定到时区，并显式处理 DST 边界。

    ambiguous 时刻选择 ``fold=0``（较早实例）；nonexistent 时刻按 DST gap
    向后推进到对应的真实本地时刻。两种修正都会记 warning，避免调度偏移静默发生。
    """
    naive = value.replace(tzinfo=None)
    fold_zero = naive.replace(tzinfo=tz, fold=0)
    fold_one = naive.replace(tzinfo=tz, fold=1)
    normalized_zero = fold_zero.astimezone(timezone.utc).astimezone(tz)
    normalized_one = fold_one.astimezone(timezone.utc).astimezone(tz)
    zero_wall = normalized_zero.replace(tzinfo=None)
    one_wall = normalized_one.replace(tzinfo=None)
    zero_valid = zero_wall == naive
    one_valid = one_wall == naive
    tz_label = getattr(tz, "key", str(tz))

    if zero_valid:
        if one_valid and fold_zero.utcoffset() != fold_one.utcoffset():
            logger.warning(
                "schedule_calc: ambiguous local time %s in %s; using fold=0",
                naive.isoformat(),
                tz_label,
            )
        return fold_zero
    if one_valid:
        return fold_one

    forward_candidates = [
        candidate
        for candidate in (normalized_zero, normalized_one)
        if candidate.replace(tzinfo=None) > naive
    ]
    shifted = (
        min(forward_candidates, key=lambda candidate: candidate.replace(tzinfo=None))
        if forward_candidates
        else normalized_zero
    )
    logger.warning(
        "schedule_calc: nonexistent local time %s in %s; shifted forward to %s",
        naive.isoformat(),
        tz_label,
        shifted.replace(tzinfo=None).isoformat(),
    )
    return shifted


def _parse_run_at(value: Any, tz_name: str | None = None) -> datetime | None:
    """解析 one_shot 的 ``run_at``（ISO 字符串，可能带 tz）→ UTC naive。

    带偏移的 ISO 直接转 UTC；naive ISO 按 payload 显式 ``tz`` 或桌面系统本地时区
    解释。非字符串 / 非法 ISO 返回 None（由调用方决定是否报错）。
    立即触发意图（``now`` / ``immediate`` / ``asap`` / ``立刻`` / ``立即`` / ``马上``，
    大小写不敏感）一律解析为 ``utc_now_naive()``——LLM 无法可靠知道当前 ISO 时刻，
    「现在就执行」由本函数兜底，避免立即任务因拿不到时间戳而永不触发（US1）。
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = _localize_wall_time(value, _resolve_tz(tz_name))
        return _to_utc_naive(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.lower() in {"now", "immediate", "immediately", "asap", "立刻", "立即", "马上"}:
        from src.utils.timezone import utc_now_naive

        return utc_now_naive()
    candidate = _parse_iso(text)
    if candidate is None:
        logger.warning("schedule_calc: cannot parse run_at=%r", value)
        return None
    if candidate.tzinfo is None:
        candidate = _localize_wall_time(candidate, _resolve_tz(tz_name))
    return _to_utc_naive(candidate)


def _parse_iso(text: str) -> datetime | None:
    """容忍 ``Z`` / 偏移 / naive 三种 ISO 形式。"""
    cleaned = text.replace("Z", "+00:00") if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _parse_time_of_day(value: Any) -> tuple[int, int] | None:
    """解析 ``"HH:MM"`` → (hour, minute)；非法返回 None。"""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) != 2:
        return None
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _parse_interval_seconds(value: Any) -> int | None:
    """解析正整数秒数，拒绝 bool、浮点截断和小数字符串。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdecimal():
            return None
        try:
            seconds = int(text)
        except (TypeError, ValueError):
            return None
    else:
        return None
    return seconds if seconds > 0 else None


def _compute_interval(after_utc_naive: datetime, interval_seconds: int) -> datetime | None:
    """interval 形态：``after + interval``（对齐到 interval 粒度，下次滚动复用）。"""
    if interval_seconds <= 0:
        return None
    # 严格晚于 after：第一次触发直接 after + interval。
    try:
        return after_utc_naive + timedelta(seconds=interval_seconds)
    except (OverflowError, TypeError):
        return None


def compute_next_interval_from_anchor(
    payload: dict,
    *,
    anchor: datetime,
    after: datetime,
) -> datetime | None:
    """按原计划节拍推进 interval，返回严格晚于 ``after`` 的首个时点。

    ``anchor`` 是上一次计划触发点（通常为触发前的 ``next_fire_at``），不是 worker
    实际醒来的时刻。这样 app 晚启动或扫描延迟只会跳过错过的格点，不会把整个周期
    永久平移。非法形态或 datetime 溢出返回 ``None``，由业务入口 fail-closed。
    """
    if not isinstance(payload, dict) or not isinstance(anchor, datetime):
        return None
    if not isinstance(after, datetime):
        return None
    interval_seconds = _parse_interval_seconds(payload.get("interval_seconds"))
    if interval_seconds is None:
        return None
    if anchor > after:
        return anchor
    try:
        interval = timedelta(seconds=interval_seconds)
        steps = ((after - anchor) // interval) + 1
        return anchor + (interval * steps)
    except (OverflowError, TypeError, ZeroDivisionError):
        return None


def _next_local_occurrence(
    after_utc_naive: datetime, tz: ZoneInfo, predicate, *, max_iter: int = 10
) -> datetime | None:
    """从 ``after`` 开始按本地日历逐日推进，找首个满足 ``predicate(local_aware)`` 且
    严格大于 ``after`` 的本地时点，转 UTC naive 返回。

    ``predicate`` 收当日 local_aware datetime，返回 ``datetime | None``：若当日有合法
    触发时刻返回该 aware datetime，否则 None。
    """
    after_aware = after_utc_naive.replace(tzinfo=timezone.utc).astimezone(tz)
    # 从「after 当天」开始逐日查；当天可能就有未过的时点。
    base_date = after_aware.date()
    for i in range(max_iter + 1):
        candidate_date = base_date + timedelta(days=i)
        candidate = predicate(tz, candidate_date)
        if candidate is None:
            continue
        try:
            candidate_utc = candidate.astimezone(timezone.utc)
        except Exception:  # pragma: no cover - 防御性
            continue
        # 严格大于 after（UTC 口径比较）
        if candidate_utc > after_aware.astimezone(timezone.utc):
            return candidate_utc.replace(tzinfo=None)
    return None


def _daily_predicate(hour: int, minute: int):
    def _fn(tz: ZoneInfo, date):
        return _localize_wall_time(
            datetime(date.year, date.month, date.day, hour, minute),
            tz,
        )

    return _fn


def _parse_weekdays(value: Any) -> list[int] | None:
    """解析 ISO weekday JSON 数组；任一元素非法则整体拒绝。"""
    if not isinstance(value, list) or not value:
        return None
    iso_days: set[int] = set()
    for value_item in value:
        if isinstance(value_item, bool) or not isinstance(value_item, int):
            return None
        if not 1 <= value_item <= 7:
            return None
        iso_days.add(value_item)
    return sorted(iso_days) or None


def _weekly_predicate(weekdays: Any, hour: int, minute: int):
    # ISO 周一=1..周日=7；Python date.isoweekday() 同口径。
    parsed_days = _parse_weekdays(weekdays)
    if parsed_days is None:
        return None
    iso_days = set(parsed_days)

    def _fn(tz: ZoneInfo, date):
        if date.isoweekday() not in iso_days:
            return None
        return _localize_wall_time(
            datetime(date.year, date.month, date.day, hour, minute),
            tz,
        )

    return _fn


def compute_next_fire(payload: dict, after_local: datetime) -> datetime | None:
    """计算严格晚于 ``after_local`` 的下一个触发时刻（UTC naive）。

    Args:
        payload: ``schedule_payload`` dict。形态见模块 docstring。
        after_local: 参考时刻（**UTC naive**，参数名沿用契约；调用方传 ``utc_now_naive()``）。

    Returns:
        UTC naive datetime，或 None（payload 形态无法识别）。

    Notes:
        - one_shot：直接返回 ``run_at`` 解析结果（即便已过去，misfire 补跑由 worker 决定）。
        - 其余形态：滚动到严格晚于 ``after_local`` 的首个未来时点。
    """
    if not isinstance(payload, dict):
        return None

    # one_shot：run_at
    if "run_at" in payload:
        return _parse_run_at(payload.get("run_at"), payload.get("tz"))

    # interval：interval_seconds
    if "interval_seconds" in payload:
        interval_seconds = _parse_interval_seconds(payload.get("interval_seconds"))
        if interval_seconds is None:
            return None
        return _compute_interval(after_local, interval_seconds)

    # daily / weekly / weekdays：kind + time_of_day (+ weekdays) + tz
    kind = payload.get("kind")
    time_of_day = payload.get("time_of_day")
    hm = _parse_time_of_day(time_of_day)
    if hm is None:
        return None
    hour, minute = hm
    tz = _resolve_tz(payload.get("tz"))

    if kind == "daily":
        return _next_local_occurrence(after_local, tz, _daily_predicate(hour, minute))
    if kind == "weekdays":
        return _next_local_occurrence(
            after_local, tz, _weekly_predicate([1, 2, 3, 4, 5], hour, minute) or (lambda *_: None)
        )
    if kind == "weekly":
        weekdays = payload.get("weekdays")
        predicate = _weekly_predicate(weekdays, hour, minute)
        if predicate is None:
            return None
        return _next_local_occurrence(after_local, tz, predicate)

    return None


def validate_schedule_payload(
    schedule_kind: str,
    payload: dict[str, Any],
    *,
    after: datetime,
) -> datetime:
    """校验 outer kind 与 payload 形态并返回权威下次触发时刻。

    ``compute_next_fire`` 保持宽松的纯计算 API（非法输入返回 ``None``）；所有业务入口
    必须走本函数，把非法/歧义形态统一折叠为安全的 ``ValueError``。interval 同时兼容
    历史 ``{"interval_seconds": N}`` 与工具契约
    ``{"kind": "interval", "interval_seconds": N}``。
    """
    if not isinstance(payload, dict):
        raise ValueError("schedule_payload must be an object")
    if not isinstance(after, datetime):
        raise ValueError("schedule reference time must be a datetime")
    if "tz" in payload and not _is_valid_tz_name(payload.get("tz")):
        raise ValueError("tz must be a valid IANA timezone name")

    if schedule_kind == "one_shot":
        if "run_at" not in payload:
            raise ValueError("one_shot schedule requires run_at")
        recurring_fields = {"kind", "interval_seconds", "time_of_day", "weekdays"}
        if recurring_fields.intersection(payload):
            raise ValueError("one_shot schedule cannot contain recurring fields")
    elif schedule_kind == "recurring":
        if "run_at" in payload:
            raise ValueError("recurring schedule cannot contain run_at")

        kind = payload.get("kind")
        if "interval_seconds" in payload:
            if kind not in (None, "interval"):
                raise ValueError("interval schedule kind must be interval")
            if "time_of_day" in payload or "weekdays" in payload:
                raise ValueError("interval schedule cannot contain calendar fields")
            if _parse_interval_seconds(payload.get("interval_seconds")) is None:
                raise ValueError("interval_seconds must be a positive whole number")
        else:
            if kind not in {"daily", "weekly", "weekdays"}:
                raise ValueError("recurring schedule requires an interval or calendar shape")
            if _parse_time_of_day(payload.get("time_of_day")) is None:
                raise ValueError("calendar schedule requires a valid time_of_day")
            if kind == "weekly":
                if _parse_weekdays(payload.get("weekdays")) is None:
                    raise ValueError("weekly schedule requires weekdays from 1 to 7")
            elif "weekdays" in payload:
                raise ValueError("only weekly schedule may contain weekdays")
    else:
        raise ValueError("schedule_kind must be one_shot or recurring")

    try:
        next_fire = compute_next_fire(payload, after)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError("schedule_payload does not produce a valid trigger time") from exc
    if next_fire is None:
        raise ValueError("schedule_payload does not produce a valid trigger time")
    if schedule_kind == "recurring" and next_fire <= after:
        raise ValueError("recurring schedule must advance to a future trigger time")
    return next_fire


def describe_schedule(schedule_kind: str, payload: dict, tz_name: str | None = None) -> str:
    """把调度参数翻译成人话（用于确认卡核对，防「9点」听成 21 点等歧义）。"""
    if not isinstance(payload, dict):
        return "未知调度"
    if schedule_kind == "one_shot":
        run_at = _parse_run_at(payload.get("run_at"), tz_name or payload.get("tz"))
        if run_at is None:
            return "一次性任务（时间未解析）"
        tz = _resolve_tz(tz_name or payload.get("tz"))
        local_aware = run_at.replace(tzinfo=timezone.utc).astimezone(tz)
        return f"一次性 {local_aware.month}月{local_aware.day}日 {local_aware.hour:02d}:{local_aware.minute:02d}"

    if "interval_seconds" in payload:
        seconds = _parse_interval_seconds(payload.get("interval_seconds"))
        if seconds is None:
            return "周期任务（间隔非法）"
        if seconds >= 3600 and seconds % 3600 == 0:
            hours = seconds // 3600
            return f"每隔 {hours} 小时"
        if seconds >= 60 and seconds % 60 == 0:
            minutes = seconds // 60
            return f"每隔 {minutes} 分钟"
        return f"每隔 {seconds} 秒"

    kind = payload.get("kind")
    hm = _parse_time_of_day(payload.get("time_of_day"))
    if hm is None:
        return "周期任务（时间未解析）"
    hour, minute = hm
    time_str = f"{hour:02d}:{minute:02d}"
    tz = _resolve_tz(tz_name or payload.get("tz"))
    # 用今天日期展示 time_of_day 在本地时区的语义（DST 展示取 fold=0）
    today_local = datetime.now(timezone.utc).astimezone(tz)
    sample = datetime(
        today_local.year, today_local.month, today_local.day, hour, minute, tzinfo=tz, fold=0
    )
    _ = sample  # 仅用于触发 tz 解析校验，不直接展示

    if kind == "daily":
        return f"每天 {time_str}"
    if kind == "weekdays":
        return f"工作日 {time_str}"
    if kind == "weekly":
        iso_days = _parse_weekdays(payload.get("weekdays"))
        if iso_days is None:
            return f"每周 {time_str}"
        days_label = "、".join(_WEEKDAY_CN[d - 1] for d in iso_days)
        return f"每{days_label} {time_str}"
    return "周期任务"

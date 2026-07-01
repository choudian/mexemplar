"""
统一时区工具 -- 全项目统一使用 UTC 存储，显示层按需转本地时间。
"""

from datetime import datetime, timezone

_LOCAL_TZ = datetime.now().astimezone().tzinfo


def utc_now() -> datetime:
    """返回当前 UTC 时间（带 tzinfo）。"""
    return datetime.now(timezone.utc)


def from_timestamp_utc_naive(timestamp: float) -> datetime:
    """将 Unix 时间戳转换为 naive UTC datetime。"""
    return to_naive_utc(datetime.fromtimestamp(timestamp, tz=timezone.utc))


def to_naive_utc(dt: datetime) -> datetime:
    """将 datetime 转为 naive UTC（去掉 tzinfo），兼容 SQLAlchemy DateTime 列。"""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(tzinfo=None)


def utc_now_naive() -> datetime:
    """返回当前 naive UTC 时间，直接赋值给 ORM 字段。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_local(dt: datetime) -> datetime:
    """将存储的 naive UTC 时间转为本地 aware datetime，用于 UI 显示。"""
    if dt is None:
        return dt
    utc_aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    return utc_aware.astimezone(_LOCAL_TZ)


def local_now() -> datetime:
    """返回当前本地 aware datetime。用于 UI 层与 to_local() 结果做差值比较。"""
    return datetime.now(_LOCAL_TZ)


def coerce_timestamp(value) -> datetime | None:
    """如果 value 是数值型时间戳则转为 naive UTC datetime，否则原样返回。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return from_timestamp_utc_naive(value)
    return value


def local_naive_to_utc_naive(dt: datetime) -> datetime:
    """将 legacy local naive datetime 归一化为 naive UTC。"""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_LOCAL_TZ)
    return to_naive_utc(dt)


def format_local(dt: datetime, fmt: str = "%m/%d %H:%M") -> str:
    """将 UTC naive datetime 转本地后格式化为字符串。"""
    if dt is None:
        return ""
    return to_local(dt).strftime(fmt)

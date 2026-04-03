"""
通用辅助函数

提供项目级别的通用工具函数，避免在多处重复相同逻辑。
"""

from pathlib import Path


def to_seconds(time_diff) -> float:
    """将 timedelta 或数值统一转为秒数。

    录制数据的 timestamp 可能是 float（秒）也可能是 datetime，
    两者相减分别得到 float 或 timedelta。此函数统一处理这两种情况。

    Args:
        time_diff: timedelta 对象或 float/int 数值

    Returns:
        秒数（float）
    """
    if hasattr(time_diff, "total_seconds"):
        return time_diff.total_seconds()
    return float(time_diff)


def get_default_data_dir() -> Path:
    """获取默认数据目录，确保目录存在。

    返回项目根目录下的 data/ 目录，如不存在则自动创建。

    Returns:
        data 目录的 Path 对象
    """
    project_root = Path(__file__).parent.parent.parent
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

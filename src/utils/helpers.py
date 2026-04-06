"""
通用辅助函数

提供项目级别的通用工具函数，避免在多处重复相同逻辑。
"""

import re
from pathlib import Path


_TEMPLATE_RE = re.compile(r'\{(\w+)\}')


def safe_format_template(template: str, **kwargs: str) -> str:
    """安全的模板字符串替换。

    使用 re.sub 一次性替换 {key} 占位符，
    避免 str.format() 遇到未知花括号时抛出 KeyError。
    未匹配的 {key} 原样保留。替换值中的花括号不会被二次替换。

    注意：不支持 {{ }} 转义语法，模板中的双花括号会被忽略（只匹配 {word}）。

    Args:
        template: 包含 {key} 占位符的模板字符串
        **kwargs: 要替换的键值对

    Returns:
        替换后的字符串
    """
    def replacer(match):
        key = match.group(1)
        return str(kwargs[key]) if key in kwargs else match.group(0)
    return _TEMPLATE_RE.sub(replacer, template)


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

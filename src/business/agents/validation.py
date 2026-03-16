"""
参数验证机制

为工具参数提供轻量级验证。
"""

from typing import Any, Dict, get_type_hints
from functools import wraps
import logging

logger = logging.getLogger(__name__)


def validate_parameters(schema: Dict[str, Any]):
    """
    参数验证装饰器

    Args:
        schema: 参数 schema（JSON Schema 格式）

    Returns:
        装饰器函数

    Example:
        >>> @validate_parameters({
        ...     "type": "object",
        ...     "required": ["id"],
        ...     "properties": {
        ...         "id": {"type": "string"},
        ...         "limit": {"type": "integer"}
        ...     }
        ... })
        ... def query_data(id: str, limit: int = 100) -> str:
        ...     return f"Data for {id}, limit={limit}"
    """
    def decorator(func):
        @wraps(func)
        def wrapper(**kwargs):
            # 1. 检查必填参数
            required = schema.get("required", [])
            for param in required:
                if param not in kwargs:
                    logger.warning(f"[参数验证] 缺少必填参数: {param}")
                    return f"错误：缺少必填参数 '{param}'"

            # 2. 类型检查（基于类型注解）
            try:
                type_hints_dict = get_type_hints(func)
                for param, hint in type_hints_dict.items():
                    if param in kwargs:
                        value = kwargs[param]
                        # 处理 Optional 类型
                        if hasattr(hint, "__origin__"):
                            from typing import get_origin, get_args
                            origin = get_origin(hint)
                            if origin is type(None):
                                # 只检查非 None 值
                                if value is not None:
                                    args_types = get_args(hint)
                                    if args_types and not isinstance(value, args_types[0]):
                                        error_msg = (
                                            f"错误：参数 '{param}' 类型应为 {args_types[0].__name__} "
                                            f"（或 None），实际为 {type(value).__name__}"
                                        )
                                        logger.warning(f"[参数验证] {error_msg}")
                                        return error_msg
                            else:
                                # 其他复杂类型暂不检查
                                continue
                        else:
                            # 检查普通类型
                            if not isinstance(value, hint):
                                error_msg = (
                                    f"错误：参数 '{param}' 类型应为 {hint.__name__}，"
                                    f"实际为 {type(value).__name__}"
                                )
                                logger.warning(f"[参数验证] {error_msg}")
                                return error_msg
            except Exception as e:
                logger.warning(f"[参数验证] 类型检查失败: {e}")
                # 类型检查失败不阻止执行，继续调用原函数

            # 3. 调用原函数
            return func(**kwargs)
        return wrapper
    return decorator
"""AST 相关通用工具函数"""

import ast


def top_name(name: str | None) -> str:
    """提取模块/属性名的第一个点号之前的部分。"""
    return (name or "").split(".")[0]


def extract_import_names(code: str) -> set[str]:
    """从代码中提取顶层 import 模块名（第一级，不含子模块）。

    Returns:
        如 {"requests", "json", "bs4"} 的集合，包含标准库模块名。
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(top_name(alias.name))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(top_name(node.module))
    return names

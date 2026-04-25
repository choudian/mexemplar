"""
SQL 列血缘分析器：判定 query_data 结果列是直接源字段还是计算/聚合列，
并提取同行稳定定位字段，为占位对象的 locator 构造和 read_blocked_reason 判定提供依据。

仅在 src/recording/filtering/ 内使用 sqlglot；recording_data_tools.py 不得直接 import sqlglot。
"""

from dataclasses import dataclass, field
from typing import Optional

from sqlglot import exp, parse


# ---------------------------------------------------------------------------
# StableLocatorRule: 声明每张源表的稳定定位字段映射
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StableLocatorRule:
    table: str
    recommended_id_field: str
    describe_locator_fields: tuple[str, ...] = ()
    requires_filter_rewrite: bool = False

    def __post_init__(self):
        if not self.describe_locator_fields:
            object.__setattr__(self, "describe_locator_fields", (self.recommended_id_field,))


STABLE_LOCATOR_RULES: dict[str, StableLocatorRule] = {
    rule.table: rule
    for rule in [
        StableLocatorRule(table="network_requests", recommended_id_field="request_id", requires_filter_rewrite=True),
        StableLocatorRule(table="actions", recommended_id_field="action_id"),
        StableLocatorRule(table="sibling_snapshots", recommended_id_field="snapshot_id"),
    ]
}


# ---------------------------------------------------------------------------
# ProjectionBinding: 分析器对单个结果列的输出
# ---------------------------------------------------------------------------

@dataclass
class ProjectionBinding:
    output_name: str
    source_table: Optional[str] = None
    source_field: Optional[str] = None
    is_direct_column: bool = False


# ---------------------------------------------------------------------------
# QueryProjectionAnalyzer
# ---------------------------------------------------------------------------

class QueryProjectionAnalyzer:
    """分析 SELECT 语句的列投影血缘。"""

    def __init__(self, schema_info: Optional[dict[str, set[str]]] = None):
        self._schema = schema_info or {}

    def analyze(self, sql: str) -> list[ProjectionBinding]:
        """解析 SQL 并返回每个结果列的 ProjectionBinding。"""
        try:
            statements = parse(sql, read="duckdb")
        except Exception:
            return []

        if not statements or not isinstance(statements[0], exp.Select):
            return []

        select_stmt = statements[0]
        tables_in_from, alias_map = self._extract_table_info(select_stmt)
        single_table = tables_in_from[0] if len(tables_in_from) == 1 else None
        bindings: list[ProjectionBinding] = []

        for expr_node in select_stmt.expressions:
            binding = self._analyze_expression(expr_node, select_stmt)
            # Resolve alias to actual table name
            if binding.source_table and binding.source_table in alias_map:
                binding.source_table = alias_map[binding.source_table]
            # For single-table queries, unqualified columns belong to that table
            if binding.is_direct_column and binding.source_table is None and single_table:
                binding.source_table = single_table
            bindings.append(binding)

        return bindings

    def _extract_table_info(self, select_stmt: exp.Select) -> tuple[list[str], dict[str, str]]:
        """单次遍历提取 FROM/JOIN 中的表名和别名映射。"""
        tables = []
        alias_map: dict[str, str] = {}
        for table in select_stmt.find_all(exp.Table):
            tables.append(table.name)
            alias = table.alias
            if alias and alias != table.name:
                alias_map[alias] = table.name
        return tables, alias_map

    def _analyze_expression(
        self, expr_node: exp.Expression, select_stmt: exp.Select
    ) -> ProjectionBinding:
        output_name = expr_node.alias_or_name

        # Star / qualified star → not direct for our purposes
        if isinstance(expr_node, exp.Star):
            return ProjectionBinding(output_name=output_name)

        # Direct column reference (possibly with alias)
        if isinstance(expr_node, exp.Column):
            return self._resolve_column(expr_node, output_name)

        # Alias wrapping a column
        if isinstance(expr_node, exp.Alias):
            return self._resolve_alias(expr_node, output_name)

        # Anything else (functions, aggregates, concatenations, arithmetic, etc.)
        return ProjectionBinding(output_name=output_name)

    def _resolve_column(
        self, col: exp.Column, output_name: str
    ) -> ProjectionBinding:
        return ProjectionBinding(
            output_name=output_name,
            source_table=col.table or None,
            source_field=col.name,
            is_direct_column=True,
        )

    def _resolve_alias(self, alias: exp.Alias, output_name: str) -> ProjectionBinding:
        inner = alias.this

        if isinstance(inner, exp.Column):
            binding = self._resolve_column(inner, output_name)
            binding.output_name = output_name
            return binding

        return ProjectionBinding(output_name=output_name)


def find_stable_locator_in_bindings(
    bindings: list[ProjectionBinding],
    source_table: str,
) -> Optional[ProjectionBinding]:
    """在 bindings 中查找某张源表的稳定定位字段直接投影。"""
    rule = STABLE_LOCATOR_RULES.get(source_table)
    if not rule:
        return None

    for b in bindings:
        if (
            b.is_direct_column
            and b.source_table == source_table
            and b.source_field == rule.recommended_id_field
        ):
            return b
    return None


def find_stable_locator_in_row(
    bindings: list[ProjectionBinding],
    source_table: str,
    row: dict,
) -> Optional[ProjectionBinding]:
    """在 bindings + 实际行数据中查找稳定定位字段（处理无表前缀的列名）。"""
    # Phase 1: 带表前缀的直接投影
    direct = find_stable_locator_in_bindings(bindings, source_table)
    if direct is not None:
        if direct.output_name in row and row[direct.output_name] is not None:
            return direct

    rule = STABLE_LOCATOR_RULES.get(source_table)
    if not rule:
        return None

    # 2. 回退：output_name 或 source_field 在行中且无歧义
    candidates = []
    for b in bindings:
        if not b.is_direct_column:
            continue
        # 表名匹配 或 表名未知且字段名匹配
        if b.source_table == source_table or b.source_table is None:
            if b.source_field == rule.recommended_id_field or b.output_name == rule.recommended_id_field:
                candidates.append(b)

    if len(candidates) == 1:
        b = candidates[0]
        key = b.output_name if b.output_name in row else b.source_field
        if key and key in row and row[key] is not None:
            return b

    # 多个候选 → 歧义，保守返回 None
    return None

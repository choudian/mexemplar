from sqlglot import exp, parse
from sqlglot.optimizer.scope import traverse_scope

VISIBLE_NETWORK_REQUEST_COLUMNS = [
    "request_id",
    "action_id",
    "recording_id",
    "url",
    "method",
    "request_type",
    "request_headers",
    "request_body",
    "response_status",
    "response_headers",
    "response_body",
    "duration",
    "timestamp",
]


class SqlRewriteError(RuntimeError):
    """Raised when a query cannot be safely rewritten for filtered access."""


def rewrite(sql: str) -> str:
    try:
        statements = parse(sql, read="duckdb")
    except Exception as exc:
        raise SqlRewriteError("failed to parse SQL") from exc

    if len(statements) != 1:
        raise SqlRewriteError("expected a single statement")

    expression = statements[0]
    if not isinstance(expression, (exp.Select, exp.Union, exp.Except, exp.Intersect)):
        raise SqlRewriteError("statement type is not allowed")

    for scope in traverse_scope(expression):
        for source in scope.sources.values():
            if not isinstance(source, exp.Table):
                continue
            if _is_filter_decisions_table(source):
                raise SqlRewriteError("filter_decisions is hidden")
            if _is_information_schema_table(source):
                raise SqlRewriteError("information_schema access is not allowed")
            if _is_prefixed_system_source(source):
                raise SqlRewriteError("system catalog access is not allowed")
            if _is_network_requests_table(source):
                source.replace(_filtered_network_requests_subquery(source.alias_or_name))

    return expression.sql(dialect="duckdb")


def _is_network_requests_table(table: exp.Table) -> bool:
    return table.name.lower() == "network_requests"


def _is_filter_decisions_table(table: exp.Table) -> bool:
    return table.name.lower() == "filter_decisions"


def _is_information_schema_table(table: exp.Table) -> bool:
    return (table.db or "").lower() == "information_schema"


def _is_prefixed_system_source(table: exp.Table) -> bool:
    if isinstance(table.this, exp.Anonymous):
        name = table.this.name.lower()
        return name.startswith("duckdb_") or name.startswith("pragma_")
    table_name = table.name.lower()
    return table_name.startswith("duckdb_") or table_name.startswith("pragma_")


def _filtered_network_requests_subquery(alias_name: str) -> exp.Subquery:
    inner = (
        exp.select(*[exp.column(column) for column in VISIBLE_NETWORK_REQUEST_COLUMNS])
        .from_("network_requests")
        .where(exp.EQ(this=exp.column("filtered"), expression=exp.false()))
    )
    return inner.subquery(alias=alias_name or "network_requests")

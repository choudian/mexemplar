from typing import Any

from .sql_rewriter import rewrite, validate_table_against_mode_allowlist

SQL_PARSE_FAILED_MESSAGE = "SQL 解析失败，请简化查询后重试"
DATA_ACCESS_RESTRICTED_MESSAGE = "数据访问受限"

_RELATION_FETCH_METHODS = frozenset({"fetchall", "fetchone", "fetchmany"})
_RELATION_WRAP_METHODS = frozenset(
    {
        "filter",
        "project",
        "select",
        "join",
        "aggregate",
        "order",
        "limit",
        "distinct",
        "union",
        "except_",
        "intersect",
        "set_alias",
    }
)
_RELATION_DENIED_METHODS = frozenset(
    {"query", "create_view", "df", "pl", "arrow", "fetchdf", "fetch_df", "to_df"}
)


class MaskedSqlParseError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(SQL_PARSE_FAILED_MESSAGE)


class DataAccessRestrictedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(DATA_ACCESS_RESTRICTED_MESSAGE)


def sanitize_tool_exception(exc: Exception) -> RuntimeError:
    if isinstance(exc, DataAccessRestrictedError):
        return exc
    if str(exc).startswith("table_not_in_mode:"):
        return RuntimeError(str(exc))
    return MaskedSqlParseError()


def _validate_and_rewrite(sql: str, mode: str) -> str:
    """Rewrite SQL and validate table access against mode allowlist."""
    rewritten = rewrite(sql)
    validate_table_against_mode_allowlist(sql, mode)
    return rewritten


class FilteredDuckDBConnection:
    def __init__(self, conn: Any, *, mode: str = "browser") -> None:
        self._conn = conn
        self._mode = mode

    def execute(self, sql: str, parameters: Any = None):
        rewritten = self._rewrite_sql(sql)
        try:
            if parameters is None:
                self._conn.execute(rewritten)
            else:
                self._conn.execute(rewritten, parameters)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None
        return self

    def executemany(self, sql: str, parameters: Any = None):
        rewritten = self._rewrite_sql(sql)
        try:
            if parameters is None:
                self._conn.executemany(rewritten, [])
            else:
                self._conn.executemany(rewritten, parameters)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None
        return self

    def sql(self, sql: str, *args, **kwargs):
        return self._call_relation_method("sql", sql, *args, **kwargs)

    def from_query(self, sql: str, *args, **kwargs):
        return self._call_relation_method("from_query", sql, *args, **kwargs)

    def query(self, sql: str, *args, **kwargs):
        return self._call_relation_method("query", sql, *args, **kwargs)

    def cursor(self):
        return FilteredDuckDBCursor(self._conn.cursor(), mode=self._mode)

    def table(self, name: str):
        normalized = name.strip().strip('"').lower()
        if normalized == "filter_decisions":
            raise DataAccessRestrictedError()
        try:
            validate_table_against_mode_allowlist(f"SELECT * FROM {normalized}", self._mode)
            if normalized == "network_requests":
                relation = self._conn.sql(rewrite("SELECT * FROM network_requests"))
            else:
                relation = self._conn.table(name)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None
        return FilteredDuckDBRelation(relation)

    def fetchall(self):
        return self._fetch("fetchall")

    def fetchone(self):
        return self._fetch("fetchone")

    def fetchmany(self, size: int | None = None):
        return self._fetch("fetchmany", size)

    def __getattr__(self, name: str):
        raise DataAccessRestrictedError()

    def _call_relation_method(self, method_name: str, sql: str, *args, **kwargs):
        rewritten = self._rewrite_sql(sql)
        try:
            relation = getattr(self._conn, method_name)(rewritten, *args, **kwargs)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None
        return FilteredDuckDBRelation(relation)

    def _rewrite_sql(self, sql: str) -> str:
        try:
            return _validate_and_rewrite(sql, self._mode)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None

    def _fetch(self, method_name: str, *args):
        try:
            return getattr(self._conn, method_name)(*args)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None


class FilteredDuckDBCursor:
    def __init__(self, cursor: Any, *, mode: str = "browser") -> None:
        self._cursor = cursor
        self._mode = mode

    def execute(self, sql: str, parameters: Any = None):
        try:
            rewritten = _validate_and_rewrite(sql, self._mode)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None
        try:
            if parameters is None:
                self._cursor.execute(rewritten)
            else:
                self._cursor.execute(rewritten, parameters)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None
        return self

    def fetchall(self):
        return self._fetch("fetchall")

    def fetchone(self):
        return self._fetch("fetchone")

    def fetchmany(self, size: int | None = None):
        return self._fetch("fetchmany", size)

    def __getattr__(self, name: str):
        raise DataAccessRestrictedError()

    def _fetch(self, method_name: str, *args):
        try:
            return getattr(self._cursor, method_name)(*args)
        except Exception as exc:
            raise sanitize_tool_exception(exc) from None


class FilteredDuckDBRelation:
    def __init__(self, relation: Any) -> None:
        self._relation = relation

    def __getattr__(self, name: str):
        if name in _RELATION_DENIED_METHODS:
            raise DataAccessRestrictedError()

        if name in _RELATION_FETCH_METHODS:

            def _fetch(*args, **kwargs):
                try:
                    return getattr(self._relation, name)(*args, **kwargs)
                except Exception as exc:
                    raise sanitize_tool_exception(exc) from None

            return _fetch

        if name in _RELATION_WRAP_METHODS:

            def _wrap(*args, **kwargs):
                unwrapped_args = [_unwrap_relation_arg(arg) for arg in args]
                try:
                    relation = getattr(self._relation, name)(*unwrapped_args, **kwargs)
                except Exception as exc:
                    raise sanitize_tool_exception(exc) from None
                return FilteredDuckDBRelation(relation)

            return _wrap

        raise DataAccessRestrictedError()


def _unwrap_relation_arg(value: Any) -> Any:
    if isinstance(value, FilteredDuckDBRelation):
        return value._relation
    return value

"""测试 query_projection_analyzer 的列血缘分析能力。"""

import pytest

from src.recording.filtering.query_projection_analyzer import (
    STABLE_LOCATOR_RULES,
    ProjectionBinding,
    QueryProjectionAnalyzer,
    _find_stable_locator_in_bindings,
    find_stable_locator_in_row,
)


@pytest.fixture
def analyzer():
    return QueryProjectionAnalyzer()


# ---------------------------------------------------------------------------
# 直接列选择
# ---------------------------------------------------------------------------


class TestDirectColumn:
    def test_simple_select(self, analyzer):
        bindings = analyzer.analyze("SELECT request_id, response_body FROM network_requests")
        assert len(bindings) == 2
        assert bindings[0] == ProjectionBinding(
            output_name="request_id", source_table="network_requests",
            source_field="request_id", is_direct_column=True,
        )
        assert bindings[1] == ProjectionBinding(
            output_name="response_body", source_table="network_requests",
            source_field="response_body", is_direct_column=True,
        )

    def test_qualified_column(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT nr.request_id, nr.response_body FROM network_requests nr"
        )
        # Alias resolved to actual table name
        assert bindings[0].source_table == "network_requests"
        assert bindings[0].source_field == "request_id"
        assert bindings[0].is_direct_column is True

    def test_alias_on_direct_column(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT request_id, response_body AS body FROM network_requests"
        )
        assert bindings[1].output_name == "body"
        assert bindings[1].source_field == "response_body"
        assert bindings[1].is_direct_column is True


# ---------------------------------------------------------------------------
# Join 与定位字段检测
# ---------------------------------------------------------------------------


class TestJoinLocator:
    def test_join_with_locator(self, analyzer):
        sql = (
            "SELECT nr.request_id, nr.response_body AS body, a.action_type "
            "FROM network_requests nr "
            "JOIN actions a ON a.recording_id = nr.recording_id "
            "WHERE nr.request_id = 42"
        )
        bindings = analyzer.analyze(sql)
        body = next(b for b in bindings if b.output_name == "body")
        assert body.source_table == "network_requests"
        assert body.source_field == "response_body"
        assert body.is_direct_column is True

        req_id = next(b for b in bindings if b.output_name == "request_id")
        assert req_id.source_table == "network_requests"
        assert req_id.source_field == "request_id"

    def test_find_stable_locator_present(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT nr.request_id, nr.response_body FROM network_requests nr"
        )
        loc = _find_stable_locator_in_bindings(bindings, "network_requests")
        assert loc is not None
        assert loc.source_field == "request_id"

    def test_find_stable_locator_missing(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT nr.response_body FROM network_requests nr"
        )
        loc = _find_stable_locator_in_bindings(bindings, "network_requests")
        assert loc is None


# ---------------------------------------------------------------------------
# 计算列 / 聚合 → is_direct_column = False
# ---------------------------------------------------------------------------


class TestComputedColumns:
    def test_concatenation(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT response_body || '' AS body FROM network_requests"
        )
        assert bindings[0].is_direct_column is False

    def test_function_call(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT COUNT(*) FROM network_requests"
        )
        assert bindings[0].is_direct_column is False

    def test_aggregate_group_by(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT recording_id, COUNT(*) FROM network_requests GROUP BY recording_id"
        )
        assert bindings[0].is_direct_column is True  # recording_id is direct
        assert bindings[1].is_direct_column is False  # COUNT(*) is not

    def test_arithmetic(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT duration * 1000 AS duration_ms FROM network_requests"
        )
        assert bindings[0].is_direct_column is False


# ---------------------------------------------------------------------------
# 未覆盖源表
# ---------------------------------------------------------------------------


class TestUncoveredTable:
    def test_non_covered_table_column(self, analyzer):
        bindings = analyzer.analyze(
            "SELECT some_id, some_field FROM unknown_table"
        )
        assert bindings[0].is_direct_column is True  # still direct
        # but STABLE_LOCATOR_RULES won't have it
        assert "unknown_table" not in STABLE_LOCATOR_RULES


# ---------------------------------------------------------------------------
# 歧义 join
# ---------------------------------------------------------------------------


class TestAmbiguousJoin:
    def test_same_name_id_from_two_tables(self, analyzer):
        sql = (
            "SELECT a.request_id, b.request_id "
            "FROM network_requests a "
            "JOIN network_requests b ON a.recording_id = b.recording_id"
        )
        bindings = analyzer.analyze(sql)
        assert len(bindings) == 2
        # Both resolved to same actual table name
        assert bindings[0].source_table == "network_requests"
        assert bindings[1].source_table == "network_requests"

    def test_find_locator_ambiguous_returns_none(self, analyzer):
        """当多个无表前缀的 binding 候选匹配同一 locator 字段时，返回 None（保守）。"""
        bindings = [
            ProjectionBinding("request_id", None, "request_id", True),
            ProjectionBinding("request_id_2", None, "request_id", True),
        ]
        row = {"request_id": 42, "request_id_2": 43}
        # Both bindings have source_table=None and source_field=request_id → ambiguous
        loc = find_stable_locator_in_row(bindings, "network_requests", row)
        assert loc is None


# ---------------------------------------------------------------------------
# StableLocatorRule 覆盖
# ---------------------------------------------------------------------------


class TestStableLocatorRules:
    def test_v1_covers_three_tables(self):
        assert "network_requests" in STABLE_LOCATOR_RULES
        assert "actions" in STABLE_LOCATOR_RULES
        assert "sibling_snapshots" in STABLE_LOCATOR_RULES

    def test_rule_fields(self):
        rule = STABLE_LOCATOR_RULES["network_requests"]
        assert rule.recommended_id_field == "request_id"
        assert rule.describe_locator_fields == ("request_id",)

    def test_actions_rule(self):
        rule = STABLE_LOCATOR_RULES["actions"]
        assert rule.recommended_id_field == "action_id"

    def test_sibling_snapshots_rule(self):
        rule = STABLE_LOCATOR_RULES["sibling_snapshots"]
        assert rule.recommended_id_field == "snapshot_id"


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_sql(self, analyzer):
        bindings = analyzer.analyze("")
        assert bindings == []

    def test_invalid_sql(self, analyzer):
        bindings = analyzer.analyze("NOT VALID SQL ???")
        assert bindings == []

    def test_select_star(self, analyzer):
        bindings = analyzer.analyze("SELECT * FROM network_requests")
        assert len(bindings) == 1
        assert bindings[0].is_direct_column is False

    def test_find_stable_locator_in_row_unqualified(self, analyzer):
        """无表前缀时，如果字段名匹配且无歧义，仍可定位。"""
        bindings = analyzer.analyze(
            "SELECT request_id, response_body FROM network_requests"
        )
        row = {"request_id": 42, "response_body": "big content..." * 100}
        loc = find_stable_locator_in_row(bindings, "network_requests", row)
        assert loc is not None
        assert loc.source_field == "request_id"

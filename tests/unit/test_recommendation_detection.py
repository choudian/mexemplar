"""
推荐内容识别单元测试
"""

import pytest
from src.business.ai.preprocessing.analyzers.intelligence_analyzer import (
    RequestIntelligenceAnalyzer,
    RequestAnalysis,
)


class TestRecommendationDetection:
    """测试推荐内容识别功能"""

    @pytest.fixture
    def analyzer(self):
        """创建分析器实例"""
        return RequestIntelligenceAnalyzer()

    def test_is_recommendation_request_url_pattern(self, analyzer):
        """测试 URL 模式匹配"""
        # 推荐内容 URL
        assert (
            analyzer._is_recommendation_request("https://api.example.com/recommend/items", {})
            == True
        )

        assert (
            analyzer._is_recommendation_request("https://api.example.com/personalize/feed", {})
            == True
        )

        assert (
            analyzer._is_recommendation_request("https://api.example.com/related/videos", {})
            == True
        )

        # 非 URL 模式
        assert analyzer._is_recommendation_request("https://api.example.com/items/123", {}) == False

        assert (
            analyzer._is_recommendation_request("https://api.example.com/search?q=test", {})
            == False
        )

    def test_is_recommendation_request_query_params(self, analyzer):
        """测试查询参数特征判断"""
        # 推荐算法参数
        assert (
            analyzer._is_recommendation_request(
                "https://api.example.com/items?algorithm=collab", {}
            )
            == True
        )

        assert (
            analyzer._is_recommendation_request("https://api.example.com/feed?based=history", {})
            == True
        )

        # 非推荐参数
        assert (
            analyzer._is_recommendation_request("https://api.example.com/items?page=1&limit=10", {})
            == False
        )

    def test_is_recommendation_request_response_body(self, analyzer):
        """测试响应体特征判断"""
        # 推荐关键词
        response_data = {
            "recommendations": [
                {"id": 1, "name": "Item 1"},
                {"id": 2, "name": "Item 2"},
            ]
        }
        assert (
            analyzer._is_recommendation_request("https://api.example.com/data", response_data)
            == True
        )

        response_data = {"personalized_content": {"for_you": ["item1", "item2"]}}
        assert (
            analyzer._is_recommendation_request("https://api.example.com/feed", response_data)
            == True
        )

        # 非推荐内容
        response_data = {
            "items": [
                {"id": 1, "name": "Item 1"},
                {"id": 2, "name": "Item 2"},
            ]
        }
        assert (
            analyzer._is_recommendation_request("https://api.example.com/items", response_data)
            == False
        )

    def test_analyze_importance_core(self, analyzer):
        """测试核心业务分析"""
        analysis = RequestAnalysis(
            request_id="test_1",
            is_meaningful=True,
            reason="搜索结果API",
            confidence=0.9,
        )

        result = analyzer._analyze_importance("https://api.example.com/search?q=test", {}, analysis)

        assert result.is_recommendation == False
        assert result.importance_level == "core"

    def test_analyze_importance_secondary(self, analyzer):
        """测试次要内容（推荐）分析"""
        analysis = RequestAnalysis(
            request_id="test_2",
            is_meaningful=True,
            reason="推荐内容",
            confidence=0.8,
        )

        result = analyzer._analyze_importance(
            "https://api.example.com/recommend/items", {}, analysis
        )

        assert result.is_recommendation == True
        assert result.importance_level == "secondary"

    def test_analyze_importance_meaningless(self, analyzer):
        """测试无意义请求分析"""
        analysis = RequestAnalysis(
            request_id="test_3",
            is_meaningful=False,
            reason="广告请求",
            confidence=0.95,
        )

        result = analyzer._analyze_importance("https://ad.example.com/banner", {}, analysis)

        # 无意义的请求，is_recommendation 应该为 False
        assert result.is_recommendation == False
        assert result.importance_level == "meaningless"

    def test_recommendation_patterns(self, analyzer):
        """测试推荐模式常量"""
        # 验证模式列表不为空
        assert len(analyzer.recommendation_patterns) > 0
        assert "/recommend" in analyzer.recommendation_patterns
        assert "/suggest" in analyzer.recommendation_patterns

        assert len(analyzer.suggestion_patterns) > 0
        assert "/autocomplete" in analyzer.suggestion_patterns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

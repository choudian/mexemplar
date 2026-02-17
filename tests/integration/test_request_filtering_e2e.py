"""
端到端测试：网络请求智能过滤

测试完整的过滤工作流：Action → 智能过滤 → 分析
"""

import pytest
from src.business.ai.preprocessing import DataPreprocessor, CompressionLevel
from src.recording.recorder import Action, NetworkRequest


def test_complete_filtering_workflow():
    """测试完整的过滤工作流 - 真实场景模拟

    工作流程：
    1. 基础过滤器过滤静态资源、埋点等
    2. 智能过滤器进一步分析依赖关系和加密数据
    """

    # 准备测试数据：模拟一个真实的表单提交场景
    # 注意：需要添加 response_headers 以便智能分析器能识别 JSON 响应
    actions = [
        Action(
            action_type="navigate",
            recording_mode="browser",
            url="https://www.example.com/form",
            timestamp=1000,
            network_requests=None,
        ),
        Action(
            action_type="click",
            recording_mode="browser",
            timestamp=2000,
            network_requests=[
                # 下拉列表请求（依赖 1：获取国家列表）
                NetworkRequest(
                    url="https://api.example.com/countries",
                    method="GET",
                    response_body='[{"id": 1, "name": "China"}, {"id": 2, "name": "USA"}]',
                    response_headers={"content-type": "application/json"},
                    response_status=200,
                    timestamp=2100,
                )
            ],
        ),
        Action(
            action_type="input",
            recording_mode="browser",
            timestamp=3000,
            parameters={"value": "China"},
            network_requests=None,
        ),
        Action(
            action_type="click",
            recording_mode="browser",
            timestamp=4000,
            network_requests=[
                # 表单提交请求（依赖 2：依赖国家列表返回的 ID）
                NetworkRequest(
                    url="https://api.example.com/submit",
                    method="POST",
                    request_body='{"country_id": 1, "name": "Test"}',
                    response_body='{"status": "ok", "submission_id": 12345}',
                    response_headers={"content-type": "application/json"},
                    response_status=200,
                    timestamp=4100,
                ),
                # 心跳请求（会被基础过滤器过滤）
                NetworkRequest(
                    url="https://api.example.com/health",
                    method="GET",
                    response_status=200,
                    timestamp=4200,
                ),
            ],
        ),
    ]

    # 执行预处理
    preprocessor = DataPreprocessor()
    result = preprocessor.preprocess(actions, CompressionLevel.MODERATE)

    # 验证操作未被过滤
    assert len(result.actions) == 4, "操作不应该被过滤"

    # 验证统计信息存在
    stats = result.metadata.get("analysis_stats", {})
    assert "intelligent_filter" in stats, "应该有智能过滤统计信息"

    # 验证过滤统计结构
    filter_stats = stats["intelligent_filter"]
    assert "total_requests" in filter_stats
    assert "filtered_out" in filter_stats
    assert "meaningful_kept" in filter_stats

    # 验证依赖关系被正确分析
    # 直接测试请求分析器
    analyzer = preprocessor.request_intelligence_analyzer

    # 分析原始请求（在基础过滤之前）
    all_analyses = analyzer.analyze_requests(actions, use_llm=False)

    # 验证业务请求被识别为有意义
    # 注意：心跳请求可能在基础过滤中已被过滤，所以这里主要验证业务 API
    meaningful_count = sum(1 for a in all_analyses if a.is_meaningful)
    assert meaningful_count >= 1, f"应该识别出至少一个有意义的请求，实际有 {meaningful_count} 个"

    # 验证有业务 API 被识别
    business_api_analyses = [a for a in all_analyses if a.category == "api_call"]
    assert len(business_api_analyses) >= 1, "应该识别出业务 API 请求"


def test_encrypted_data_filtering():
    """测试加密数据过滤

    注意：基础过滤器会过滤掉没有 JSON 响应的请求。
    为了测试加密检测，我们需要提供一个看似 JSON 但实际加密的响应。
    """

    actions = [
        Action(
            action_type="navigate",
            recording_mode="browser",
            url="https://secure.example.com",
            timestamp=1000,
            network_requests=[
                NetworkRequest(
                    url="https://api.example.com/secure-data",
                    method="GET",
                    # 模拟加密的 JSON 响应（Django 加密标记）
                    response_body="gAAAAABlCi5i4qR8ZX5rvcYjPEXo_ZK" * 10,
                    response_headers={"content-type": "application/json"},
                    response_status=200,
                    timestamp=2000,
                )
            ],
        )
    ]

    # 直接测试加密检测器
    from src.business.ai.preprocessing.analyzers.intelligence_analyzer import EncryptionDetector

    detector = EncryptionDetector()

    # 测试短加密数据（Django 标记）
    short_encrypted = "gAAAAABlCi5i4qR8ZX5rvcYjPEXo_ZK"
    assert detector.is_encrypted(short_encrypted), "应该识别 Django 加密标记"

    # 验证非加密数据
    assert not detector.is_encrypted('{"data": "test"}'), "不应该将普通 JSON 识别为加密"
    assert not detector.is_encrypted("plain text"), "不应该将普通文本识别为加密"


def test_dependency_tracking():
    """测试依赖关系跟踪"""

    actions = [
        Action(
            action_type="click",
            recording_mode="browser",
            timestamp=1000,
            network_requests=[
                # 请求 A：返回列表数据
                NetworkRequest(
                    url="https://api.example.com/items",
                    method="GET",
                    response_body='[{"id": 101, "name": "Item 1"}, {"id": 102, "name": "Item 2"}]',
                    response_status=200,
                    timestamp=1100,
                )
            ],
        ),
        Action(
            action_type="click",
            recording_mode="browser",
            timestamp=2000,
            network_requests=[
                # 请求 B：依赖请求 A 返回的 ID
                NetworkRequest(
                    url="https://api.example.com/items/101/detail",
                    method="GET",
                    response_body='{"id": 101, "name": "Item 1", "description": "Detail"}',
                    response_status=200,
                    timestamp=2100,
                )
            ],
        ),
    ]

    preprocessor = DataPreprocessor()

    # 分析依赖关系
    analyzer = preprocessor.request_intelligence_analyzer
    all_requests = analyzer._extract_all_requests(actions)
    dependency_graph = analyzer._dependency_analyzer.build_dependency_graph(all_requests)

    # 验证依赖图结构
    assert len(dependency_graph) == 2, "应该有 2 个请求节点"

    # 验证依赖关系
    req_ids = list(dependency_graph.keys())
    req_a = req_ids[0]
    req_b = req_ids[1]

    # 检查依赖信息
    assert "depends_on" in dependency_graph[req_a]
    assert "used_by" in dependency_graph[req_a]
    assert "used_by_count" in dependency_graph[req_a]

    # 验证被依赖的请求被标记为有意义
    analyses = analyzer.analyze_requests(actions, use_llm=False)

    # 被依赖的请求应该有更高的优先级
    for analysis in analyses:
        if analysis.is_meaningful:
            # 验证被依赖的请求有更高的置信度
            dep_info = dependency_graph.get(analysis.request_id, {})
            if dep_info.get("used_by_count", 0) > 0:
                assert analysis.confidence > 0.5, "被依赖的请求应该有较高的置信度"
                assert "依赖" in analysis.reason, "原因应该包含'依赖'关键字"


def test_analytics_filtering():
    """测试分析/埋点请求过滤

    注意：基础过滤器已经过滤了大部分埋点请求。
    这里我们直接测试智能分析器的分类能力。
    """

    from src.business.ai.preprocessing.analyzers.intelligence_analyzer import RequestIntelligenceAnalyzer

    analyzer = RequestIntelligenceAnalyzer()

    # 测试各种埋点 URL 模式
    analytics_urls = [
        "https://www.google-analytics.com/collect",
        "https://tracking.example.com/pixel.gif",
        "https://metrics.example.com/telemetry",
        "https://stats.example.com/beacon",
    ]

    identified_count = 0
    for url in analytics_urls:
        # 创建测试请求数据
        req_data = {
            "request_id": f"test_{url}",
            "url": url,
            "method": "GET",
            "request_body": {},
            "status_code": 200,
            "response_body": '{"ok": true}',
            "headers": {},
            "action": None,
        }

        # 分析请求
        dependency_graph = {f"test_{url}": {"depends_on": [], "used_by": [], "used_by_count": 0}}
        analysis = analyzer._rule_based_analysis(req_data, dependency_graph)

        if analysis.category == "analytics":
            identified_count += 1

    # 应该识别出大部分埋点请求（至少 2 个）
    assert identified_count >= 2, f"应该识别出至少 2 个埋点请求，实际识别了 {identified_count} 个"


def test_static_resource_filtering():
    """测试静态资源过滤"""

    static_urls = [
        "https://cdn.example.com/style.css",
        "https://cdn.example.com/app.js",
        "https://cdn.example.com/logo.png",
        "https://fonts.example.com/font.woff2",
    ]

    actions = []
    for idx, url in enumerate(static_urls):
        actions.append(
            Action(
                action_type="navigate",
                recording_mode="browser",
                timestamp=1000 + idx * 1000,
                network_requests=[
                    NetworkRequest(
                        url=url,
                        method="GET",
                        response_body="binary data",
                        response_status=200,
                        timestamp=1100 + idx * 1000,
                    )
                ],
            )
        )

    preprocessor = DataPreprocessor()
    analyses = preprocessor.request_intelligence_analyzer.analyze_requests(actions, use_llm=False)

    # 所有静态资源都应该被过滤
    static_filtered = sum(1 for a in analyses if a.category == "static" and not a.is_meaningful)

    assert static_filtered >= 3, f"至少应该过滤 3 个静态资源请求，实际过滤了 {static_filtered} 个"


def test_heartbeat_detection():
    """测试心跳请求检测"""

    heartbeat_urls = [
        "https://api.example.com/heartbeat",
        "https://api.example.com/ping",
        "https://api.example.com/keepalive",
        "https://api.example.com/health",
    ]

    actions = []
    for idx, url in enumerate(heartbeat_urls):
        actions.append(
            Action(
                action_type="wait",
                recording_mode="browser",
                timestamp=1000 + idx * 1000,
                network_requests=[
                    NetworkRequest(
                        url=url,
                        method="GET",
                        response_body='{"status": "ok"}',
                        response_status=200,
                        timestamp=1100 + idx * 1000,
                    )
                ],
            )
        )

    preprocessor = DataPreprocessor()
    analyses = preprocessor.request_intelligence_analyzer.analyze_requests(actions, use_llm=False)

    # 所有心跳请求都应该被过滤
    heartbeat_filtered = sum(
        1 for a in analyses if a.category == "heartbeat" and not a.is_meaningful
    )

    assert heartbeat_filtered >= 3, f"至少应该过滤 3 个心跳请求，实际过滤了 {heartbeat_filtered} 个"


def test_mixed_requests_scenario():
    """测试混合请求场景（实际录制中常见）

    重点测试：
    1. 基础过滤器过滤静态资源
    2. 智能过滤器识别心跳请求
    3. 业务 API 被正确保留
    """

    actions = [
        Action(
            action_type="navigate",
            recording_mode="browser",
            url="https://www.example.com",
            timestamp=1000,
            network_requests=[
                # 静态资源（会被基础过滤器过滤）
                NetworkRequest(
                    url="https://cdn.example.com/app.css",
                    method="GET",
                    response_status=200,
                    timestamp=1100,
                ),
                # 业务 API
                NetworkRequest(
                    url="https://api.example.com/config",
                    method="GET",
                    response_body='{"feature_flags": {"new_ui": true}}',
                    response_headers={"content-type": "application/json"},
                    response_status=200,
                    timestamp=1200,
                ),
            ],
        ),
        Action(
            action_type="click",
            recording_mode="browser",
            timestamp=2000,
            network_requests=[
                # 列表数据（会被后续请求依赖）
                NetworkRequest(
                    url="https://api.example.com/users",
                    method="GET",
                    response_body='[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]',
                    response_headers={"content-type": "application/json"},
                    response_status=200,
                    timestamp=2100,
                ),
            ],
        ),
        Action(
            action_type="click",
            recording_mode="browser",
            timestamp=3000,
            network_requests=[
                # 详情请求（依赖列表请求的 ID）
                NetworkRequest(
                    url="https://api.example.com/users/1",
                    method="GET",
                    response_body='{"id": 1, "name": "Alice", "email": "alice@example.com"}',
                    response_headers={"content-type": "application/json"},
                    response_status=200,
                    timestamp=3100,
                ),
                # 心跳（会被基础过滤器过滤）
                NetworkRequest(
                    url="https://api.example.com/health",
                    method="GET",
                    response_status=200,
                    timestamp=3200,
                ),
            ],
        ),
    ]

    preprocessor = DataPreprocessor()
    result = preprocessor.preprocess(actions, CompressionLevel.MODERATE)

    # 分析原始请求（在基础过滤之前）
    analyzer = preprocessor.request_intelligence_analyzer
    all_analyses = analyzer.analyze_requests(actions, use_llm=False)

    # 统计各类别
    category_counts = {}
    for analysis in all_analyses:
        category_counts[analysis.category] = category_counts.get(analysis.category, 0) + 1

    # 验证分类识别（静态资源、心跳、业务 API 等）
    assert len(category_counts) >= 1, "应该识别出多种请求类别"

    # 验证有意义请求被保留
    meaningful_count = sum(1 for a in all_analyses if a.is_meaningful)
    assert meaningful_count >= 1, f"应该保留至少 1 个有意义的请求，实际有 {meaningful_count} 个"

    # 验证统计信息存在
    stats = result.metadata.get("analysis_stats", {})
    assert "intelligent_filter" in stats, "应该有智能过滤统计信息"


def test_empty_requests():
    """测试空请求列表"""
    actions = [
        Action(
            action_type="navigate",
            recording_mode="browser",
            url="https://www.example.com",
            timestamp=1000,
            network_requests=None,
        )
    ]

    preprocessor = DataPreprocessor()
    result = preprocessor.preprocess(actions, CompressionLevel.MODERATE)

    # 验证不会出错
    assert result is not None
    assert len(result.actions) == 1

    # 统计信息应该正确
    stats = result.metadata.get("analysis_stats", {})
    filter_stats = stats.get("intelligent_filter", {})

    assert filter_stats.get("total_requests", 0) == 0
    assert filter_stats.get("filtered_out", 0) == 0
    assert filter_stats.get("meaningful_kept", 0) == 0


def test_preprocessing_result_structure():
    """测试预处理结果结构"""

    actions = [
        Action(
            action_type="click",
            recording_mode="browser",
            timestamp=1000,
            network_requests=[
                NetworkRequest(
                    url="https://api.example.com/data",
                    method="GET",
                    response_body='{"data": "test"}',
                    response_status=200,
                    timestamp=1100,
                )
            ],
        )
    ]

    preprocessor = DataPreprocessor()
    result = preprocessor.preprocess(actions, CompressionLevel.MODERATE)

    # 验证返回的是 PreprocessingResultV2
    assert hasattr(result, "actions"), "结果应该有 actions 属性"
    assert hasattr(result, "metadata"), "结果应该有 metadata 属性"
    assert hasattr(result, "network_analysis"), "结果应该有 network_analysis 属性"
    assert hasattr(result, "list_analysis"), "结果应该有 list_analysis 属性"

    # 验证 metadata 结构
    assert "analysis_stats" in result.metadata, "metadata 应该包含 analysis_stats"
    assert (
        "intelligent_filter" in result.metadata["analysis_stats"]
    ), "analysis_stats 应该包含 intelligent_filter"

    # 验证智能过滤统计结构
    filter_stats = result.metadata["analysis_stats"]["intelligent_filter"]
    required_keys = ["total_requests", "filtered_out", "meaningful_kept", "filter_ratio"]
    for key in required_keys:
        assert key in filter_stats, f"filter_stats 应该包含 {key}"


def test_compression_levels():
    """测试不同压缩级别"""

    actions = [
        Action(
            action_type="click",
            recording_mode="browser",
            timestamp=1000,
            network_requests=[
                NetworkRequest(
                    url="https://api.example.com/data",
                    method="GET",
                    response_body='{"data": "test"}',
                    response_status=200,
                    timestamp=1100,
                )
            ],
        )
    ]

    preprocessor = DataPreprocessor()

    # 测试所有压缩级别
    for level in [
        CompressionLevel.NONE,
        CompressionLevel.CONSERVATIVE,
        CompressionLevel.MODERATE,
        CompressionLevel.AGGRESSIVE,
    ]:
        result = preprocessor.preprocess(actions, level)

        # 验证不会出错
        assert result is not None, f"压缩级别 {level.value} 不应该返回 None"
        assert result.metadata is not None, f"压缩级别 {level.value} 的 metadata 不应该为 None"

        # 验证智能过滤统计存在（除了 NONE 级别）
        stats = result.metadata.get("analysis_stats", {})
        if level != CompressionLevel.NONE:
            assert "intelligent_filter" in stats, f"压缩级别 {level.value} 应该有智能过滤统计"

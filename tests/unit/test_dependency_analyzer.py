"""
依赖关系分析器测试
"""

from src.business.ai.dependency_analyzer import DependencyAnalyzer
from src.recording.recorder import NetworkRequest


def test_find_data_dependencies():
    analyzer = DependencyAnalyzer()

    # 模拟请求列表
    requests = [
        NetworkRequest(
            url="https://api.example.com/countries",
            method="GET",
            response_body='[{"id": 1, "name": "China"}, {"id": 2, "name": "USA"}]',
            timestamp=1000,
        ),
        NetworkRequest(
            url="https://api.example.com/submit",
            method="POST",
            request_body='{"country_id": 1, "user": "test"}',
            timestamp=2000,
        ),
    ]

    dependencies = analyzer.find_dependencies(requests)

    # 第二个请求依赖第一个请求的数据
    assert len(dependencies) == 2
    submit_req_deps = dependencies[1]
    assert len(submit_req_deps) == 1
    assert submit_req_deps[0].field_name == "country_id"
    assert submit_req_deps[0].field_value == 1
    assert submit_req_deps[0].source_request_id == "/countries@1000"


def test_no_dependencies():
    analyzer = DependencyAnalyzer()

    requests = [
        NetworkRequest(
            url="https://api.example.com/submit",
            method="POST",
            request_body='{"name": "test"}',
            timestamp=1000,
        )
    ]

    dependencies = analyzer.find_dependencies(requests)

    assert len(dependencies) == 1
    assert len(dependencies[0]) == 0

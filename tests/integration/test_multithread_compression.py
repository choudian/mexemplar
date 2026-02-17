"""
数据压缩模型多线程测试

测试单线程和多线程模式的一致性和性能差异。
"""

import pytest
import time
from typing import List, Dict
from unittest.mock import patch

from src.recording.recorder import Action, NetworkRequest
from src.business.ai.preprocessing.analyzers.intelligence_analyzer import RequestIntelligenceAnalyzer
from src.data.unified_config import get_unified_config


class TestMultithreadCompression:
    """数据压缩模型多线程测试"""

    @pytest.fixture
    def sample_actions(self) -> List[Action]:
        """创建测试用的 Action 列表"""
        actions = []

        # 创建 20 个模拟的 Action（每个包含 2 个网络请求）
        for i in range(20):
            action = Action(
                action_type="click",
                recording_mode="browser",
                timestamp=1000 + i * 100,
                url=f"https://example.com/page{i}",
                dom_element={"tag": "button", "text": f"Button {i}"},
                network_requests=[
                    NetworkRequest(
                        url=f"https://api.example.com/data/{i}",
                        method="GET",
                        request_body={},
                        response_status=200,
                        response_headers={"content-type": "application/json"},
                        response_body='{"id": 123, "name": "Test"}',
                        timestamp=1000 + i * 100,
                    ),
                    NetworkRequest(
                        url=f"https://cdn.example.com/static/script.js",
                        method="GET",
                        request_body={},
                        response_status=200,
                        response_headers={"content-type": "application/javascript"},
                        response_body="console.log('test');",
                        timestamp=1000 + i * 100 + 10,
                    ),
                ],
                parameters={},
            )
            actions.append(action)

        return actions

    @pytest.fixture
    def mock_llm_response(self) -> Dict:
        """模拟 LLM 响应"""
        return {
            "is_meaningful": True,
            "reason": "API 请求，返回业务数据",
            "confidence": 0.9,
            "category": "api_call",
            "is_replayable": True,
        }

    def test_single_thread_mode(self, sample_actions: List[Action], mock_llm_response: Dict):
        """测试单线程模式（threads=1）"""
        config = get_unified_config()

        # 设置为单线程模式
        config.set_runtime("ai.compression_model_threads", 1)
        config.set_runtime("ai.compression_model_enabled", True)

        # 创建分析器
        analyzer = RequestIntelligenceAnalyzer(config)

        # Mock LLM 调用
        with patch.object(analyzer, "_call_compression_model", return_value=mock_llm_response):
            start_time = time.time()
            analyses = analyzer.analyze_requests(sample_actions, use_llm=True)
            elapsed_time = time.time() - start_time

        # 验证结果
        assert len(analyses) == 40  # 20 actions * 2 requests

        # 统计有意义和无意义的请求
        meaningful_count = sum(1 for a in analyses if a.is_meaningful)
        assert meaningful_count > 0  # 至少有一些有意义的请求

        print(f"\n单线程模式耗时: {elapsed_time:.2f} 秒")
        print(f"平均每个请求: {elapsed_time / 40:.3f} 秒")
        print(f"有意义请求: {meaningful_count}/{len(analyses)}")
        print(f"规则引擎过滤: {len(analyses) - meaningful_count} 个静态资源")

    def test_multi_thread_mode(self, sample_actions: List[Action], mock_llm_response: Dict):
        """测试多线程模式（threads=4）"""
        config = get_unified_config()

        # 设置为多线程模式
        config.set_runtime("ai.compression_model_threads", 4)
        config.set_runtime("ai.compression_model_enabled", True)

        # 创建分析器
        analyzer = RequestIntelligenceAnalyzer(config)

        # Mock LLM 调用
        with patch.object(analyzer, "_call_compression_model", return_value=mock_llm_response):
            start_time = time.time()
            analyses = analyzer.analyze_requests(sample_actions, use_llm=True)
            elapsed_time = time.time() - start_time

        # 验证结果
        assert len(analyses) == 40  # 20 actions * 2 requests

        # 统计有意义和无意义的请求
        meaningful_count = sum(1 for a in analyses if a.is_meaningful)
        assert meaningful_count > 0  # 至少有一些有意义的请求

        print(f"\n多线程模式（4线程）耗时: {elapsed_time:.2f} 秒")
        print(f"平均每个请求: {elapsed_time / 40:.3f} 秒")
        print(f"吞吐量: {40 / elapsed_time:.2f} 请求/秒")
        print(f"有意义请求: {meaningful_count}/{len(analyses)}")
        print(f"规则引擎过滤: {len(analyses) - meaningful_count} 个静态资源")

    def test_result_consistency(self, sample_actions: List[Action], mock_llm_response: Dict):
        """验证单线程和多线程结果一致性"""
        config = get_unified_config()

        # 单线程模式
        config.set_runtime("ai.compression_model_threads", 1)
        config.set_runtime("ai.compression_model_enabled", True)

        analyzer_single = RequestIntelligenceAnalyzer(config)

        with patch.object(
            analyzer_single, "_call_compression_model", return_value=mock_llm_response
        ):
            single_thread_results = analyzer_single.analyze_requests(sample_actions, use_llm=True)

        # 多线程模式
        config.set_runtime("ai.compression_model_threads", 4)

        analyzer_multi = RequestIntelligenceAnalyzer(config)

        with patch.object(
            analyzer_multi, "_call_compression_model", return_value=mock_llm_response
        ):
            multi_thread_results = analyzer_multi.analyze_requests(sample_actions, use_llm=True)

        # 验证数量一致
        assert len(single_thread_results) == len(multi_thread_results)

        # 验证每个结果的关键字段一致
        for single, multi in zip(single_thread_results, multi_thread_results):
            assert single.is_meaningful == multi.is_meaningful
            assert single.reason == multi.reason
            assert single.confidence == multi.confidence
            assert single.category == multi.category

        print("\n单线程和多线程结果一致性验证通过")

    def test_performance_improvement(self, sample_actions: List[Action], mock_llm_response: Dict):
        """测试性能提升（需要真实网络请求，此为模拟测试）"""
        config = get_unified_config()

        # 单线程模式
        config.set_runtime("ai.compression_model_threads", 1)
        config.set_runtime("ai.compression_model_enabled", True)

        analyzer_single = RequestIntelligenceAnalyzer(config)

        with patch.object(
            analyzer_single, "_call_compression_model", return_value=mock_llm_response
        ):
            start_time = time.time()
            analyzer_single.analyze_requests(sample_actions, use_llm=True)
            single_thread_time = time.time() - start_time

        # 多线程模式（4 线程）
        config.set_runtime("ai.compression_model_threads", 4)

        analyzer_multi = RequestIntelligenceAnalyzer(config)

        with patch.object(
            analyzer_multi, "_call_compression_model", return_value=mock_llm_response
        ):
            start_time = time.time()
            analyzer_multi.analyze_requests(sample_actions, use_llm=True)
            multi_thread_time = time.time() - start_time

        # 计算性能提升
        speedup = single_thread_time / multi_thread_time
        efficiency = speedup / 4  # 效率 = 实际加速比 / 理论加速比

        print(f"\n性能对比:")
        print(f"单线程耗时: {single_thread_time:.2f} 秒")
        print(f"多线程（4线程）耗时: {multi_thread_time:.2f} 秒")
        print(f"加速比: {speedup:.2f}x")
        print(f"并行效率: {efficiency * 100:.1f}%")

        # 注意：由于 Mock 调用很快，实际加速比可能不明显
        # 真实测试需要使用实际的 API 调用

    def test_thread_count_validation(self, sample_actions: List[Action]):
        """测试线程数验证"""
        config = get_unified_config()

        # 测试无效的线程数（0）
        config.set_runtime("ai.compression_model_threads", 0)
        config.set_runtime("ai.compression_model_enabled", True)

        analyzer = RequestIntelligenceAnalyzer(config)

        # 应该回退到单线程模式
        with patch.object(
            analyzer, "_call_compression_model", return_value={"is_meaningful": True}
        ):
            # 不应该抛出异常
            analyses = analyzer.analyze_requests(sample_actions, use_llm=True)
            assert len(analyses) > 0

    def test_error_handling_in_multithread(self, sample_actions: List[Action]):
        """测试多线程模式下的错误处理"""
        config = get_unified_config()

        config.set_runtime("ai.compression_model_threads", 4)
        config.set_runtime("ai.compression_model_enabled", True)

        analyzer = RequestIntelligenceAnalyzer(config)

        # Mock LLM 调用，让部分请求失败
        call_count = [0]

        def mock_call_with_errors(prompt: str):
            call_count[0] += 1
            if call_count[0] % 5 == 0:  # 每 5 个调用失败一次
                raise Exception("模拟 API 调用失败")
            return {
                "is_meaningful": True,
                "reason": "成功",
                "confidence": 0.9,
                "category": "api_call",
                "is_replayable": True,
            }

        with patch.object(analyzer, "_call_compression_model", side_effect=mock_call_with_errors):
            analyses = analyzer.analyze_requests(sample_actions, use_llm=True)

        # 验证：即使有错误，也应该返回所有请求的分析结果
        assert len(analyses) == 40

        # 验证：失败的请求应该被标记为 is_meaningful=False
        failed_count = sum(1 for a in analyses if not a.is_meaningful)
        assert failed_count > 0  # 应该有一些失败的请求

        print(f"\n错误处理测试: {failed_count} 个请求分析失败，已被正确处理")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

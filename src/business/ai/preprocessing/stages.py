"""
处理阶段实现

包含所有具体的数据处理阶段。
"""

import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

from src.business.ai.preprocessing.pipeline import PipelineStage, PipelineContext
from src.business.ai.preprocessing.models import CompressionLevel
from src.recording.recorder import Action

logger = logging.getLogger(__name__)


class DataCleaningStage(PipelineStage):
    """阶段 1: 数据清理（DOM、网络请求、截图）"""

    def __init__(self):
        super().__init__("data_cleaning")

        # 无效域名关键词
        self.invalid_keywords = {
            "ad.",
            "ads.",
            "analytics",
            "tracking",
            "tracker",
            "doubleclick",
            "google-analytics",
            "googletagmanager",
            "facebook.com/tr",
            "pixel.",
            "telemetry.",
            "metrics.",
            "stats.",
            "beacon.",
            "clarity.",
        }

        # 静态资源文件扩展名
        self.static_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".webp",
            ".bmp",
            ".css",
            ".scss",
            ".less",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".otf",
            ".mp3",
            ".mp4",
            ".avi",
            ".mov",
            ".wav",
            ".webm",
            ".zip",
            ".rar",
            ".tar",
            ".gz",
            ".xml",
            ".json",
            ".txt",
        }

    def process(self, context: PipelineContext) -> PipelineContext:
        """执行数据清理"""
        actions = context.actions

        # 1. 过滤网络请求
        actions = self._filter_network_requests(actions)

        # 2. 清理 DOM 属性（基础清理）
        actions = self._clean_dom_attributes_basic(actions)

        context.actions = actions
        return context

    def _filter_network_requests(self, actions: List[Action]) -> List[Action]:
        """过滤无效的网络请求"""
        for action in actions:
            if action.network_requests:
                # 过滤无效请求
                filtered_requests = []
                for req in action.network_requests:
                    url_lower = req.url.lower() if req.url else ""

                    # 1. 检查是否为广告/统计等无效请求
                    is_invalid = any(keyword in url_lower for keyword in self.invalid_keywords)
                    if is_invalid:
                        continue

                    # 2. 检查是否为静态资源（通过文件扩展名）
                    if any(url_lower.endswith(ext) for ext in self.static_extensions):
                        continue

                    # 3. 只保留 2xx 状态码的请求
                    if not req.response_status or not (200 <= req.response_status < 300):
                        continue

                    # 4. 检查是否为 API 请求
                    parsed_url = urlparse(req.url)
                    path = parsed_url.path.lower()

                    # 判断是否为 API 请求的多个条件
                    is_api = False

                    # 4.1 URL 路径包含 API 关键词
                    api_keywords = ["/api/", "/sugrec", "/search", "/query", "/v1/", "/v2/"]
                    if any(keyword in url_lower for keyword in api_keywords):
                        is_api = True

                    # 4.2 URL 参数包含 json 相关
                    if not is_api and parsed_url.query:
                        query_params = parse_qs(parsed_url.query)
                        if any(key in query_params for key in ["json", "callback", "jsonp", "format"]):
                            is_api = True

                    # 4.3 响应头明确标识为 JSON
                    if not is_api and req.response_headers:
                        headers_str = str(req.response_headers).lower()
                        if "application/json" in headers_str:
                            is_api = True

                    # 4.4 响应体是 JSON 对象或数组
                    if not is_api and req.response_body:
                        body_stripped = req.response_body.strip()
                        if body_stripped.startswith("{") or body_stripped.startswith("["):
                            is_api = True

                    # 4.5 排除纯页面请求
                    if not is_api:
                        if path in ["/", "", "/index.html", "/index.htm"] and not parsed_url.query:
                            is_api = False
                        elif path.endswith((".html", ".htm")):
                            is_api = False

                    # 只保留 API 请求
                    if is_api:
                        filtered_requests.append(req)

                action.network_requests = filtered_requests or None

        return actions

    def _clean_dom_attributes_basic(self, actions: List[Action]) -> List[Action]:
        """基础 DOM 属性清理（移除 bounding_box）"""
        for action in actions:
            if action.dom_element and isinstance(action.dom_element, dict):
                # 移除 bounding_box（执行时不需要）
                action.dom_element.pop("bounding_box", None)

        return actions


class DataCompressionStage(PipelineStage):
    """阶段 2: 数据压缩（根据级别）"""

    def __init__(self, level: CompressionLevel):
        super().__init__(f"compression_{level.value}")
        self.level = level

    def process(self, context: PipelineContext) -> PipelineContext:
        """执行数据压缩"""
        actions = context.actions

        # 根据压缩级别执行不同的压缩策略
        if self.level == CompressionLevel.NONE:
            compressed = actions
        else:
            # 应用压缩逻辑（这些方法将在 DataPreprocessor 中实现）
            # 这里只是标记压缩级别，实际压缩由 DataPreprocessor 处理
            compressed = actions

        context.actions = compressed
        context.metadata["compression_level"] = self.level.value
        return context


class IntelligenceAnalysisStage(PipelineStage):
    """阶段 3: 智能分析（V2 功能）"""

    def __init__(self, analyzer):
        super().__init__("intelligence_analysis")
        self.analyzer = analyzer

    def process(self, context: PipelineContext) -> PipelineContext:
        """执行智能分析"""
        actions = context.actions
        use_llm = context.metadata.get("use_compression_model", False)

        result = self.analyzer.analyze_requests(actions, use_llm=use_llm)
        context.analysis["intelligence"] = result
        return context


class NetworkAnalysisStage(PipelineStage):
    """阶段 4: 网络分析（V2 功能）"""

    def __init__(self, analyzer):
        super().__init__("network_analysis")
        self.analyzer = analyzer

    def process(self, context: PipelineContext) -> PipelineContext:
        """执行网络分析"""
        actions = context.actions
        result = self.analyzer.analyze_requests(actions)
        context.analysis["network"] = result
        return context


class ListOperationAnalysisStage(PipelineStage):
    """阶段 5: 列表分析（V2 功能）"""

    def __init__(self, analyzer):
        super().__init__("list_operation_analysis")
        self.analyzer = analyzer

    def process(self, context: PipelineContext) -> PipelineContext:
        """执行列表分析"""
        actions = context.actions
        network_result = context.analysis.get("network", [])
        result = self.analyzer.analyze_list_operations(actions, network_result)
        context.analysis["list_operations"] = result
        return context

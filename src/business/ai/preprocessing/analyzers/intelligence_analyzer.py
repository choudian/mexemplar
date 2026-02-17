"""
网络请求智能分析器

使用 LLM 和规则分析哪些网络请求是有意义的。
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.recording.recorder import Action
from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)


class CompressionModelError(Exception):
    """压缩模型调用错误（用于向上传递给 UI）"""
    def __init__(self, message: str, error_type: str = "unknown"):
        super().__init__(message)
        self.error_type = error_type  # 'token_exceeded', 'rate_limit', 'api_error', 'config_error'
        self.message = message


class TokenLimitExceededError(CompressionModelError):
    """Token 超量错误"""
    def __init__(self, message: str):
        super().__init__(message, error_type="token_exceeded")


class RateLimitError(CompressionModelError):
    """请求频率限制错误"""
    def __init__(self, message: str):
        super().__init__(message, error_type="rate_limit")


@dataclass
class RequestAnalysis:
    """请求分析结果"""

    request_id: str
    is_meaningful: bool
    reason: str
    confidence: float = 0.0
    category: str = "other"  # api_call, data_fetch, analytics, heartbeat, other
    is_replayable: bool = False
    # ⭐ 新增字段
    is_recommendation: bool = False  # 是否为推荐内容
    importance_level: str = "unknown"  # 重要性等级: "core" / "secondary" / "meaningless"


class RequestIntelligenceAnalyzer:
    """
    网络请求智能分析器

    职责：
    1. 使用 LLM 分析请求是否对自动化有意义
    2. 基于规则过滤（静态资源、心跳、埋点）
    3. 依赖关系分析（依赖其他请求的请求优先保留）
    4. 加密检测（加密的请求可能无法复现）
    """

    def __init__(self, config_manager: Optional[Any] = None):
        """
        初始化分析器

        Args:
            config_manager: 统一配置管理器（可选，默认使用全局实例）
        """
        # 使用统一配置管理器
        self.config = config_manager or get_unified_config()

        # 检查是否启用数据压缩模型
        self.compression_model_enabled = self.config.get_compression_model_enabled()
        self.compression_model_provider = self.config.get_compression_model_provider()
        self.compression_model_name = self.config.get_compression_model_name()
        self.api_key = self.config.get_compression_model_api_key()
        self.base_url = self.config.get_compression_model_base_url()

        # 初始化组件
        self._encryption_detector = EncryptionDetector()
        self._dependency_analyzer = DependencyAnalyzer()

        # 如果启用了压缩模型但未配置 API key，记录警告
        if self.compression_model_enabled and not self.api_key:
            logger.warning("[智能过滤] 数据压缩模型已启用但未配置 API key，将仅使用规则引擎")
            self.compression_model_enabled = False

        # 记录配置信息
        if self.compression_model_enabled:
            logger.info(
                f"[智能过滤] 数据压缩模型已启用: {self.compression_model_provider}/{self.compression_model_name}"
            )
            if self.base_url:
                logger.info(f"[智能过滤] 自定义 endpoint: {self.base_url}")

        # ⭐ 推荐内容识别模式
        self.recommendation_patterns = [
            "/recommend",
            "/recomm",
            "/suggestion",
            "/suggest",
            "/personalize",
            "/for-you",
            "/foryou",
            "/related",
            "/similar",
            "/also-like",
            "/pickup",
            "/pick-for-you",
        ]

        self.suggestion_patterns = [
            "/sugrec",
            "/suggest",
            "/autocomplete",
            "/completion",
            "/ac",
        ]

        # 规则配置
        self.static_extensions = {
            ".js",
            ".css",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
            ".eot",
            ".mp4",
            ".mp3",
            ".avi",
            ".mov",
        }
        self.analytics_patterns = [
            "google-analytics",
            "gtag",
            "analytics",
            "tracking",
            "telemetry",
            "mixpanel",
            "amplitude",
            "segment",
            "metrics",
        ]
        self.heartbeat_patterns = ["heartbeat", "ping", "keepalive", "alive", "health"]

        # 广告网络域名配置
        self.ad_network_domains = [
            # Google AdSense
            "googlesyndication.com",
            "doubleclick.net",
            "googleadservices.com",
            "googleadsserving.cn",
            # 百度联盟
            "baidustatic.com",
            "cpro.baidu.com",
            "pos.baidu.com",
            "e.click.baidu.com",
            # 阿里妈妈
            "mmstat.com",
            "alimama.com",
            "atm.baidu.com",
            "alicdn.com",  # 阿里 CDN（包含 mm/ap.js 等广告脚本）
            # 腾讯广点通
            "tgclick.qq.com",
            "e.qq.com",
            "a.qq.com",
            "beacon.qq.com",
            # 头条联盟
            "touclick.com",
            "tantengjt.com",
            # 360联盟
            "media.360.cn",
            "s.360.cn",
            # 其他广告网络
            "admaster.com.cn",
            "ad.cnzz.com",
            "ads-twitter.com",
            "amazon-adsystem.com",
            "advertising.com",
            "adserver.com",
            "adtech.net",
            "criteo.com",
            "outbrain.com",
            "taboola.com",
        ]

        # 广告关键词模式
        self.ad_keywords = [
            "ad",
            "adv",
            "广告",
            "推广",
            "guanggiao",
            "banner",
            "sidebar",
            "popup",
        ]

        # 常见广告尺寸参数
        self.ad_sizes = [
            "300x250",
            "728x90",
            "160x600",
            "336x280",
            "970x90",
            "320x50",
        ]

    def analyze_requests(
        self, actions: List[Action], use_llm: bool = False
    ) -> List[RequestAnalysis]:
        """
        分析多个请求

        Args:
            actions: 录制的 Action 列表（包含网络请求）
            use_llm: 是否使用 LLM 分析（数据压缩模型）

        Returns:
            分析结果列表

        Raises:
            CompressionModelError: 当压缩模型调用失败且无法降级时抛出
        """
        # 记录分析策略
        if use_llm:
            if self.compression_model_enabled and self.api_key:
                logger.info("[智能过滤] 使用策略: 规则引擎 + 数据压缩模型")
            else:
                logger.warning("[智能过滤] 要求数据压缩模型但未启用或未配置 API key，回退到规则引擎")
                use_llm = False
        else:
            logger.info("[智能过滤] 使用策略: 仅规则引擎")

        # 1. 提取所有网络请求
        all_requests = self._extract_all_requests(actions)

        # 2. 分析依赖关系
        dependency_graph = self._dependency_analyzer.build_dependency_graph(all_requests)

        # 3. 基于规则预分析
        rule_based_results = {}
        for req_id, req_data in all_requests.items():
            result = self._rule_based_analysis(req_data, dependency_graph)
            rule_based_results[req_id] = result

            # ⭐ 记录规则引擎的决策（反馈循环）
            self.log_filter_decision(
                req_id=req_id,
                decision="keep" if result.is_meaningful else "filter",
                source="rule",
                confidence=result.confidence,
                reason=result.reason,
            )

        # 4. 可选：使用 LLM 深度分析
        if use_llm and self.api_key:
            try:
                # ⭐ 动态调整过滤阈值（根据请求数量）
                total_requests = len(all_requests)
                if total_requests > 1000:
                    dynamic_confidence_threshold = 0.8
                    logger.info(f"[智能过滤] 请求数量较多（{total_requests}），使用高过滤阈值: {dynamic_confidence_threshold}")
                elif total_requests > 500:
                    dynamic_confidence_threshold = 0.7
                    logger.info(f"[智能过滤] 请求数量中等（{total_requests}），使用中等过滤阈值: {dynamic_confidence_threshold}")
                else:
                    dynamic_confidence_threshold = 0.5
                    logger.info(f"[智能过滤] 请求数量较少（{total_requests}），使用保守过滤阈值: {dynamic_confidence_threshold}")

                llm_results = self._llm_based_analysis(all_requests, dependency_graph, actions)

                # 合并结果（规则引擎的明确判断优先，添加置信度阈值）
                for req_id, llm_result in llm_results.items():
                    rule_result = rule_based_results.get(req_id)

                    # 检查规则引擎结果
                    if rule_result:
                        rule_confidence = getattr(rule_result, "confidence", 0.0)
                        rule_is_meaningful = getattr(rule_result, "is_meaningful", False)

                        # 规则引擎的明确判断优先（置信度 >= 0.8）
                        if rule_confidence >= 0.8:
                            logger.debug(
                                f"[智能过滤] 规则引擎明确判断优先: {req_id}, "
                                f"is_meaningful={rule_is_meaningful}, confidence={rule_confidence}"
                            )
                            continue  # 跳过，不使用LLM结果

                    # 检查LLM结果的置信度（使用动态阈值）
                    llm_confidence = float(getattr(llm_result, "confidence", 0.5))
                    llm_is_meaningful = getattr(llm_result, "is_meaningful", False)

                    # 添加动态置信度阈值：低置信度强制过滤
                    if llm_is_meaningful and llm_confidence < dynamic_confidence_threshold:
                        logger.debug(
                            f"[智能过滤] LLM置信度低于动态阈值（{llm_confidence:.2f} < {dynamic_confidence_threshold}），强制过滤: {req_id}"
                        )
                        llm_result.is_meaningful = False
                        llm_result.reason = (
                            f"LLM置信度低于动态阈值（{llm_confidence:.2f} < {dynamic_confidence_threshold}），{llm_result.reason}"
                        )

                    # 使用LLM结果（或修改后的结果）
                    rule_based_results[req_id] = llm_result

                    # ⭐ 记录 LLM 的决策（反馈循环）
                    pattern_matched = getattr(llm_result, "pattern_matched", "none") if hasattr(llm_result, "pattern_matched") else "none"
                    scores = getattr(llm_result, "scores", {}) if hasattr(llm_result, "scores") else {}

                    self.log_filter_decision(
                        req_id=req_id,
                        decision="keep" if llm_result.is_meaningful else "filter",
                        source="llm",
                        confidence=llm_result.confidence,
                        reason=llm_result.reason,
                        pattern_matched=pattern_matched,
                        scores=scores,
                    )

            except TokenLimitExceededError as e:
                # Token 超量：记录警告，回退到规则引擎，但继续处理
                logger.warning(f"[智能过滤] 压缩模型 Token 超量，回退到规则引擎: {e}")
                logger.info("[智能过滤] 将使用规则引擎结果继续处理")
                # 不抛出异常，继续使用规则引擎的结果

            except RateLimitError as e:
                # 频率限制：记录警告，回退到规则引擎
                logger.warning(f"[智能过滤] 压缩模型请求频率限制，回退到规则引擎: {e}")
                logger.info("[智能过滤] 将使用规则引擎结果继续处理")
                # 不抛出异常，继续使用规则引擎的结果

            except CompressionModelError as e:
                # 其他压缩模型错误：根据错误类型决定是否继续
                if e.error_type in ["config_error", "empty_response", "parse_error"]:
                    # 配置错误或响应解析错误：可以降级
                    logger.warning(f"[智能过滤] 压缩模型错误，回退到规则引擎: {e}")
                    logger.info("[智能过滤] 将使用规则引擎结果继续处理")
                else:
                    # API 错误：向上传递，让调用者决定
                    logger.error(f"[智能过滤] 压缩模型 API 错误: {e}")
                    raise

        # 5. ⭐ 推荐内容识别和重要性分析
        for req_id, result in rule_based_results.items():
            req_data = all_requests.get(req_id)
            if req_data:
                # 提取响应数据
                response_data = None
                try:
                    response_body = req_data.get("response_body", "")
                    if response_body and isinstance(response_body, str):
                        import json

                        try:
                            response_data = json.loads(response_body)
                        except json.JSONDecodeError:
                            pass
                except Exception:
                    pass

                # 分析重要性
                result = self._analyze_importance(req_data.get("url", ""), response_data, result)
                rule_based_results[req_id] = result

        return list(rule_based_results.values())

    def log_filter_decision(
        self,
        req_id: str,
        decision: str,  # "keep" or "filter"
        source: str,  # "rule" or "llm"
        confidence: float,
        reason: str,
        pattern_matched: str = "none",
        scores: Dict[str, float] = None,
        action_id: Optional[int] = None,
        recording_id: Optional[str] = None,
        request_timestamp: Optional[float] = None,
    ):
        """
        记录过滤决策（用于反馈循环）

        这个方法会记录：
        1. 过滤决策（保留/过滤）
        2. 决策来源（规则引擎/LLM）
        3. 置信度
        4. 判断理由
        5. 匹配的模式（V2提示词）
        6. 各维度评分（V2提示词）
        7. 关联的 action_id 和 recording_id（新增）
        8. 请求和操作时间戳（新增）

        Args:
            req_id: 请求 ID
            decision: 决策（"keep" or "filter"）
            source: 决策来源（"rule" or "llm"）
            confidence: 置信度
            reason: 判断理由
            pattern_matched: 匹配的模式
            scores: 各维度评分
            action_id: 关联的操作 ID
            recording_id: 录制会话 ID
            request_timestamp: 请求时间戳
        """
        try:
            from src.data.duckdb_manager import DuckDBManager

            duckdb = DuckDBManager()
            conn = duckdb.connect()

            # 获取请求和时间戳信息（如果没有提供）
            if action_id is None or request_timestamp is None:
                try:
                    req_info = conn.execute(
                        """
                        SELECT action_id, timestamp
                        FROM network_requests
                        WHERE CAST(request_id AS VARCHAR) = ?
                        LIMIT 1
                    """,
                        (req_id,),
                    ).fetchone()

                    if req_info:
                        if action_id is None:
                            action_id = req_info[0]
                        if request_timestamp is None:
                            request_timestamp = req_info[1].timestamp() if req_info[1] else None
                except Exception:
                    pass

            # 获取 recording_id（如果还没有）
            if recording_id is None and action_id is not None:
                try:
                    rec_info = conn.execute(
                        "SELECT recording_id, timestamp FROM actions WHERE action_id = ?",
                        (action_id,),
                    ).fetchone()

                    if rec_info:
                        recording_id = rec_info[0]
                except Exception:
                    pass

            # 插入记录（包含新字段）
            conn.execute(
                """
                INSERT INTO filter_decisions (
                    request_id, action_id, recording_id, decision, source, confidence, reason,
                    pattern_matched, scores, request_timestamp, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, TO_TIMESTAMP(?), TO_TIMESTAMP(?))
            """,
                [
                    req_id,
                    action_id,
                    recording_id,
                    decision,
                    source,
                    confidence,
                    reason,
                    pattern_matched,
                    str(scores) if scores else "{}",
                    request_timestamp or time.time(),
                    time.time(),
                ],
            )

            logger.debug(f"[反馈循环] 已记录过滤决策: {req_id} -> {decision} (source: {source})")

        except Exception as e:
            logger.error(f"[反馈循环] 记录失败: {e}")
            # 不影响主流程，静默失败

    def get_meaningful_requests(
        self, actions: List[Action], use_llm: bool = False
    ) -> List[Dict[str, Any]]:
        """
        获取有意义的网络请求列表

        Args:
            actions: 录制的 Action 列表
            use_llm: 是否使用 LLM 分析

        Returns:
            过滤后的有意义请求列表
        """
        analyses = self.analyze_requests(actions, use_llm=use_llm)

        # 构建请求 ID 到完整请求的映射
        all_requests = self._extract_all_requests(actions)

        # 分析依赖关系（用于排序）
        dependency_graph = self._dependency_analyzer.build_dependency_graph(all_requests)

        # 筛选有意义的请求
        meaningful = []
        for analysis in analyses:
            if analysis.is_meaningful:
                req_data = all_requests.get(analysis.request_id)
                if req_data:
                    meaningful.append(
                        {
                            "request_id": analysis.request_id,
                            "url": req_data.get("url"),
                            "method": req_data.get("method"),
                            "analysis": analysis,
                            "full_data": req_data,
                        }
                    )

        # 按依赖关系排序（被依赖的优先）
        meaningful.sort(
            key=lambda x: dependency_graph.get(x["request_id"], {}).get("used_by_count", 0),
            reverse=True,
        )

        return meaningful

    def count_meaningful_requests(self, actions: List[Action], use_llm: bool = False) -> int:
        """
        统计有意义的请求数量

        Args:
            actions: 录制的 Action 列表
            use_llm: 是否使用 LLM 分析

        Returns:
            有意义的请求数量
        """
        analyses = self.analyze_requests(actions, use_llm=use_llm)
        return sum(1 for a in analyses if a.is_meaningful)

    # ========== 私有方法 ==========

    def _extract_all_requests(self, actions: List[Action]) -> Dict[str, Dict[str, Any]]:
        """
        从 Actions 中提取所有网络请求

        Returns:
            {request_id: request_data} 字典
            - request_id 优先使用数据库ID（整数），其次使用生成ID（字符串）
        """
        requests = {}
        for action in actions:
            if not action.network_requests:
                continue
            for req in action.network_requests:
                # 处理 NetworkRequest 对象或字典
                if hasattr(req, "to_dict"):
                    req_dict = req.to_dict()
                else:
                    req_dict = req

                # ⭐ 优先使用数据库ID（整数）
                db_request_id = req_dict.get("request_id")
                if db_request_id is not None:
                    # 使用数据库ID（整数）
                    req_id = db_request_id
                else:
                    # 降级：生成字符串ID（兼容从队列文件加载的情况）
                    import time
                    req_id = f"{int(action.timestamp)}_{int(time.time() * 1000) % 10000}"

                requests[req_id] = {
                    "request_id": req_id,
                    "url": req_dict.get("url", ""),
                    "method": req_dict.get("method", "GET"),
                    "request_body": req_dict.get("request_body", {}),
                    "status_code": req_dict.get("response_status", req_dict.get("status_code", 0)),
                    "response_body": req_dict.get("response_body", ""),
                    "headers": req_dict.get("response_headers", req_dict.get("headers", {})),
                    "action": action,
                    "raw_data": req_dict,
                }
        return requests

    def _rule_based_analysis(
        self, req_data: Dict[str, Any], dependency_graph: Dict[str, Dict]
    ) -> RequestAnalysis:
        """
        基于规则的分析（快速、低成本）

        判断逻辑：
        1. 静态资源 → 无意义
        2. 心跳请求 → 无意义
        3. 埋点请求 → 无意义
        4. 加密响应 → 可能无法复现
        5. 被 N 个请求依赖 → 有意义
        6. JSON/HTML 响应 → 可能有意义
        7. ⭐ 新增：表单数据源识别
        8. ⭐ 新增：核心业务操作识别
        """
        req_id = req_data["request_id"]
        url = req_data["url"].lower()
        response_body = req_data.get("response_body", "")
        content_type = req_data.get("headers", {}).get("content-type", "")
        method = req_data.get("method", "GET").upper()
        action = req_data.get("action")

        # ⭐ 新增规则 0：表单数据源识别（模式A）
        # 特征：GET请求返回数组结构，包含 id/name 或 code/label
        if method == "GET" and "application/json" in content_type:
            try:
                import json

                if response_body:
                    data = json.loads(response_body)
                    # 检查是否为数组，且包含 id/name 或 code/label 结构
                    if isinstance(data, list) and len(data) > 0:
                        first_item = data[0] if isinstance(data[0], dict) else {}
                        # 检查是否为选项数据结构
                        if any(key in first_item for key in ["id", "code"]) and any(
                            key in first_item for key in ["name", "label", "title"]
                        ):
                            # 进一步验证：检查 URL 是否包含数据源关键词
                            datasource_keywords = [
                                "cities",
                                "provinces",
                                "categories",
                                "types",
                                "options",
                                "list",
                                "enum",
                                "dictionary",
                            ]
                            if any(kw in url for kw in datasource_keywords):
                                return RequestAnalysis(
                                    request_id=req_id,
                                    is_meaningful=True,
                                    reason=f"表单数据源（返回{len(data)}个选项）",
                                    category="data_fetch",
                                    confidence=0.9,
                                    is_replayable=True,
                                )
            except (json.JSONDecodeError, TypeError, IndexError):
                pass  # JSON 解析失败，继续其他规则

        # ⭐ 新增规则 0.5：核心业务操作识别（模式B）
        # 特征：URL 包含核心业务关键词
        core_operation_keywords = ["search", "query", "submit", "create", "update", "delete", "login", "checkout", "order", "pay"]
        if any(kw in url for kw in core_operation_keywords):
            # 排除明显的统计/埋点
            if not any(kw in url for kw in self.analytics_patterns + self.heartbeat_patterns):
                return RequestAnalysis(
                    request_id=req_id,
                    is_meaningful=True,
                    reason=f"核心业务操作（URL包含: {[kw for kw in core_operation_keywords if kw in url][0]}）",
                    category="api_call",
                    confidence=0.85,
                    is_replayable=True,
                )

        # ⭐ 新增规则 0.8：推荐内容识别（模式E）
        # 特征：URL 包含推荐/个性化关键词
        recommendation_patterns = [
            "/recommend",
            "/recomm",
            "/suggestion",
            "/suggest",
            "/personalize",
            "/for-you",
            "/foryou",
            "/related",
            "/similar",
            "/also-like",
        ]
        if any(pattern in url for pattern in recommendation_patterns):
            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=False,
                reason="推荐内容请求（与用户主动操作无关）",
                category="analytics",
                confidence=0.85,
                is_recommendation=True,  # ⭐ 标记为推荐内容
                importance_level="secondary",
            )

        # ⭐ 新增规则 0.9：资源预加载识别（模式F）
        # 特征：URL 包含 prefetch/preload，或 Link header 包含 rel=prefetch
        if "prefetch" in url or "preload" in url:
            # 检查是否在用户操作之前触发（通过 action 判断）
            if action and action.action_type in ["navigate", "page_load"]:
                return RequestAnalysis(
                    request_id=req_id,
                    is_meaningful=False,
                    reason="资源预加载（用户未实际访问）",
                    category="other",
                    confidence=0.8,
                )

        # 规则 1: 广告网络域名检测（优先级最高）
        if any(ad_domain in url for ad_domain in self.ad_network_domains):
            # 识别具体的广告网络
            ad_network = "未知广告网络"
            if "google" in url or "doubleclick" in url:
                ad_network = "Google AdSense"
            elif "baidu" in url:
                ad_network = "百度联盟"
            elif "mmstat" in url or "alimama" in url:
                ad_network = "阿里妈妈"
            elif "qq.com" in url:
                ad_network = "腾讯广点通"
            elif "360.cn" in url:
                ad_network = "360联盟"

            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=False,
                reason=f"广告请求：{ad_network}",
                category="advertising",
                confidence=0.95,  # 高置信度
            )

        # 规则 2: 广告关键词和文件检测
        # 检查 URL 路径中是否包含广告关键词
        url_path = url.split("?")[0]  # 移除查询参数
        if any(f"/{kw}" in url_path or f"{kw}." in url_path for kw in self.ad_keywords):
            # 检查是否是广告文件（静态资源）
            if any(url.endswith(ext) for ext in self.static_extensions):
                return RequestAnalysis(
                    request_id=req_id,
                    is_meaningful=False,
                    reason=f"广告文件：包含广告关键词 {url_path}",
                    category="advertising",
                    confidence=0.9,
                )

        # 规则 3: 广告尺寸参数检测
        if any(size in url for size in self.ad_sizes):
            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=False,
                reason=f"广告请求：包含广告尺寸参数 {url}",
                category="advertising",
                confidence=0.85,
            )

        # 规则 4: 静态资源
        if any(url.endswith(ext) for ext in self.static_extensions):
            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=False,
                reason=f"静态资源 ({url.split('.')[-1]})",
                category="static",
                confidence=0.95,  # 高置信度
            )

        # 规则 5: 心跳请求
        if any(pattern in url for pattern in self.heartbeat_patterns):
            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=False,
                reason="心跳/健康检查",
                category="heartbeat",
                confidence=0.95,  # 高置信度
            )

        # 规则 6: 埋点请求
        if any(pattern in url for pattern in self.analytics_patterns):
            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=False,
                reason="数据分析/埋点",
                category="analytics",
                confidence=0.9,  # 高置信度
            )

        # 规则 7: 加密检测
        if self._encryption_detector.is_encrypted(response_body):
            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=False,
                reason="响应数据已加密，无法复现",
                category="encrypted",
                is_replayable=False,
                confidence=0.9,  # 高置信度
            )

        # 规则 8: 依赖关系（被其他请求依赖 → 很重要）
        dep_info = dependency_graph.get(req_id, {})
        used_by_count = dep_info.get("used_by_count", 0)
        if used_by_count > 0:
            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=True,
                reason=f"被 {used_by_count} 个请求依赖",
                confidence=0.9,
                category="api_call",
                is_replayable=True,
            )

        # 规则 9: JSON/HTML 响应 → 可能有意义
        if "application/json" in content_type or "text/html" in content_type:
            return RequestAnalysis(
                request_id=req_id,
                is_meaningful=True,
                reason="返回业务数据（JSON/HTML）",
                confidence=0.7,
                category="data_fetch",
                is_replayable=True,
            )

        # 规则 10: 其他响应 → 可能无意义
        return RequestAnalysis(
            request_id=req_id,
            is_meaningful=False,
            reason="未识别为业务请求",
            category="other",
            is_replayable=False,
            confidence=0.5,  # 低置信度，允许LLM覆盖
        )

    def _llm_based_analysis(
        self,
        all_requests: Dict[str, Dict[str, Any]],
        dependency_graph: Dict[str, Dict],
        all_actions: List[Action],
    ) -> Dict[str, RequestAnalysis]:
        """
        使用 LLM 深度分析（较慢、有成本）

        实现逻辑：
        1. 为每个请求生成分析提示词
        2. 调用压缩模型 API
        3. 解析 LLM 响应
        4. 转换为 RequestAnalysis 对象

        支持多线程并发处理（通过配置控制）

        Args:
            all_requests: 所有请求的字典
            dependency_graph: 依赖关系图
            all_actions: 所有操作列表（用于提取上下文）
        """
        # 获取线程数配置
        num_threads = self.config.get_compression_model_threads()

        if num_threads <= 1:
            # 单线程模式（原有逻辑）
            logger.info("[智能过滤] 使用单线程模式进行 LLM 分析")
            return self._llm_analysis_single_thread(all_requests, dependency_graph, all_actions)
        else:
            # 多线程模式
            logger.info(f"[智能过滤] 使用多线程模式进行 LLM 分析，线程数: {num_threads}")
            return self._llm_analysis_multi_thread(all_requests, dependency_graph, num_threads, all_actions)

    def _llm_analysis_single_thread(
        self,
        all_requests: Dict[str, Dict[str, Any]],
        dependency_graph: Dict[str, Dict],
        all_actions: List[Action],
    ) -> Dict[str, RequestAnalysis]:
        """单线程分析（原有逻辑）

        Args:
            all_requests: 所有请求的字典
            dependency_graph: 依赖关系图
            all_actions: 所有操作列表（用于提取上下文）
        """
        results = {}
        total_requests = len(all_requests)
        start_time = time.time()

        logger.info(f"[智能过滤] 开始 LLM 深度分析（单线程），共 {total_requests} 个请求")

        # 遍历所有请求进行分析
        for idx, (req_id, req_data) in enumerate(all_requests.items(), 1):
            try:
                # 1. 生成分析提示词
                prompt = self._generate_analysis_prompt(req_data, dependency_graph, all_actions)

                logger.debug(f"[智能过滤] 请求 {idx}/{total_requests}: {req_id}")
                logger.debug(f"[智能过滤] Prompt 长度: {len(prompt)} 字符")

                # 2. 调用压缩模型
                llm_response = self._call_compression_model(prompt)

                # 3. 解析响应
                analysis = self._parse_llm_response(req_id, llm_response, req_data)

                results[req_id] = analysis

                logger.info(
                    f"[智能过滤] {req_id}: is_meaningful={analysis.is_meaningful}, "
                    f"reason={analysis.reason}, confidence={analysis.confidence}"
                )

            except Exception as e:
                # 错误处理：记录错误但继续处理其他请求
                logger.error(f"[智能过滤] 分析请求 {req_id} 失败: {e}", exc_info=True)

                # 返回保守结果（标记为无意义）
                results[req_id] = RequestAnalysis(
                    request_id=req_id,
                    is_meaningful=False,
                    reason=f"LLM 分析失败: {str(e)}",
                    confidence=0.0,
                    category="other",
                    is_replayable=False,
                )

        elapsed_time = time.time() - start_time
        logger.info(
            f"[智能过滤] LLM 深度分析完成（单线程），"
            f"成功分析 {len(results)}/{total_requests} 个请求，"
            f"耗时 {elapsed_time:.2f} 秒，"
            f"平均 {elapsed_time / total_requests:.2f} 秒/请求"
        )

        return results

    def _llm_analysis_multi_thread(
        self,
        all_requests: Dict[str, Dict[str, Any]],
        dependency_graph: Dict[str, Dict],
        num_threads: int,
        all_actions: List[Action],
    ) -> Dict[str, RequestAnalysis]:
        """多线程并发分析

        Args:
            all_requests: 所有请求的字典
            dependency_graph: 依赖关系图
            num_threads: 线程数
            all_actions: 所有操作列表（用于提取上下文）
        """
        results = {}
        request_items = list(all_requests.items())
        total_requests = len(request_items)
        start_time = time.time()

        logger.info(
            f"[智能过滤] 开始 LLM 深度分析（多线程，{num_threads} 线程），共 {total_requests} 个请求"
        )

        # 使用线程池
        with ThreadPoolExecutor(
            max_workers=num_threads, thread_name_prefix="llm_analyzer"
        ) as executor:
            # 提交所有任务
            future_to_req_id = {
                executor.submit(
                    self._analyze_single_request,
                    req_id,
                    req_data,
                    dependency_graph,
                    all_actions,
                ): req_id
                for req_id, req_data in request_items
            }

            # 收集结果
            completed_count = 0
            for future in as_completed(future_to_req_id):
                req_id = future_to_req_id[future]
                try:
                    result = future.result()
                    results[req_id] = result

                    completed_count += 1

                    # 记录进度（每完成 10 个或全部完成）
                    if completed_count % 10 == 0 or completed_count == total_requests:
                        logger.info(
                            f"[智能过滤] 多线程分析进度: {completed_count}/{total_requests}"
                        )

                except Exception as e:
                    logger.error(f"[智能过滤] 分析请求 {req_id} 失败: {e}", exc_info=True)
                    results[req_id] = RequestAnalysis(
                        request_id=req_id,
                        is_meaningful=False,
                        reason=f"LLM 分析失败: {str(e)}",
                        confidence=0.0,
                        category="other",
                        is_replayable=False,
                    )

        elapsed_time = time.time() - start_time

        # 避免除零错误
        avg_time = elapsed_time / total_requests if total_requests > 0 else 0
        throughput = total_requests / elapsed_time if elapsed_time > 0 else 0

        logger.info(
            f"[智能过滤] LLM 深度分析完成（多线程），"
            f"成功分析 {len(results)}/{total_requests} 个请求，"
            f"耗时 {elapsed_time:.2f} 秒，"
            f"平均 {avg_time:.2f} 秒/请求，"
            f"吞吐量 {throughput:.2f} 请求/秒"
        )

        return results

    def _analyze_single_request(
        self,
        req_id: str,
        req_data: Dict[str, Any],
        dependency_graph: Dict[str, Dict],
        all_actions: List[Action],
    ) -> RequestAnalysis:
        """
        分析单个请求（线程安全）

        Args:
            req_id: 请求 ID
            req_data: 请求数据
            dependency_graph: 依赖关系图
            all_actions: 所有操作列表（用于提取上下文）

        Returns:
            RequestAnalysis 对象
        """
        # 生成提示词
        prompt = self._generate_analysis_prompt(req_data, dependency_graph, all_actions)

        # 调用 LLM（线程安全，LangChain 的 chat() 方法是线程安全的）
        llm_response = self._call_compression_model(prompt)

        # 解析响应
        analysis = self._parse_llm_response(req_id, llm_response, req_data)

        return analysis

    def _generate_analysis_prompt(
        self, req_data: Dict[str, Any], dependency_graph: Dict[str, Dict], all_actions: List[Action] = None
    ) -> str:
        """
        生成 LLM 分析提示词

        Args:
            req_data: 请求数据
            dependency_graph: 依赖关系图
            all_actions: 所有操作列表（用于提取上下文）

        Returns:
            完整的提示词字符串
        """
        from src.business.ai.prompts.request_analysis_prompts import JUDGMENT_PROMPT_V2_TEMPLATE

        # 提取请求信息
        url = req_data.get("url", "")
        method = req_data.get("method", "GET")
        request_body = req_data.get("request_body", {})

        # 提取响应信息
        status_code = req_data.get("status_code", 0)
        headers = req_data.get("headers", {})
        content_type = headers.get("content-type", "")
        response_body = req_data.get("response_body", "")

        # 响应体预览（限制 500 字符）
        response_body_preview = response_body[:500] if response_body else ""

        # 提取关联的用户操作信息
        action = req_data.get("action")

        # 提取上下文信息（用于 V2 提示词）
        current_action = action
        if current_action and all_actions:
            # 找到当前 action 在列表中的位置
            try:
                current_index = all_actions.index(current_action)

                # 提取最近3步操作（包括当前操作）
                recent_actions = []
                start_idx = max(0, current_index - 2)
                for i in range(start_idx, min(current_index + 1, len(all_actions))):
                    act = all_actions[i]
                    desc = f"{i - start_idx + 1}. {act.action_type}"
                    if act.url:
                        desc += f" (URL: {act.url})"
                    if act.window_title:
                        desc += f" (窗口: {act.window_title})"
                    recent_actions.append(desc)

                # 提取后续操作预览（接下来1-2步）
                subsequent_actions = []
                for i in range(current_index + 1, min(current_index + 3, len(all_actions))):
                    act = all_actions[i]
                    desc = f"{act.action_type}"
                    if act.url:
                        desc += f" (URL: {act.url})"
                    if act.window_title:
                        desc += f" (窗口: {act.window_title})"
                    subsequent_actions.append(desc)

                # 计算发生时机（与上一步操作的时间差）
                if current_index > 0:
                    prev_action = all_actions[current_index - 1]
                    time_diff = current_action.timestamp - prev_action.timestamp
                    # 兼容处理 float 和 datetime 两种类型
                    if hasattr(time_diff, "total_seconds"):
                        # datetime.timedelta 对象
                        time_diff_seconds = time_diff.total_seconds()
                    else:
                        # float 类型（秒）
                        time_diff_seconds = time_diff

                    if time_diff_seconds < 1:
                        timing = f"紧接着上一步操作（{time_diff_seconds:.2f}秒）"
                    elif time_diff_seconds < 5:
                        timing = f"上一步操作后{time_diff_seconds:.2f}秒"
                    else:
                        timing = f"上一步操作后{time_diff_seconds:.2f}秒（可能有延迟）"
                else:
                    timing = "第一步操作"

                # 提取当前页面
                current_page = current_action.url or current_action.window_title or "未知页面"

                # 提取核心操作
                core_actions = [act.action_type for act in all_actions if act.action_type not in ["wait", "screenshot"]]
                core_actions_str = ", ".join(core_actions[:5])  # 最多显示5个
                if len(core_actions) > 5:
                    core_actions_str += f" 等{len(core_actions)}个操作"

            except (ValueError, IndexError):
                # 找不到当前 action，使用默认值
                recent_actions = ["1. 未知操作"]
                subsequent_actions = []
                timing = "未知时机"
                current_page = "未知页面"
                core_actions_str = "未知操作"
        else:
            # 没有 all_actions 或当前 action，使用默认值
            recent_actions = ["1. 未知操作"]
            subsequent_actions = []
            timing = "未知时机"
            current_page = "未知页面"
            core_actions_str = "未知操作"

        # 格式化为字符串
        recent_action_1 = recent_actions[0] if len(recent_actions) > 0 else ""
        recent_action_2 = recent_actions[1] if len(recent_actions) > 1 else ""
        recent_action_3 = recent_actions[2] if len(recent_actions) > 2 else ""
        subsequent_operations = "\n".join(subsequent_actions) if subsequent_actions else "无"

        # 判断数据类型
        data_type = "xhr_request"
        if url.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2")):
            data_type = "resource_load"
        elif action and action.action_type in ["click", "input", "submit"]:
            data_type = "xhr_request"
        elif "prefetch" in url or "preload" in url:
            data_type = "prefetch"

        # 提取元素信息（用于兼容）
        if action and action.dom_element:
            element = action.dom_element
            tag = element.get("tag", "")
            text = element.get("text", "")[:30]  # 限制长度
            element_info = f"<{tag}> text='{text}'"
        else:
            element_info = "N/A"

        # 依赖信息
        req_id = req_data["request_id"]
        dep_info = dependency_graph.get(req_id, {})
        used_by_count = dep_info.get("used_by_count", 0)

        # 填充 V2 提示词模板
        try:
            prompt = JUDGMENT_PROMPT_V2_TEMPLATE.format(
                request_id=req_id,  # ⭐ 传入数据库ID
                current_page=current_page,
                core_actions=core_actions_str,
                recent_action_1=recent_action_1,
                recent_action_2=recent_action_2,
                recent_action_3=recent_action_3,
                data_type=data_type,
                url=url,
                method=method,
                request_body=str(request_body)[:500],  # 限制长度
                status_code=status_code,
                content_type=content_type,
                response_body_preview=response_body_preview,
                timing=timing,
                subsequent_operations=subsequent_operations,
                used_by_count=used_by_count,
            )
        except KeyError as e:
            logger.error(f"[智能过滤] 提示词模板填充失败，缺少字段: {e}")
            # 回退到旧模板（如果需要）
            raise

        return prompt

    def _parse_llm_response(
        self, req_id: str, llm_response: Dict[str, Any], req_data: Dict[str, Any]
    ) -> RequestAnalysis:
        """
        解析 LLM 响应并转换为 RequestAnalysis 对象

        支持 V1 和 V2 两种响应格式：
        - V1: is_meaningful, category (api_call/data_fetch/analytics/heartbeat/other)
        - V2: is_relevant, category (core_operation/data_source/side_effect/noise/resource)

        ⭐ 重要：验证 LLM 返回的 request_id 是否与我们给的一致

        Args:
            req_id: 我们给 LLM 的请求 ID（数据库ID）
            llm_response: LLM 返回的 JSON 响应
            req_data: 原始请求数据（用于降级处理）

        Returns:
            RequestAnalysis 对象
        """
        try:
            # ⭐ 验证 LLM 返回的 request_id 是否正确
            returned_req_id = llm_response.get("request_id")
            if returned_req_id is not None:
                # ⭐ 类型转换后再比较（我们给的是 int，LLM 返回的可能是 str）
                try:
                    returned_req_id_converted = int(returned_req_id) if isinstance(returned_req_id, str) else returned_req_id
                    if returned_req_id_converted != req_id:
                        logger.warning(
                            f"[智能过滤] LLM 返回的 request_id ({returned_req_id}, 类型: {type(returned_req_id).__name__}) "
                            f"与我们给的不一致 ({req_id}, 类型: {type(req_id).__name__})，强制使用我们的 ID"
                        )
                    else:
                        logger.debug(f"[智能过滤] {req_id}: LLM 正确返回了 request_id")
                except (ValueError, TypeError):
                    logger.warning(
                        f"[智能过滤] LLM 返回的 request_id ({returned_req_id}) 无法转换为整数，"
                        f"与我们给的不一致 ({req_id})，强制使用我们的 ID"
                    )
            else:
                logger.debug(f"[智能过滤] {req_id}: LLM 未返回 request_id")

            # 兼容 V1 和 V2 格式
            # V1 使用 is_meaningful，V2 使用 is_relevant
            is_meaningful = llm_response.get("is_meaningful", llm_response.get("is_relevant", False))

            # V2 的 category 映射到 V1 的 category
            category_v2 = llm_response.get("category", "")
            category_mapping = {
                "core_operation": "api_call",
                "data_source": "data_fetch",
                "side_effect": "api_call",
                "noise": "analytics",
                "resource": "other",
            }
            category = category_mapping.get(category_v2, llm_response.get("category", "other"))

            # 提取其他字段（带默认值）
            reason = llm_response.get("reason", "LLM 未提供理由")
            confidence = float(llm_response.get("confidence", 0.5))
            is_replayable = llm_response.get("is_replayable", True)

            # 提取 V2 特有的字段（用于调试，不影响现有逻辑）
            pattern_matched = llm_response.get("pattern_matched", "none")
            risk_level = llm_response.get("risk_level", "uncertain")
            scores = llm_response.get("scores", {})

            # 记录 V2 的额外信息（用于调试）
            if pattern_matched != "none":
                logger.debug(
                    f"[智能过滤] {req_id}: 匹配模式={pattern_matched}, "
                    f"风险等级={risk_level}, "
                    f"评分={scores}"
                )

            # 验证字段
            if not isinstance(is_meaningful, bool):
                logger.warning(f"[智能过滤] {req_id}: is_meaningful/is_relevant 不是布尔值，使用默认值 False")
                is_meaningful = False

            if not 0.0 <= confidence <= 1.0:
                logger.warning(f"[智能过滤] {req_id}: confidence 超出范围，调整为 0.5")
                confidence = 0.5

            # 加密检测降级：如果 LLM 判断可复现但响应已加密，强制标记为不可复现
            if is_replayable:
                response_body = req_data.get("response_body", "")
                if self._encryption_detector.is_encrypted(response_body):
                    logger.warning(f"[智能过滤] {req_id}: 响应已加密，强制标记为不可复现")
                    is_replayable = False
                    is_meaningful = False
                    reason = f"{reason}（响应已加密）"

            return RequestAnalysis(
                request_id=req_id,  # 使用我们给的ID，而不是LLM返回的
                is_meaningful=is_meaningful,
                reason=reason,
                confidence=confidence,
                category=category,
                is_replayable=is_replayable,
            )

        except Exception as e:
            # 解析失败：返回保守结果
            logger.error(f"[智能过滤] {req_id}: 解析 LLM 响应失败: {e}")
            logger.debug(f"[智能过滤] {req_id}: LLM 响应内容: {llm_response}")

            return RequestAnalysis(
                request_id=req_id,  # 即使失败也使用我们给的ID
                is_meaningful=False,
                reason=f"LLM 响应解析失败: {str(e)}",
                confidence=0.0,
                category="other",
                is_replayable=False,
            )

    def _extract_json_from_response(self, response_text: str) -> Dict[str, Any]:
        """
        从 LLM 响应中提取 JSON

        处理以下情况：
        1. 响应被 ```json 和 ``` 包裹
        2. 响应被 ``` 和 ``` 包裹
        3. 响应前后有多余的空白字符
        4. 响应包含其他说明文字（只提取 JSON 部分）
        5. 使用括号匹配算法提取完整的 JSON 对象（支持嵌套）

        Args:
            response_text: 原始响应文本

        Returns:
            解析后的 JSON 字典

        Raises:
            ValueError: 无法提取有效 JSON
        """
        import json
        import re

        # 去除首尾空白
        response_text = response_text.strip()

        # 情况 1: 提取 ```json``` 代码块中的内容
        json_block_pattern = r"```json\s*(.*?)\s*```"
        match = re.search(json_block_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            logger.debug("[智能过滤] 从 ```json``` 代码块中提取 JSON")
            try:
                result = json.loads(json_str)
                if isinstance(result, dict):
                    return result
                else:
                    logger.warning(f"[智能过滤] LLM 返回的不是字典而是 {type(result)}")
            except json.JSONDecodeError as e:
                logger.warning(f"[智能过滤] ```json``` 代码块解析失败: {e}")

        # 情况 2: 提取 ``` ``` 代码块中的内容（无 json 标记）
        code_block_pattern = r"```\s*(.*?)\s*```"
        match = re.search(code_block_pattern, response_text, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
            # 尝试解析为 JSON
            try:
                logger.debug("[智能过滤] 从 ``` ``` 代码块中提取 JSON")
                result = json.loads(json_str)
                if isinstance(result, dict):
                    return result
                else:
                    logger.warning(f"[智能过滤] LLM 返回的不是字典而是 {type(result)}")
            except json.JSONDecodeError:
                # 如果不是 JSON，继续尝试其他方法
                logger.debug("[智能过滤] ``` ``` 代码块不是有效 JSON，尝试其他方法")

        # 情况 3: 使用括号匹配算法查找完整的 JSON 对象
        # 这个方法支持任意层级的嵌套
        json_str = self._extract_complete_json_object(response_text)
        if json_str:
            try:
                logger.debug("[智能过滤] 使用括号匹配算法提取 JSON 对象")
                result = json.loads(json_str)
                if isinstance(result, dict):
                    return result
                else:
                    logger.warning(f"[智能过滤] LLM 返回的不是字典而是 {type(result)}")
            except json.JSONDecodeError as e:
                logger.warning(f"[智能过滤] 括号匹配提取的 JSON 解析失败: {e}")

        # 情况 4: 直接解析整个响应
        try:
            logger.debug("[智能过滤] 尝试直接解析整个响应")
            result = json.loads(response_text)
            # 验证返回的是字典而不是其他类型（如字符串、数字等）
            if isinstance(result, dict):
                return result
            else:
                # LLM 返回了非字典类型
                logger.error(f"[智能过滤] LLM 返回的不是字典: {type(result)} = {result}")
                raise ValueError(
                    f"LLM 返回的不是 JSON 对象（字典），而是 {type(result).__name__}: {str(result)[:100]}"
                )
        except json.JSONDecodeError as e:
            # 提供更详细的错误信息
            logger.error(f"[智能过滤] JSON 解析失败: {e}")
            logger.error(f"[智能过滤] 响应前500字符: {response_text[:500]}")
            raise ValueError(
                f"无法从响应中提取有效 JSON: {e}\n" f"响应内容: {response_text[:200]}"
            ) from e

    def _extract_complete_json_object(self, text: str) -> Optional[str]:
        """
        使用括号匹配算法提取完整的 JSON 对象

        支持任意层级的嵌套，包括数组和对象

        Args:
            text: 待搜索的文本

        Returns:
            提取到的 JSON 字符串，如果找不到则返回 None
        """
        # 查找第一个 {
        start_idx = text.find("{")
        if start_idx == -1:
            return None

        # 使用栈来匹配括号（同时支持 {} 和 []）
        stack = []
        in_string = False
        escape_next = False

        for i in range(start_idx, len(text)):
            char = text[i]

            # 处理字符串内的转义字符
            if escape_next:
                escape_next = False
                continue

            if char == "\\" and in_string:
                escape_next = True
                continue

            # 处理字符串边界
            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            # 如果在字符串内，跳过括号匹配
            if in_string:
                continue

            # 括号匹配
            if char in "{[":
                stack.append(char)
            elif char in "}]":
                if not stack:
                    # 括号不匹配（多余的右括号）
                    break

                last_bracket = stack.pop()
                # 检查括号是否匹配
                if (char == "}" and last_bracket != "{") or (char == "]" and last_bracket != "["):
                    # 括号类型不匹配
                    break

                # 栈为空，找到完整的对象
                if not stack:
                    json_str = text[start_idx : i + 1]
                    # 验证是否看起来像 JSON（包含基本字段）
                    if any(
                        key in json_str
                        for key in [
                            "is_meaningful",
                            "reason",
                            "confidence",
                            "category",
                            "is_replayable",
                        ]
                    ):
                        return json_str
                    # 如果不包含预期字段，继续寻找下一个完整的对象
                    # 因为可能找到的是嵌套的内部对象
                    start_idx = text.find("{", i + 1)
                    if start_idx == -1:
                        return None
                    # 重置栈并继续
                    stack = []
                    continue

        # 未找到完整的 JSON 对象
        return None

    def _call_compression_model(self, prompt: str) -> Dict[str, Any]:
        """
        调用数据压缩模型进行分析

        Args:
            prompt: 提示词

        Returns:
            模型响应（解析后的字典）

        Raises:
            TokenLimitExceededError: Token 超量
            RateLimitError: 请求频率限制
            CompressionModelError: 其他压缩模型错误
        """
        # 如果未启用压缩模型，返回空结果（不抛出异常）
        if not self.compression_model_enabled or not self.api_key:
            logger.warning("[智能过滤] 数据压缩模型未启用或未配置 API key，跳过 LLM 调用")
            return {}

        try:
            # 延迟导入（避免未安装 LangChain 时的导入错误）
            from src.business.ai.llm_client import create_llm_client

            # 如果客户端还未初始化
            if not hasattr(self, "_llm_client"):
                config = {
                    "provider": self.compression_model_provider,
                    "model": self.compression_model_name,
                    "api_key": self.api_key,
                    "base_url": self.base_url,
                    "temperature": self.config.get_compression_model_temperature(),
                    "max_tokens": self.config.get_compression_model_max_tokens(),
                }
                self._llm_client = create_llm_client(config)
                logger.info("[智能过滤] 数据压缩模型客户端已初始化")

            # 调用模型
            response_text = self._llm_client.chat(prompt)

            # 验证响应是否为空
            if not response_text or not response_text.strip():
                logger.error("[智能过滤] LLM 返回空响应")
                raise CompressionModelError("LLM 返回空响应", error_type="empty_response")

            # 记录原始响应（用于调试）
            logger.debug(f"[智能过滤] LLM 原始响应类型: {type(response_text)}")
            logger.debug(f"[智能过滤] LLM 原始响应长度: {len(response_text)} 字符")
            logger.debug(f"[智能过滤] LLM 原始响应前500字符: {response_text[:500]}")

            # 提取并解析 JSON
            try:
                result = self._extract_json_from_response(response_text)
                logger.debug(f"[智能过滤] LLM 响应解析成功: {result}")
                return result
            except ValueError as e:
                logger.error(f"[智能过滤] LLM 响应 JSON 提取失败: {e}")
                logger.debug(f"[智能过滤] 原始响应: {response_text}")
                raise CompressionModelError(f"LLM 响应不是有效的 JSON: {e}", error_type="parse_error") from e

        except ImportError as e:
            logger.error(f"[智能过滤] LangChain 未安装: {e}")
            raise CompressionModelError(
                "请安装 LangChain: uv add langchain-anthropic langchain-openai",
                error_type="config_error"
            ) from e

        # 捕获 Token 超量错误
        except Exception as e:
            error_message = str(e).lower()

            # Token 超量错误检测
            token_exceeded_patterns = [
                "token limit exceeded",
                "context length exceeded",
                "maximum context length",
                "too many tokens",
                "token数量超过",
                "token 超量",
                "context_length_exceeded",
                "max_tokens",
            ]
            if any(pattern in error_message for pattern in token_exceeded_patterns):
                logger.error(f"[智能过滤] Token 超量错误: {e}")
                raise TokenLimitExceededError(f"压缩模型 Token 超量: {e}") from e

            # 频率限制错误检测
            rate_limit_patterns = [
                "rate limit",
                "too many requests",
                "429",
                "请求过于频繁",
                "rate_limit",
            ]
            if any(pattern in error_message for pattern in rate_limit_patterns):
                logger.error(f"[智能过滤] 请求频率限制: {e}")
                raise RateLimitError(f"压缩模型请求频率限制: {e}") from e

            # 其他错误
            logger.error(f"[智能过滤] 数据压缩模型调用失败: {e}")
            raise CompressionModelError(f"压缩模型调用失败: {e}", error_type="api_error") from e

    def _is_recommendation_request(
        self, url: str, response_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        判断是否为推荐内容请求

        判断依据：
        1. URL 模式匹配
        2. 查询参数特征
        3. 响应体特征

        Args:
            url: 请求 URL
            response_data: 响应数据（可选）

        Returns:
            bool: 是否为推荐内容
        """
        from urllib.parse import urlparse, parse_qs
        import json

        # 1. URL 模式匹配
        url_lower = url.lower()
        if any(pattern in url_lower for pattern in self.recommendation_patterns):
            return True

        # 2. 查询参数特征判断
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)

            # 推荐算法常见参数
            rec_params = ["algorithm", "based", "recommend", "for_you", "for-you"]
            params_str = str(params).lower()
            if any(param in params_str for param in rec_params):
                return True
        except Exception:
            pass  # URL 解析失败，继续其他判断

        # 3. 响应体特征判断
        if response_data:
            try:
                response_str = json.dumps(response_data).lower()
                rec_keywords = ["recommend", "personalize", "for you", "pick", "suggest"]
                if any(keyword in response_str for keyword in rec_keywords):
                    return True
            except Exception:
                pass  # JSON 序列化失败，忽略

        return False

    def _analyze_importance(
        self,
        url: str,
        response_data: Optional[Dict[str, Any]],
        analysis: RequestAnalysis,
    ) -> RequestAnalysis:
        """
        分析请求的重要性等级

        三级分类：
        - core: 核心业务（用户操作直接触发，响应包含用户需要的内容）
        - secondary: 次要内容（推荐算法、搜索建议等）
        - meaningless: 无意义（广告、统计、埋点）

        Args:
            url: 请求 URL
            response_data: 响应数据（可选）
            analysis: 已有的分析结果

        Returns:
            RequestAnalysis: 更新后的分析结果
        """
        # 判断是否为推荐内容
        is_rec = self._is_recommendation_request(url, response_data)

        # 确定重要性等级
        if not analysis.is_meaningful:
            # 无意义的请求
            importance = "meaningless"
        elif is_rec:
            # 推荐内容（次要）
            importance = "secondary"
        else:
            # 核心业务
            importance = "core"

        # 更新分析结果
        analysis.is_recommendation = is_rec
        analysis.importance_level = importance

        return analysis


class EncryptionDetector:
    """加密检测器"""

    def is_encrypted(self, data: str) -> bool:
        """
        判断数据是否被加密

        启发式规则：
        1. 熵值检测（加密数据熵值 > 7.5）
        2. 字符分布均匀
        3. Base64 但解码后仍是乱码
        """
        if not data:
            return False

        # 规则 1: 明显的加密标记（即使很短也识别）
        if data.startswith("gAAAAA"):  # Django 加密标记
            return True

        # 规则 2: 熵值检测（需要足够长度）
        if len(data) >= 50:
            entropy = self._calculate_entropy(data[:500])
            if entropy > 7.5:
                return True

        return False

    def _calculate_entropy(self, data: str) -> float:
        """计算字符串的熵值"""
        import math
        from collections import Counter

        if not data:
            return 0.0

        counter = Counter(data)
        total = len(data)
        entropy = 0.0

        for count in counter.values():
            p = count / total
            entropy -= p * math.log2(p)

        return entropy


class DependencyAnalyzer:
    """依赖关系分析器"""

    def build_dependency_graph(self, requests: Dict[str, Dict[str, Any]]) -> Dict[str, Dict]:
        """
        构建依赖关系图

        检测逻辑：
        1. 请求 B 的 URL 包含请求 A 响应中的 ID
        2. 请求 B 的 headers 使用了请求 A 返回的 token
        3. 请求 B 的 request_body 引用了请求 A 的数据

        Returns:
            {
                request_id: {
                    'depends_on': [...],  # 依赖的请求 ID
                    'used_by': [...],     # 被哪些请求依赖
                    'used_by_count': 3    # 被依赖次数
                }
            }
        """
        graph = {}

        # 初始化图
        for req_id in requests:
            graph[req_id] = {"depends_on": [], "used_by": [], "used_by_count": 0}

        # 分析每对请求的依赖关系
        req_ids = list(requests.keys())
        for i, id_a in enumerate(req_ids):
            for id_b in req_ids[i + 1 :]:
                req_a = requests[id_a]
                req_b = requests[id_b]

                # 检测 B 是否依赖 A（B 在 A 之后）
                if self._check_dependency(req_b, req_a):
                    graph[id_b]["depends_on"].append(id_a)
                    graph[id_a]["used_by"].append(id_b)

        # 更新计数
        for req_id in graph:
            graph[req_id]["used_by_count"] = len(graph[req_id]["used_by"])

        return graph

    def _check_dependency(self, req_b: Dict[str, Any], req_a: Dict[str, Any]) -> bool:
        """
        检测 req_b 是否依赖 req_a

        检测点：
        1. URL 中包含 req_a 响应的 ID
        2. Headers 中使用了 req_a 的 token
        3. Request body 引用了 req_a 的数据
        """
        # 提取 req_a 的关键字段
        response_a = req_a.get("response_body", "")
        if not response_a:
            return False

        # 尝试提取 ID/token（JSON 响应）
        try:
            import json

            data_a = json.loads(response_a)
            ids_or_tokens = self._extract_ids(data_a)
        except (json.JSONDecodeError, TypeError):
            ids_or_tokens = []

        # 如果没有提取到 ID，尝试简单的字符串匹配（查找数字 ID）
        if not ids_or_tokens:
            # 简单模式：在 JSON 响应中查找 "id": 数字 的模式
            import re

            id_matches = re.findall(r'"[^"]*id[^"]*"\s*:\s*(\d+)', response_a)
            if id_matches:
                ids_or_tokens = id_matches

        if not ids_or_tokens:
            return False

        # 检测 req_b 是否引用了这些 ID
        url_b = req_b.get("url", "")
        headers_b = str(req_b.get("headers", {}))
        body_b = str(req_b.get("request_body", ""))

        for id_token in ids_or_tokens:
            if id_token in url_b or id_token in headers_b or id_token in body_b:
                return True

        return False

    def _extract_ids(self, data: Any, prefix: str = "") -> List[str]:
        """
        从 JSON 数据中提取可能的 ID/token

        策略：
        1. 字段名包含 id/token/key 的值
        2. UUID 格式的字符串
        3. 长度 > 20 的字符串（可能是 token）
        """
        import uuid as uuid_lib

        results = []

        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{prefix}.{key}" if prefix else key

                # 检查字段名
                if any(keyword in key.lower() for keyword in ["id", "token", "key", "session"]):
                    if isinstance(value, str) and len(value) >= 3:
                        results.append(value)

                # 递归
                results.extend(self._extract_ids(value, current_path))

        elif isinstance(data, list):
            for i, item in enumerate(data):
                results.extend(self._extract_ids(item, f"{prefix}[{i}]"))

        elif isinstance(data, str):
            # UUID 检测
            try:
                uuid_lib.UUID(data)
                results.append(data)
            except (ValueError, AttributeError):
                pass

            # 长字符串检测（可能是 token）
            if len(data) > 20:
                results.append(data)

        return results

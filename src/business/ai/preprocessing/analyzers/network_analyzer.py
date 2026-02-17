"""
网络请求分析器

分析录制的网络请求，判断是否可复现、提取响应结构
"""

import json
import logging
from typing import List, Optional
from urllib.parse import urlparse

from src.recording.recorder import Action, NetworkRequest, NetworkRequestDetail
from src.business.ai.prompts.prompt_data_models import (
    NetworkRequestAnalysis,
    ResponseStructure,
    ResponseStructureType,
)


logger = logging.getLogger(__name__)


class NetworkRequestAnalyzer:
    """
    网络请求分析器

    核心功能：
    1. 判断网络请求是否可复现（不需要认证）
    2. 提取 JSON 响应结构
    3. 关联操作和网络请求
    """

    # 需要认证的 header 关键词
    AUTH_HEADERS = {
        "authorization",
        "cookie",
        "x-csrf-token",
        "x-auth-token",
        "authentication",
    }

    # 无效域名关键词（广告、统计、追踪）
    INVALID_DOMAIN_KEYWORDS = {
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
    }

    def __init__(self):
        """初始化分析器"""
        pass

    def analyze_requests(self, actions: List[Action]) -> List[NetworkRequestAnalysis]:
        """
        分析所有操作中的网络请求

        Args:
            actions: 操作列表

        Returns:
            网络请求分析结果列表
        """
        analyses = []

        for idx, action in enumerate(actions):
            # 获取网络请求（可能是 NetworkRequest 或 NetworkRequestDetail）
            network_requests = action.network_requests

            if not network_requests:
                continue

            # 分析每个网络请求
            for req in network_requests:
                # 转换为 NetworkRequestDetail（如果需要）
                if isinstance(req, NetworkRequest):
                    detail = self._convert_to_detail(req)
                elif isinstance(req, NetworkRequestDetail):
                    detail = req
                elif isinstance(req, dict):
                    # 从字典创建
                    detail = NetworkRequestDetail.from_dict(req)
                else:
                    logger.warning(f"未知的网络请求类型: {type(req)}")
                    continue

                # 分析请求
                analysis = self.analyze_request(detail, action, idx)
                if analysis:
                    analyses.append(analysis)

        logger.info(f"分析了 {len(analyses)} 个网络请求")
        return analyses

    def analyze_request(
        self, request: NetworkRequestDetail, action: Optional[Action] = None, action_index: int = -1
    ) -> Optional[NetworkRequestAnalysis]:
        """
        分析单个网络请求

        Args:
            request: 网络请求详情
            action: 关联的操作
            action_index: 操作索引

        Returns:
            网络请求分析结果
        """
        # 检查是否有效的请求
        if not self._is_valid_request(request):
            return None

        # 检查是否是 JSON 响应
        is_json = self._check_is_json_response(request)

        # 检查是否可直接复现
        is_replayable = self._check_if_replayable(request)

        # 提取响应结构
        response_structure = None
        if is_json and is_replayable:
            response_structure = self._extract_structure(request)

        # 检查认证
        has_auth, auth_type = self._check_auth(request)

        # 获取 Content-Type
        content_type = (
            request.response_headers.get("content-type", "") if request.response_headers else ""
        )

        # 生成 action_id
        action_id = f"action_{action_index}" if action_index >= 0 else "unknown"

        return NetworkRequestAnalysis(
            action_id=action_id,
            url=request.url,
            method=request.method,
            response_status=request.response_status or 0,
            is_json_response=is_json,
            is_replayable=is_replayable,  # ⭐ 关键
            response_structure=response_structure,
            response_body=request.response_body,  # 添加响应体
            has_auth=has_auth,
            auth_type=auth_type,
            content_type=content_type,
        )

    def _is_valid_request(self, request: NetworkRequestDetail) -> bool:
        """
        判断是否是有效的请求

        过滤掉无效的域名、失败的请求等
        """
        # 检查 URL
        if not request.url:
            return False

        # 检查响应状态
        if (
            not request.response_status
            or request.response_status < 200
            or request.response_status >= 300
        ):
            return False

        # 检查是否为无效域名
        parsed_url = urlparse(request.url)
        domain = parsed_url.netloc.lower()

        for keyword in self.INVALID_DOMAIN_KEYWORDS:
            if keyword in domain:
                return False

        return True

    def _check_is_json_response(self, request: NetworkRequestDetail) -> bool:
        """
        检查是否是 JSON 响应
        """
        # 检查 Content-Type
        if request.response_headers:
            content_type = request.response_headers.get("content-type", "").lower()
            if "application/json" in content_type:
                return True

        # 检查 response_body_parsed
        if request.response_body_parsed is not None:
            return True

        # 检查 response_body
        if request.response_body:
            try:
                json.loads(request.response_body)
                return True
            except (json.JSONDecodeError, TypeError):
                pass

        # 检查 is_json_response 字段
        if hasattr(request, "is_json_response"):
            return request.is_json_response

        return False

    def _check_if_replayable(self, request: NetworkRequestDetail) -> bool:
        """
        ⭐ 判断是否可直接复现

        可复现条件：
        1. 状态码 2xx
        2. 不需要认证
        3. 是 GET 请求（或者无复杂的 POST body）
        """
        # 检查响应状态
        if (
            not request.response_status
            or request.response_status < 200
            or request.response_status >= 300
        ):
            return False

        # 检查认证
        has_auth, _ = self._check_auth(request)
        if has_auth:
            return False

        # GET 请求通常可复现
        if request.method == "GET":
            return True

        # POST/PUT 请求：检查是否有简单的 body
        if request.method in ["POST", "PUT", "PATCH"]:
            # 如果 body 为空或很简单，也可复现
            body = request.request_body or ""
            if not body or len(body) < 100:
                return True

        return False

    def _check_auth(self, request: NetworkRequestDetail) -> tuple[bool, Optional[str]]:
        """
        检查是否需要认证

        Returns:
            (是否需要认证, 认证类型)
        """
        if not request.response_headers:
            return False, None

        headers_lower = {k.lower(): v for k, v in request.response_headers.items()}

        # 检查各种认证 header
        for auth_header in self.AUTH_HEADERS:
            if auth_header in headers_lower:
                # 判断认证类型
                value = headers_lower[auth_header]
                if auth_header == "authorization":
                    if "bearer" in value.lower():
                        return True, "bearer"
                    elif "basic" in value.lower():
                        return True, "basic"
                    else:
                        return True, "token"
                elif auth_header == "cookie":
                    return True, "cookie"
                elif "token" in auth_header:
                    return True, "custom_token"
                else:
                    return True, "unknown"

        return False, None

    def _extract_structure(self, request: NetworkRequestDetail) -> Optional[ResponseStructure]:
        """
        ⭐ 提取 JSON 响应结构

        分析响应体的结构，判断是列表、对象还是包含列表的对象
        """
        # 获取解析后的响应体
        body = request.response_body_parsed

        if body is None:
            # 尝试解析 response_body
            if request.response_body:
                try:
                    body = json.loads(request.response_body)
                except (json.JSONDecodeError, TypeError):
                    return None
            else:
                return None

        # 检查是否是列表
        if isinstance(body, list):
            return ResponseStructure(
                type=ResponseStructureType.LIST,
                item_count=len(body),
                sample_item=body[0] if body else None,
            )

        # 检查是否是对象
        if isinstance(body, dict):
            # 检查是否有常见的列表字段
            list_keys = ["items", "results", "data", "list", "entries", "records"]

            for key in list_keys:
                if key in body and isinstance(body[key], list):
                    return ResponseStructure(
                        type=ResponseStructureType.DICT_WITH_LIST,
                        list_key=key,
                        item_count=len(body[key]),
                        sample_item=body[key][0] if body[key] else None,
                    )

            # 普通对象
            return ResponseStructure(
                type=ResponseStructureType.OBJECT,
                keys=list(body.keys()),
            )

        return None

    def _convert_to_detail(self, request: NetworkRequest) -> NetworkRequestDetail:
        """
        将 NetworkRequest 转换为 NetworkRequestDetail

        尝试解析响应体
        """
        detail = NetworkRequestDetail(
            url=request.url,
            method=request.method,
            request_headers=request.request_headers,
            request_body=request.request_body,
            response_status=request.response_status,
            response_headers=request.response_headers,
            response_body=request.response_body,
            timestamp=request.timestamp,
            duration=request.duration,
        )

        # 尝试解析响应体
        if request.response_body:
            try:
                detail.response_body_parsed = json.loads(request.response_body)
                detail.is_json_response = True
            except (json.JSONDecodeError, TypeError):
                detail.is_json_response = False

        return detail

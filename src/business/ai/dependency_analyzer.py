# ⚠️ TODO: 此模块尚未集成到工作流中
# 依赖关系分析器 - 分析网络请求之间的数据依赖关系
# 计划在后续版本中集成到数据预处理流程

"""
依赖关系分析器

分析网络请求之间的数据依赖关系
"""

import json
import logging
from typing import List, Any, Optional
from urllib.parse import urlparse

from src.business.ai.prompts.request_analysis_models import DataDependency
from src.recording.recorder import NetworkRequest

logger = logging.getLogger(__name__)


class DependencyAnalyzer:
    """依赖关系分析器"""

    def __init__(self):
        """初始化分析器"""
        pass

    def find_dependencies(self, requests: List[NetworkRequest]) -> List[List[DataDependency]]:
        """
        查找所有请求的依赖关系

        Args:
            requests: 网络请求列表（按时间排序）

        Returns:
            每个请求的依赖列表
        """
        dependencies = []

        for i, current_req in enumerate(requests):
            req_deps = []

            # 检查这个请求的请求体是否使用了之前请求的响应数据
            if current_req.request_body:
                consumed = self._find_consumed_data(current_req, requests[:i])
                req_deps.extend(consumed)

            dependencies.append(req_deps)

        return dependencies

    def _find_consumed_data(
        self, current_request: NetworkRequest, previous_requests: List[NetworkRequest]
    ) -> List[DataDependency]:
        """
        查找当前请求消耗的数据

        Args:
            current_request: 当前请求
            previous_requests: 之前的所有请求

        Returns:
            数据依赖列表
        """
        dependencies = []

        # 解析当前请求的请求体
        try:
            if isinstance(current_request.request_body, str):
                current_body = json.loads(current_request.request_body)
            elif isinstance(current_request.request_body, dict):
                current_body = current_request.request_body
            else:
                return dependencies
        except (json.JSONDecodeError, TypeError):
            return dependencies

        # 遍历请求体的所有字段
        for field_name, field_value in current_body.items():
            # 跳过 None 值
            if field_value is None:
                continue

            # 在之前所有请求的响应中查找
            for prev_req in previous_requests:
                dep = self._find_value_in_response(field_name, field_value, prev_req)
                if dep:
                    dependencies.append(dep)

        return dependencies

    def _find_value_in_response(
        self, field_name: str, field_value: Any, source_request: NetworkRequest
    ) -> Optional[DataDependency]:
        """
        在响应中查找值

        Args:
            field_name: 字段名
            field_value: 字段值
            source_request: 来源请求

        Returns:
            数据依赖对象，如果找到的话
        """
        if not source_request.response_body:
            return None

        # 解析响应体
        try:
            if isinstance(source_request.response_body, str):
                response_body = json.loads(source_request.response_body)
            elif isinstance(source_request.response_body, dict):
                response_body = source_request.response_body
            else:
                return None
        except (json.JSONDecodeError, TypeError):
            return None

        # 在响应中递归查找值
        path = self._find_path_to_value(response_body, field_value)

        if path:
            # 生成请求 ID（使用 URL）
            request_id = self._generate_request_id(source_request)

            return DataDependency(
                field_name=field_name,
                field_value=field_value,
                source_request_id=request_id,
                source_path=path,
            )

        return None

    def _find_path_to_value(
        self, data: Any, target_value: Any, current_path: str = ""
    ) -> Optional[str]:
        """
        递归查找值在数据中的路径

        Args:
            data: 要搜索的数据
            target_value: 目标值
            current_path: 当前路径

        Returns:
            路径字符串，如果找到的话
        """
        if data == target_value:
            return current_path or "root"

        if isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{current_path}.{key}" if current_path else key
                result = self._find_path_to_value(value, target_value, new_path)
                if result:
                    return result

        elif isinstance(data, list):
            for i, item in enumerate(data):
                new_path = f"{current_path}[{i}]" if current_path else f"[{i}]"
                result = self._find_path_to_value(item, target_value, new_path)
                if result:
                    return result

        return None

    def _generate_request_id(self, request: NetworkRequest) -> str:
        """
        生成请求 ID

        Args:
            request: 网络请求

        Returns:
            请求 ID
        """
        parsed = urlparse(request.url)
        path = parsed.path or parsed.netloc
        return f"{path}@{request.timestamp}"

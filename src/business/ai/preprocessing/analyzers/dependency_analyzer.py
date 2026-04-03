"""
依赖关系分析器

检测网络请求之间的数据依赖关系（ID 引用、token 传递等）。
"""

import json
from typing import Dict, Any, List


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
                    'depended_by': [...],     # 被哪些请求依赖
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

"""
提示词数据模型

定义用于代码生成的数据结构
"""

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum


class ResponseStructureType(Enum):
    """响应结构类型"""

    LIST = "list"  # 纯列表: [...]
    DICT_WITH_LIST = "dict_with_list"  # 包含列表的字典: {items: [...]}
    OBJECT = "object"  # 普通对象: {...}
    UNKNOWN = "unknown"  # 未知类型


class MatchStrategy(Enum):
    """列表匹配策略"""

    API_MATCH = "api_match"  # API 数据匹配
    DOM_MATCH = "dom_match"  # DOM 属性匹配
    FUZZY_MATCH = "fuzzy_match"  # 模糊匹配
    INDEX_MATCH = "index_match"  # 索引匹配


@dataclass
class ResponseStructure:
    """响应结构分析"""

    type: ResponseStructureType
    list_key: Optional[str] = None  # 列表字段名（如果是 dict_with_list）
    item_count: int = 0  # 列表项数
    sample_item: Optional[Dict[str, Any]] = None  # 第一个样本数据
    keys: List[str] = field(default_factory=list)  # 对象的键（如果是 object）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "type": self.type.value,
            "list_key": self.list_key,
            "item_count": self.item_count,
            "sample_item": self.sample_item,
            "keys": self.keys,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResponseStructure":
        """从字典创建"""
        return cls(
            type=ResponseStructureType(data.get("type", "unknown")),
            list_key=data.get("list_key"),
            item_count=data.get("item_count", 0),
            sample_item=data.get("sample_item"),
            keys=data.get("keys", []),
        )


@dataclass
class NetworkRequestAnalysis:
    """
    网络请求分析结果

    用于 LLM 判断是否可以使用 API
    """

    # 基本信息
    action_id: str  # 关联的操作 ID
    url: str  # 请求 URL
    method: str  # HTTP 方法
    response_status: int  # 响应状态码

    # ⭐ 关键字段：可复现性
    is_json_response: bool = False  # 是否是 JSON 响应
    is_replayable: bool = False  # ⭐ 是否可直接复现（不需要认证）

    # 响应结构分析
    response_structure: Optional[ResponseStructure] = None

    # 响应数据
    response_body: Optional[str] = None  # 响应体（用于格式化显示）

    # 元数据
    has_auth: bool = False  # 是否需要认证
    auth_type: Optional[str] = None  # 认证类型（bearer, cookie, etc.）
    content_type: Optional[str] = None  # Content-Type

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "action_id": self.action_id,
            "url": self.url,
            "method": self.method,
            "response_status": self.response_status,
            "is_json_response": self.is_json_response,
            "is_replayable": self.is_replayable,  # ⭐ 关键
            "response_structure": (
                self.response_structure.to_dict() if self.response_structure else None
            ),
            "response_body": self.response_body,
            "has_auth": self.has_auth,
            "auth_type": self.auth_type,
            "content_type": self.content_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NetworkRequestAnalysis":
        """从字典创建"""
        structure_data = data.get("response_structure")
        response_structure = ResponseStructure.from_dict(structure_data) if structure_data else None

        return cls(
            action_id=data["action_id"],
            url=data["url"],
            method=data["method"],
            response_status=data["response_status"],
            is_json_response=data.get("is_json_response", False),
            is_replayable=data.get("is_replayable", False),
            response_structure=response_structure,
            response_body=data.get("response_body"),
            has_auth=data.get("has_auth", False),
            auth_type=data.get("auth_type"),
            content_type=data.get("content_type"),
        )


@dataclass
class ListOperationAnalysis:
    """
    列表操作分析结果

    用于 LLM 判断如何智能选择列表项
    """

    # 基本信息
    action_id: str  # 关联的操作 ID
    is_list_operation: bool = False  # 是否是列表操作

    # 列表结构
    container_selector: Optional[str] = None  # 列表容器选择器
    item_selector: Optional[str] = None  # 列表项选择器
    total_count: int = 0  # 列表总数量
    clicked_index: int = -1  # 点击位置

    # ⭐ 关键字段：数据来源
    associated_api_request: Optional[NetworkRequestAnalysis] = None  # 关联的网络请求

    # 匹配策略
    suggested_strategy: MatchStrategy = MatchStrategy.DOM_MATCH
    reasoning: str = ""  # 策略选择理由

    # 兄弟元素样本（用于 DOM 匹配）
    sample_siblings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "action_id": self.action_id,
            "is_list_operation": self.is_list_operation,
            "container_selector": self.container_selector,
            "item_selector": self.item_selector,
            "total_count": self.total_count,
            "clicked_index": self.clicked_index,
            "associated_api_request": (
                self.associated_api_request.to_dict() if self.associated_api_request else None
            ),
            "suggested_strategy": self.suggested_strategy.value,
            "reasoning": self.reasoning,
            "sample_siblings": self.sample_siblings,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ListOperationAnalysis":
        """从字典创建"""
        api_data = data.get("associated_api_request")
        associated_api = NetworkRequestAnalysis.from_dict(api_data) if api_data else None

        return cls(
            action_id=data["action_id"],
            is_list_operation=data.get("is_list_operation", False),
            container_selector=data.get("container_selector"),
            item_selector=data.get("item_selector"),
            total_count=data.get("total_count", 0),
            clicked_index=data.get("clicked_index", -1),
            associated_api_request=associated_api,
            suggested_strategy=MatchStrategy(data.get("suggested_strategy", "dom_match")),
            reasoning=data.get("reasoning", ""),
            sample_siblings=data.get("sample_siblings", []),
        )


@dataclass
class ParameterDefinition:
    """
    参数定义
    """

    name: str  # 参数名（英文，snake_case）
    type: str  # 参数类型（text, number, url, date等）
    description: str  # 参数说明
    required: bool = True  # 是否必填
    default_value: Any = None  # 默认值
    source_action_index: int = -1  # 来源操作索引

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
            "required": self.required,
            "default_value": self.default_value,
            "source_action_index": self.source_action_index,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParameterDefinition":
        """从字典创建"""
        return cls(
            name=data["name"],
            type=data["type"],
            description=data["description"],
            required=data.get("required", True),
            default_value=data.get("default_value"),
            source_action_index=data.get("source_action_index", -1),
        )

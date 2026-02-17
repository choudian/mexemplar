"""
列表操作分析器

分析列表操作，关联网络请求，生成匹配策略建议
"""

import logging
from typing import List, Dict, Any, Optional

from src.recording.recorder import Action, SiblingsSnapshot, SiblingElement
from src.business.ai.prompts.prompt_data_models import (
    ListOperationAnalysis,
    MatchStrategy,
    NetworkRequestAnalysis,
    ResponseStructureType,
)


logger = logging.getLogger(__name__)


class ListOperationAnalyzer:
    """
    列表操作分析器

    核心功能：
    1. 识别列表操作（通过 siblings_snapshot）
    2. 关联网络请求
    3. 生成匹配策略建议（API 匹配 vs DOM 匹配）
    """

    def __init__(self):
        """初始化分析器"""
        pass

    def analyze_list_operations(
        self, actions: List[Action], network_analysis: List[NetworkRequestAnalysis]
    ) -> List[ListOperationAnalysis]:
        """
        分析所有操作中的列表操作

        Args:
            actions: 操作列表
            network_analysis: 网络请求分析结果

        Returns:
            列表操作分析结果列表
        """
        analyses = []

        for idx, action in enumerate(actions):
            # 获取 siblings_snapshot（可能是字典或对象）
            siblings_snapshot = self._get_siblings_snapshot(action)

            if not siblings_snapshot:
                continue

            # 分析列表操作
            analysis = self.analyze_list_operation(
                action=action,
                action_index=idx,
                siblings_snapshot=siblings_snapshot,
                network_analysis=network_analysis,
            )

            if analysis and analysis.is_list_operation:
                analyses.append(analysis)

        logger.info(f"分析了 {len(analyses)} 个列表操作")
        return analyses

    def analyze_list_operation(
        self,
        action: Action,
        action_index: int,
        siblings_snapshot: SiblingsSnapshot,
        network_analysis: List[NetworkRequestAnalysis],
    ) -> Optional[ListOperationAnalysis]:
        """
        分析单个列表操作

        Args:
            action: 操作对象
            action_index: 操作索引
            siblings_snapshot: 兄弟元素快照
            network_analysis: 网络请求分析结果

        Returns:
            列表操作分析结果
        """
        # 基本检查
        if not siblings_snapshot or siblings_snapshot.total_count == 0:
            return None

        # 生成 action_id
        action_id = f"action_{action_index}"

        # 查找关联的网络请求
        associated_api = self._find_associated_api(action, action_index, network_analysis)

        # 生成策略建议
        strategy, reasoning = self._generate_strategy(siblings_snapshot, associated_api)

        # 提取兄弟元素样本
        sample_siblings = self._extract_sample_siblings(siblings_snapshot)

        return ListOperationAnalysis(
            action_id=action_id,
            is_list_operation=True,
            container_selector=siblings_snapshot.container_selector,
            item_selector=siblings_snapshot.item_selector,
            total_count=siblings_snapshot.total_count,
            clicked_index=siblings_snapshot.clicked_index,
            associated_api_request=associated_api,
            suggested_strategy=strategy,
            reasoning=reasoning,
            sample_siblings=sample_siblings,
        )

    def _get_siblings_snapshot(self, action: Action) -> Optional[SiblingsSnapshot]:
        """
        从操作中获取 siblings_snapshot

        处理不同的数据格式（字典或对象）
        """
        # 方法 1: 从 network_requests_detail 查找
        if hasattr(action, "network_requests_detail") and action.network_requests_detail:
            for req_detail in action.network_requests_detail:
                if hasattr(req_detail, "siblings_snapshot") and req_detail.siblings_snapshot:
                    return req_detail.siblings_snapshot

        # 方法 2: 直接从 action 获取（如果 action 是 EnhancedAction）
        if hasattr(action, "siblings_snapshot") and action.siblings_snapshot:
            # 如果是字典，转换为对象
            if isinstance(action.siblings_snapshot, dict):
                return SiblingsSnapshot.from_dict(action.siblings_snapshot)
            return action.siblings_snapshot

        # 方法 3: 从 parameters 中获取
        if action.parameters and "siblings_snapshot" in action.parameters:
            snapshot_data = action.parameters["siblings_snapshot"]
            if isinstance(snapshot_data, dict):
                return SiblingsSnapshot.from_dict(snapshot_data)

        return None

    def _find_associated_api(
        self, action: Action, action_index: int, network_analysis: List[NetworkRequestAnalysis]
    ) -> Optional[NetworkRequestAnalysis]:
        """
        ⭐ 查找关联的网络请求

        关联逻辑：
        1. 优先查找前一个操作的网络请求
        2. 请求类型应该是 GET
        3. 请求应该是可复现的
        """
        if not network_analysis:
            return None

        # 策略 1: 查找当前操作的网络请求
        current_action_id = f"action_{action_index}"
        for analysis in network_analysis:
            if analysis.action_id == current_action_id:
                # 检查是否可复现
                if analysis.is_replayable:
                    return analysis

        # 策略 2: 查找前一个操作的网络请求
        prev_action_id = f"action_{action_index - 1}"
        for analysis in network_analysis:
            if analysis.action_id == prev_action_id:
                # 检查是否可复现
                if analysis.is_replayable:
                    return analysis

        # 策略 3: 查找最近的可复现 API
        for analysis in reversed(network_analysis):
            if analysis.is_replayable and analysis.method == "GET":
                return analysis

        return None

    def _generate_strategy(
        self, siblings_snapshot: SiblingsSnapshot, associated_api: Optional[NetworkRequestAnalysis]
    ) -> tuple[MatchStrategy, str]:
        """
        ⭐ 生成匹配策略建议

        决策流程：
        1. 如果有可复现的 API 且响应包含列表 → API_MATCH
        2. 如果兄弟元素有稳定的属性（data-id, href） → DOM_MATCH
        3. 如果兄弟元素只有文本 → FUZZY_MATCH
        """
        # 情况 1: 有可复现的 API
        if associated_api and associated_api.is_replayable:
            structure = associated_api.response_structure

            # 检查响应是否包含列表
            if structure and structure.type in [
                "list",
                "dict_with_list",
                ResponseStructureType.LIST,
                ResponseStructureType.DICT_WITH_LIST,
            ]:
                reasoning = (
                    f"有关联的可复现 API ({associated_api.url})，"
                    f"响应包含 {structure.item_count} 个列表项。"
                    f"优先使用 API 数据匹配，根据参数值匹配列表项。"
                )
                return MatchStrategy.API_MATCH, reasoning

        # 情况 2: 检查兄弟元素是否有稳定的属性
        stable_attrs = self._check_stable_attributes(siblings_snapshot)

        if stable_attrs:
            reasoning = (
                f"列表元素具有稳定的属性 ({', '.join(stable_attrs)})，"
                f"可以使用 DOM 属性进行精确匹配。"
            )
            return MatchStrategy.DOM_MATCH, reasoning

        # 情况 3: 只有文本，使用模糊匹配
        reasoning = "列表元素只有文本内容，没有稳定的属性标识。" "使用文本模糊匹配或索引匹配。"
        return MatchStrategy.FUZZY_MATCH, reasoning

    def _check_stable_attributes(self, snapshot: SiblingsSnapshot) -> List[str]:
        """
        检查兄弟元素是否有稳定的属性

        稳定属性：data-id, href, id 等
        """
        if not snapshot.siblings:
            return []

        stable_attrs = []
        attr_names = ["data_id", "href", "id"]

        for attr_name in attr_names:
            # 检查是否所有兄弟元素都有此属性
            has_attr_count = 0
            for sibling in snapshot.siblings:
                value = getattr(sibling, attr_name, None)
                if value:
                    has_attr_count += 1

            # 如果超过 80% 的元素有此属性，认为是稳定的
            if has_attr_count / len(snapshot.siblings) > 0.8:
                stable_attrs.append(attr_name)

        return stable_attrs

    def _extract_sample_siblings(self, snapshot: SiblingsSnapshot) -> List[Dict[str, Any]]:
        """
        提取兄弟元素样本

        只保留前 3 个和后 3 个
        """
        if not snapshot.siblings:
            return []

        siblings = snapshot.siblings

        # 取前 3 个和后 3 个
        sample_siblings = siblings[:3] + siblings[-3:] if len(siblings) > 6 else siblings

        # 转换为字典
        result = []
        for sibling in sample_siblings:
            sibling_dict = {
                "index": sibling.index,
                "tag": sibling.tag,
                "text_summary": sibling.text_summary,
                "href": sibling.href,
            }

            # 添加关键属性
            if hasattr(sibling, "data_id") and sibling.data_id:
                sibling_dict["data_id"] = sibling.data_id

            if sibling.class_list:
                sibling_dict["class"] = " ".join(sibling.class_list)

            result.append(sibling_dict)

        return result

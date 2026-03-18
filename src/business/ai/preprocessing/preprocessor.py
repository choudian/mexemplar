"""
核心预处理器

协调压缩引擎和各个分析器，提供统一的数据预处理接口。
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import logging
import hashlib
import threading
from queue import Queue

from src.recording.recorder import Action
from src.business.ai.preprocessing.models import (
    CompressionLevel,
    ProcessedAction,
    PreprocessingResult,
)
from src.business.ai.preprocessing.pipeline import (
    PreprocessingPipeline,
    PreprocessingPipelineContext,
)
from src.business.ai.preprocessing.analyzers import (
    NetworkRequestAnalyzer,
    RequestIntelligenceAnalyzer,
)
from src.business.ai.preprocessing.analyzers.intelligence_analyzer import (
    CompressionModelError,
    TokenLimitExceededError,
    RateLimitError,
)

logger = logging.getLogger(__name__)


class DataPreprocessor:
    """
    数据预处理器 - 统一版本

    在原有压缩功能基础上，集成了：
    1. 网络请求分析（判断可复现性、提取响应结构）
    2. 列表操作分析（识别列表、关联 API、生成策略建议）
    3. 智能请求过滤（规则引擎 + 数据压缩模型）
    """

    def __init__(self, compression_level: CompressionLevel = CompressionLevel.MODERATE):
        """
        初始化预处理器

        Args:
            compression_level: 默认压缩级别
        """
        # 默认压缩级别
        self.compression_level = compression_level

        # 初始化分析器
        self.network_analyzer = NetworkRequestAnalyzer()
        self.request_intelligence_analyzer = RequestIntelligenceAnalyzer()

        # 操作分类
        self.action_categories = {
            "navigation": ["navigate", "window_switch"],
            "interaction": ["click", "double_click", "right_click"],
            "input": ["keyboard_input", "text_input"],
            "system": ["scroll", "wait", "screenshot"],
        }

        # 异步 DuckDB 更新队列和线程
        self._duckdb_update_queue: Queue = Queue()
        self._duckdb_update_thread: Optional[threading.Thread] = None
        self._start_duckdb_update_thread()

    def preprocess(
        self,
        actions: List[Action],
        compression_level: Optional[CompressionLevel] = None,
        enable_analysis: bool = True,
    ) -> PreprocessingResult:
        """
        预处理录制数据（压缩 + 分析）

        Args:
            actions: 操作列表
            compression_level: 压缩级别（覆盖默认值）
            enable_analysis: 是否启用分析（默认 True）

        Returns:
            PreprocessingResult: 预处理结果
        """
        level = compression_level or self.compression_level

        logger.info("=" * 80)
        logger.info(f"开始数据预处理 (压缩级别: {level.value})")
        logger.info(f"操作数量: {len(actions)}")
        logger.info("=" * 80)

        if not actions:
            logger.warning("没有操作需要预处理")
            return PreprocessingResult(
                actions=[],
                recording_mode="unknown",
                key_actions=[],
                screenshots=[],
                metadata={},
            )

        # 获取 recording_id
        recording_id = (
            actions[0].parameters.get("recording_id", "unknown") if actions else "unknown"
        )

        # 使用 Pipeline 处理
        pipeline = PreprocessingPipeline(
            preprocessor=self,
            compression_level=level,
            enable_analysis=enable_analysis,
            recording_id=recording_id,
        )

        context = pipeline.process(actions)

        # 日志输出
        logger.info("=" * 80)
        logger.info(f"[OK] 预处理完成")
        logger.info(f"  压缩级别: {level.value}")
        logger.info(f"  操作数: {len(actions)} -> {len(context.compressed_actions)}")
        logger.info(f"  关键操作: {len(context.key_actions)}")
        logger.info(f"  截图数: {len(context.screenshots)}")
        if enable_analysis and context.metadata.get("analysis_stats"):
            logger.info(
                f"  - 智能过滤: {context.metadata['analysis_stats']['intelligent_filter']['filter_ratio']} 请求被过滤"
            )
        logger.info("=" * 80)

        # 构建结果
        result = PreprocessingResult(
            actions=context.processed_actions,
            recording_mode=self._detect_recording_mode(actions),
            key_actions=context.key_actions,
            screenshots=context.screenshots,
            metadata=context.metadata_with_stats,
            # network_analysis=context.network_analysis,  # 已移至 Agent
            # list_analysis=context.list_analysis,       # 已移至 Agent
        )

        return result

    def _apply_compression(
        self, actions: List[Action], level: CompressionLevel
    ) -> List[Action]:
        """应用压缩逻辑"""
        if level == CompressionLevel.NONE:
            return actions

        original_count = len(actions)

        # 1. 合并连续的输入操作
        actions = self._merge_consecutive_inputs(actions, level)
        logger.debug(f"  合并输入操作: {original_count} -> {len(actions)}")

        # 2. 过滤重复操作
        actions = self._filter_duplicate_actions(actions, level)
        logger.debug(f"  过滤重复操作: -> {len(actions)}")

        # 3. 清理 DOM 属性
        actions = self._clean_dom_attributes(actions, level)
        logger.debug(f"  清理DOM属性完成")

        return actions

    def _filter_requests_by_intelligence(
        self, actions: List[Action], intelligent_analysis: List[Any]
    ) -> List[Action]:
        """根据智能分析结果过滤网络请求"""
        # 构建有意义请求的 ID 集合
        meaningful_request_ids = set()
        for analysis in intelligent_analysis:
            if analysis.is_meaningful:
                meaningful_request_ids.add(analysis.request_id)

        # 过滤每个 action 的 network_requests
        filtered_count = 0
        total_count = 0

        for action in actions:
            if action.network_requests:
                total_count += len(action.network_requests)
                filtered_requests = []
                for idx, req in enumerate(action.network_requests):
                    req_id = self._generate_request_id(req, action.timestamp, idx)
                    if req_id in meaningful_request_ids:
                        filtered_requests.append(req)
                    else:
                        filtered_count += 1

                action.network_requests = filtered_requests if filtered_requests else None

        logger.info(f"  过滤请求: {filtered_count}/{total_count} 个请求被过滤")
        logger.info(f"  保留请求: {total_count - filtered_count} 个有意义的请求")

        return actions

    def _should_use_compression_level(self, compression_level: CompressionLevel) -> bool:
        """根据压缩级别决定是否使用数据压缩模型"""
        if compression_level == CompressionLevel.NONE:
            return False
        elif compression_level == CompressionLevel.CONSERVATIVE:
            return False
        elif compression_level == CompressionLevel.MODERATE:
            return True
        elif compression_level == CompressionLevel.AGGRESSIVE:
            return True
        else:
            return False

    def _generate_request_id(self, request: Any, action_timestamp: float, idx: int) -> str:
        """生成请求 ID"""
        if hasattr(request, "request_id") and request.request_id:
            return request.request_id

        if isinstance(request, dict):
            if request.get("request_id"):
                return request["request_id"]

        return f"{action_timestamp}_{idx}"

    def _detect_recording_mode(self, actions: List[Action]) -> str:
        """检测录制模式"""
        if actions and actions[0].recording_mode:
            return actions[0].recording_mode

        browser_indicators = sum(1 for action in actions if action.url or action.dom_element)
        desktop_indicators = sum(1 for action in actions if action.app_name or action.process_name)

        if browser_indicators > desktop_indicators:
            return "browser"
        elif desktop_indicators > browser_indicators:
            return "desktop"
        else:
            return "unknown"

    def _process_action(self, action: Action, index: int) -> ProcessedAction:
        """处理单个操作"""
        category = self._categorize_action(action)
        is_key = self._is_key_action(action)
        context = self._extract_context(action)

        return ProcessedAction(
            original_action=action,
            action_index=index,
            is_key_action=is_key,
            action_category=category,
            context=context,
        )

    def _categorize_action(self, action: Action) -> Optional[str]:
        """对操作进行分类"""
        action_type = action.action_type.lower()

        for category, types in self.action_categories.items():
            if any(t in action_type for t in types):
                return category

        if action.url:
            return "navigation"
        if action.dom_element:
            return "interaction"
        if action.parameters.get("text") or action.parameters.get("key"):
            return "input"

        return "unknown"

    def _is_key_action(self, action: Action) -> bool:
        """判断是否为关键操作"""
        non_key_types = ["screenshot", "wait", "window_switch"]

        if action.action_type.lower() in non_key_types:
            return False

        if action.parameters.get("auto_generated"):
            return False

        return True

    def _extract_context(self, action: Action) -> Dict[str, Any]:
        """提取操作的上下文信息"""
        context = {
            "has_screenshot": bool(action.screenshot_before or action.screenshot_after),
            "has_dom_element": bool(action.dom_element),
            "has_network_request": bool(action.network_requests),
            "has_url": bool(action.url),
            "application": action.app_name or action.process_name,
            "window_title": action.window_title,
        }

        if action.recording_mode == "browser":
            if action.dom_element:
                context["element_tag"] = action.dom_element.get("tag_name")
                context["element_text"] = action.dom_element.get("text")
                context["element_attributes"] = action.dom_element.get("attributes", {})

            if action.network_requests:
                context["network_count"] = len(action.network_requests)
                api_requests = [
                    req
                    for req in action.network_requests
                    if req.response_status and 200 <= req.response_status < 300
                ]
                if api_requests:
                    context["has_api_call"] = True
                    domains = []
                    for req in api_requests:
                        if req.url:
                            try:
                                from urllib.parse import urlparse

                                parsed = urlparse(req.url)
                                if parsed.netloc:
                                    domains.append(parsed.netloc)
                            except Exception:
                                pass
                    context["api_domains"] = list(set(domains)) if domains else []

        return context

    def _extract_key_actions(self, processed_actions: List[ProcessedAction]) -> List[ProcessedAction]:
        """提取关键操作"""
        return [action for action in processed_actions if action.is_key_action]

    def _collect_screenshots(self, actions: List[Action]) -> List[str]:
        """收集所有截图路径"""
        screenshots = []

        for action in actions:
            if action.screenshot_before:
                screenshots.append(action.screenshot_before)
            if action.screenshot_after:
                screenshots.append(action.screenshot_after)

        # 去重并保持顺序
        seen = set()
        unique_screenshots = []
        for path in screenshots:
            if path and path not in seen:
                seen.add(path)
                unique_screenshots.append(path)

        return unique_screenshots

    def _generate_metadata(
        self, actions: List[Action], processed_actions: List[ProcessedAction]
    ) -> Dict[str, Any]:
        """生成元数据"""
        action_types = {}
        applications = set()
        urls = set()

        for action in actions:
            action_type = action.action_type
            action_types[action_type] = action_types.get(action_type, 0) + 1

            if action.app_name:
                applications.add(action.app_name)
            if action.process_name:
                applications.add(action.process_name)

            if action.url:
                urls.add(action.url)

        action_sequence = [action.action_category for action in processed_actions]

        metadata = {
            "total_actions": len(actions),
            "key_actions_count": len([a for a in processed_actions if a.is_key_action]),
            "action_types": action_types,
            "applications": list(applications),
            "urls": list(urls),
            "action_sequence": action_sequence,
            "has_network_requests": any(bool(action.network_requests) for action in actions),
            "has_screenshots": any(
                bool(action.screenshot_before or action.screenshot_after) for action in actions
            ),
        }

        return metadata

    # ==================== 压缩方法 ====================

    def _merge_consecutive_inputs(
        self, actions: List[Action], level: CompressionLevel
    ) -> List[Action]:
        """合并连续的输入操作"""
        if level == CompressionLevel.NONE:
            return actions

        if not actions:
            return actions

        time_window = {
            CompressionLevel.CONSERVATIVE: 1.0,
            CompressionLevel.MODERATE: 3.0,
            CompressionLevel.AGGRESSIVE: 5.0,
        }.get(level, 3.0)

        check_interruption = level == CompressionLevel.CONSERVATIVE

        merged = []
        i = 0
        input_types = {
            "fill",
            "input",
            "keydown",
            "keypress",
            "keyup",
            "text_input",
            "keyboard_input",
        }

        while i < len(actions):
            action = actions[i]

            if (
                action.action_type.lower() in input_types
                and action.dom_element
                and action.parameters.get("value")
            ):
                element_id = self._get_element_id(action.dom_element)

                last_action = action
                last_value = action.parameters.get("value") or ""
                j = i + 1
                has_interruption = False

                while j < len(actions):
                    next_action = actions[j]

                    if check_interruption:
                        if next_action.action_type.lower() not in input_types:
                            has_interruption = True
                            break

                    time_diff = next_action.timestamp - action.timestamp
                    if hasattr(time_diff, "total_seconds"):
                        time_diff_seconds = time_diff.total_seconds()
                    else:
                        time_diff_seconds = time_diff

                    if (
                        next_action.action_type.lower() in input_types
                        and next_action.dom_element
                        and self._get_element_id(next_action.dom_element) == element_id
                        and time_diff_seconds < time_window
                    ):
                        last_action = next_action
                        last_value = next_action.parameters.get("value") or ""
                        j += 1
                    else:
                        break

                if j > i + 1 and not has_interruption:
                    merged_action = Action(
                        action_type="fill",
                        recording_mode=action.recording_mode,
                        dom_element=action.dom_element,
                        parameters={"value": last_value},
                        url=action.url,
                        app_name=action.app_name,
                        process_name=action.process_name,
                        window_title=action.window_title,
                        timestamp=action.timestamp,
                        screenshot_before=action.screenshot_before,
                        screenshot_after=last_action.screenshot_after,
                    )
                    merged.append(merged_action)
                    logger.debug(f"[{level.value}] 合并了 {j-i} 个连续输入操作")
                    i = j
                else:
                    merged.append(action)
                    i += 1
            else:
                merged.append(action)
                i += 1

        return merged

    def _filter_duplicate_actions(
        self, actions: List[Action], level: CompressionLevel
    ) -> List[Action]:
        """过滤重复的操作"""
        if not actions or level == CompressionLevel.NONE:
            return actions

        if level == CompressionLevel.CONSERVATIVE:
            repeat_threshold = 3
            time_window = 0.5
        elif level == CompressionLevel.MODERATE:
            repeat_threshold = 2
            time_window = 1.0
        else:
            repeat_threshold = 2
            time_window = 2.0

        filtered = []
        element_history = {}

        for action in actions:
            if action.action_type.lower() in {"click", "dblclick"} and action.dom_element:
                element_id = self._get_element_id(action.dom_element)
                timestamp = action.timestamp

                if element_id not in element_history:
                    element_history[element_id] = []

                def time_diff_seconds(t1, t2):
                    diff = t1 - t2
                    if hasattr(diff, "total_seconds"):
                        return diff.total_seconds()
                    return diff

                element_history[element_id] = [
                    (t, a)
                    for t, a in element_history[element_id]
                    if time_diff_seconds(timestamp, t) < time_window
                ]

                recent_count = len(element_history[element_id])

                if recent_count >= repeat_threshold:
                    logger.debug(
                        f"[{level.value}] 过滤重复操作: {element_id} "
                        f"(时间窗口: {time_window}s, 重复次数: {recent_count})"
                    )
                    element_history[element_id].append((timestamp, action))
                    continue

                filtered.append(action)
                element_history[element_id].append((timestamp, action))
            else:
                filtered.append(action)

        return filtered

    def _clean_dom_attributes(self, actions: List[Action], level: CompressionLevel) -> List[Action]:
        """清理冗余的 DOM 属性"""
        if level == CompressionLevel.NONE:
            return actions

        if level == CompressionLevel.CONSERVATIVE:
            important_attributes = {
                "id",
                "name",
                "class",
                "type",
                "href",
                "src",
                "data-testid",
                "data-cy",
                "role",
                "aria-label",
                "placeholder",
                "value",
                "title",
                "alt",
                "onclick",
                "onchange",
                "style",
                "disabled",
                "readonly",
                "required",
            }
            text_max_length = 100
            remove_bounding_box = False
        elif level == CompressionLevel.MODERATE:
            important_attributes = {
                "id",
                "name",
                "class",
                "type",
                "href",
                "src",
                "data-testid",
                "data-cy",
                "role",
                "aria-label",
                "placeholder",
                "value",
                "title",
                "alt",
            }
            text_max_length = 100
            remove_bounding_box = False
        else:
            important_attributes = {
                "id",
                "name",
                "class",
                "type",
                "data-testid",
                "data-cy",
                "role",
                "placeholder",
                "value",
            }
            text_max_length = 50
            remove_bounding_box = True

        cleaned_count = 0

        for action in actions:
            if action.dom_element and isinstance(action.dom_element, dict):
                if "attributes" in action.dom_element:
                    attrs = action.dom_element["attributes"]
                    if isinstance(attrs, dict):
                        original_count = len(attrs)
                        cleaned_attrs = {
                            k: v
                            for k, v in attrs.items()
                            if k.lower() in important_attributes or k.startswith("data-")
                        }
                        action.dom_element["attributes"] = cleaned_attrs
                        if len(cleaned_attrs) < original_count:
                            cleaned_count += 1

                if "text" in action.dom_element and action.dom_element["text"]:
                    text = action.dom_element["text"]
                    if len(text) > text_max_length:
                        action.dom_element["text"] = text[:text_max_length] + "..."
                        cleaned_count += 1

                if remove_bounding_box and "bounding_box" in action.dom_element:
                    action.dom_element.pop("bounding_box", None)
                    cleaned_count += 1

        logger.debug(f"[{level.value}] DOM属性清理: 清理了 {cleaned_count} 个操作")

        return actions

    def _optimize_screenshots(
        self, actions: List[Action], key_actions: List, level: CompressionLevel
    ) -> List[str]:
        """智能筛选截图"""
        if not actions:
            return []

        all_screenshots = []
        for action in actions:
            if action.screenshot_before:
                all_screenshots.append(("before", action, action.screenshot_before))
            if action.screenshot_after:
                all_screenshots.append(("after", action, action.screenshot_after))

        if not all_screenshots:
            return []

        if level == CompressionLevel.NONE or level == CompressionLevel.CONSERVATIVE:
            screenshot_interval = 1
        elif level == CompressionLevel.MODERATE:
            screenshot_interval = 5
        else:
            screenshot_interval = 3

        optimized = []

        # 保留导航后的截图
        for position, action, path in all_screenshots:
            if action.action_type.lower() in {"navigate", "page_load"}:
                optimized.append(path)

        # 保留关键操作的截图
        action_to_index = {id(action): idx for idx, action in enumerate(actions)}
        key_action_indices = {
            action_to_index.get(id(kaction.original_action), -1) for kaction in key_actions
        }
        key_action_count = 0

        for position, action, path in all_screenshots:
            action_idx = action_to_index.get(id(action), -1)
            if action_idx in key_action_indices:
                key_action_count += 1
                if key_action_count % screenshot_interval == 0:
                    optimized.append(path)

        # 去重
        seen = set()
        unique_screenshots = []
        for path in optimized:
            if path and path not in seen:
                seen.add(path)
                unique_screenshots.append(path)

        logger.debug(
            f"[{level.value}] 截图优化: 原始 {len(all_screenshots)} 张 -> "
            f"优化后 {len(unique_screenshots)} 张 (间隔: {screenshot_interval})"
        )

        return unique_screenshots

    def _get_element_id(self, dom_element: Dict[str, Any]) -> str:
        """获取元素的唯一标识符"""
        if not dom_element:
            return ""

        if dom_element.get("id"):
            return f"#{dom_element['id']}"

        if dom_element.get("xpath"):
            return dom_element["xpath"]

        if dom_element.get("css_selector"):
            return dom_element["css_selector"]

        element_str = f"{dom_element.get('tag_name', '')}_{dom_element.get('text', '')}"
        return hashlib.md5(element_str.encode()).hexdigest()[:8]

    # ==================== 异步 DuckDB 更新方法 ====================

    def _start_duckdb_update_thread(self) -> None:
        """启动 DuckDB 异步更新线程"""

        def update_worker():
            """DuckDB 更新工作线程"""
            logger.info("[DuckDB更新] 后台线程已启动")

            while True:
                try:
                    task = self._duckdb_update_queue.get()

                    if task is None:
                        logger.info("[DuckDB更新] 收到停止信号，退出线程")
                        break

                    recording_id, analyses = task
                    self._update_duckdb_with_recommendation_flags(recording_id, analyses)

                    self._duckdb_update_queue.task_done()

                except Exception as e:
                    logger.error(f"[DuckDB更新] 后台更新失败: {e}", exc_info=True)

        self._duckdb_update_thread = threading.Thread(
            target=update_worker, daemon=True, name="duckdb-updater"
        )
        self._duckdb_update_thread.start()

    def _update_duckdb_with_recommendation_flags(
        self, recording_id: str, analyses: List[Any]
    ) -> None:
        """更新 DuckDB 中的推荐内容标记"""
        from src.data.duckdb_manager import DuckDBManager

        try:
            duckdb = DuckDBManager()
            conn = duckdb.connect()

            updated_count = 0

            for analysis in analyses:
                if not hasattr(analysis, "is_recommendation") or not hasattr(
                    analysis, "importance_level"
                ):
                    continue

                req_id = analysis.request_id
                if not req_id:
                    continue

                try:
                    conn.execute(
                        """
                        UPDATE network_requests
                        SET
                            is_recommendation = ?,
                            importance_level = ?
                        WHERE request_id = ?
                    """,
                        [analysis.is_recommendation, analysis.importance_level, req_id],
                    )
                    updated_count += 1
                except Exception as e:
                    logger.debug(f"[DuckDB更新] 更新失败 {req_id}: {e}")

            logger.info(f"[DuckDB更新] 已更新 {updated_count}/{len(analyses)} 条记录的推荐标记")

        except Exception as e:
            logger.error(f"[DuckDB更新] 更新过程失败: {e}", exc_info=True)

    def close(self):
        """关闭预处理器，清理资源"""
        if self._duckdb_update_thread and self._duckdb_update_thread.is_alive():
            logger.info("[DuckDB更新] 发送停止信号...")
            self._duckdb_update_queue.put(None)

            self._duckdb_update_thread.join(timeout=5)

            if self._duckdb_update_thread.is_alive():
                logger.warning("[DuckDB更新] 线程未能在超时时间内结束")
            else:
                logger.info("[DuckDB更新] 线程已正常停止")

    def filter_for_main_llm(self, analyses: List[Any]) -> Dict[str, Any]:
        """过滤掉不应传给主 LLM 的请求"""
        filtered = []
        recommendation_count = 0
        meaningless_count = 0

        for analysis in analyses:
            if not analysis.is_meaningful:
                meaningless_count += 1
                continue

            if analysis.is_recommendation:
                logger.debug(
                    f"[过滤] 推荐内容不传给主LLM: {analysis.request_id}, "
                    f"原因: {analysis.reason}"
                )
                recommendation_count += 1
                continue

            filtered.append(analysis)

        logger.info(
            f"[数据压缩] 总计 {len(analyses)} 个请求，"
            f"过滤推荐内容 {recommendation_count} 个，"
            f"过滤无意义请求 {meaningless_count} 个，"
            f"传给主LLM {len(filtered)} 个"
        )

        return {
            "filtered_analyses": filtered,
            "stats": {
                "total": len(analyses),
                "recommendation_filtered": recommendation_count,
                "meaningless_filtered": meaningless_count,
                "kept": len(filtered),
            },
        }

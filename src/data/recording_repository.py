"""
录制数据仓库模块

负责录制数据的持久化存储和查询
"""

import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from .duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class RecordingRepository:
    """录制数据仓库"""

    # 标记是否已执行自动恢复（避免重复）
    _auto_recover_done = False

    def __init__(self, db_manager: Optional[DuckDBManager] = None):
        """
        初始化录制数据仓库

        Args:
            db_manager: DuckDB 管理器，如果为None则使用全局单例
        """
        if db_manager is None:
            db_manager = DuckDBManager()
            # 仅首次初始化
            if db_manager.conn is None:
                db_manager.initialize()

        self.db = db_manager

        # ⭐ 首次初始化时，自动恢复未处理的队列文件
        if not RecordingRepository._auto_recover_done:
            RecordingRepository._auto_recover_done = True
            try:
                self._auto_recover_from_queues()
            except Exception as e:
                logger.warning(f"自动恢复失败: {e}")

    def _auto_recover_from_queues(self):
        """
        自动从队列文件恢复未保存的录制

        恢复优先级：
        1. DuckDB WAL 机制（已在 connect() 中自动处理）
        2. 如果 WAL 损坏或录制不存在，从 queues 恢复
        """
        try:
            from .recording_recovery import RecordingRecovery

            # 检查是否需要恢复
            needs_recovery = self.db.needs_queue_recovery()

            if needs_recovery:
                logger.info("🔧 检测到 WAL 损坏，从 queues 恢复数据...")
            else:
                # 即使 WAL 正常，也要检查是否有未处理的队列文件
                #（正常关闭但数据未成功保存到 DuckDB 的情况）
                logger.debug("WAL 正常，检查是否有未处理的队列文件...")

            recovery = RecordingRecovery(db_manager=self.db)
            recovered = recovery.auto_recover_on_startup()

            if recovered:
                logger.info("✅ 已从队列文件自动恢复录制数据")

            # 清除恢复标志
            self.db.clear_queue_recovery_flag()

        except ImportError:
            logger.debug("恢复模块不可用，跳过自动恢复")
        except Exception as e:
            logger.warning(f"自动恢复检查失败: {e}")

    def save_recording_session(self, session: Dict[str, Any]) -> str:
        """
        保存录制会话

        Args:
            session: 录制会话字典

        Returns:
            录制会话 ID
        """
        recording_id = session.get("recording_id")
        if not recording_id:
            raise ValueError("recording_id 不能为空")

        # 转换时间戳
        start_time = (
            datetime.fromtimestamp(session["start_time"]) if session.get("start_time") else None
        )
        end_time = datetime.fromtimestamp(session["end_time"]) if session.get("end_time") else None

        # 序列化 metadata
        metadata = json.dumps(session.get("metadata", {}), ensure_ascii=False)

        self.db.insert(
            "recording_sessions",
            {
                "recording_id": recording_id,
                "status": session.get("status", "idle"),
                "recording_mode": session.get("recording_mode", "desktop"),
                "browser_type": session.get("browser_type"),
                "start_time": start_time,
                "end_time": end_time,
                "metadata": metadata,
            },
            auto_commit=True,  # ⭐ 立即落盘，防止断电丢失
        )

        logger.info(f"录制会话已保存: {recording_id}")
        return recording_id

    def save_actions(self, recording_id: str, actions: List[Dict[str, Any]]) -> List[int]:
        """
        批量保存操作序列

        Args:
            recording_id: 录制会话 ID
            actions: 操作列表

        Returns:
            插入的操作 ID 列表
        """
        if not actions:
            return []

        action_ids = []
        batch_size = 100  # 批量插入大小

        for i in range(0, len(actions), batch_size):
            batch = actions[i : i + batch_size]
            batch_data = []

            for seq_num, action in enumerate(batch, start=i + 1):
                # 转换时间戳
                timestamp = datetime.fromtimestamp(action.get("timestamp", 0))

                # 序列化 JSON 字段
                parameters = json.dumps(action.get("parameters", {}), ensure_ascii=False)
                dom_element = (
                    json.dumps(action.get("dom_element"), ensure_ascii=False)
                    if action.get("dom_element")
                    else None
                )
                dom_tree_snapshot = (
                    json.dumps(action.get("dom_tree_snapshot"), ensure_ascii=False)
                    if action.get("dom_tree_snapshot")
                    else None
                )
                visual_features = (
                    json.dumps(action.get("visual_features"), ensure_ascii=False)
                    if action.get("visual_features")
                    else None
                )

                batch_data.append(
                    {
                        "recording_id": recording_id,
                        "sequence_number": seq_num,
                        "action_type": action.get("action_type"),
                        "recording_mode": action.get("recording_mode", "desktop"),
                        "app_name": action.get("app_name"),
                        "process_name": action.get("process_name"),
                        "window_title": action.get("window_title"),
                        "parameters": parameters,
                        "url": action.get("url"),
                        "dom_element": dom_element,
                        "dom_tree_snapshot": dom_tree_snapshot,
                        "visual_features": visual_features,
                        "screenshot_before": action.get("screenshot_before"),
                        "screenshot_after": action.get("screenshot_after"),
                        "timestamp": timestamp,
                    }
                )

            # 批量插入（最后一个批次自动提交）
            is_last_batch = (i + batch_size) >= len(actions)
            action_ids.extend(self.db.insert_many("actions", batch_data, auto_commit=is_last_batch))

        logger.info(f"已保存 {len(action_ids)} 条操作记录")
        return action_ids

    def save_network_requests(
        self,
        action_id: Optional[int],
        network_requests: List[Dict[str, Any]],
        recording_id: Optional[str] = None,
    ) -> List[int]:
        """
        保存网络请求

        Args:
            action_id: 关联的操作 ID（可以是 None，表示独立的网络请求）
            network_requests: 网络请求列表
            recording_id: 录制会话 ID（用于直接关联，提高查询性能）

        Returns:
            插入的请求 ID 列表
        """
        if not network_requests:
            logger.debug(f"save_network_requests: 网络请求列表为空 (action_id={action_id}, recording_id={recording_id})")
            return []

        logger.debug(f"save_network_requests: 准备保存 {len(network_requests)} 条网络请求 (action_id={action_id}, recording_id={recording_id})")

        request_ids = []
        for request in network_requests:
            try:
                # 转换时间戳
                timestamp = datetime.fromtimestamp(request.get("timestamp", 0))

                # 序列化 JSON 字段
                request_headers = json.dumps(request.get("request_headers", {}), ensure_ascii=False)
                response_headers = json.dumps(request.get("response_headers", {}), ensure_ascii=False)

                request_id = self.db.insert(
                    "network_requests",
                    {
                        "action_id": action_id,
                        "recording_id": recording_id,
                        "url": request.get("url"),
                        "method": request.get("method"),
                        "request_type": request.get("request_type"),
                        "request_headers": request_headers,
                        "request_body": request.get("request_body"),
                        "response_status": request.get("response_status"),
                        "response_headers": response_headers,
                        "response_body": request.get("response_body"),
                        "duration": request.get("duration"),
                        "timestamp": timestamp,
                        "filtered": False,  # 默认未过滤
                        "filter_reason": None,
                        "filtered_at": None,
                    },
                )
                request_ids.append(request_id)
                logger.debug(f"  保存网络请求成功: request_id={request_id}, url={request.get('url')}")
            except Exception as e:
                logger.error(f"保存网络请求失败: {e}, url={request.get('url')}", exc_info=True)
                # 继续保存其他请求，不中断整个流程

        logger.info(f"save_network_requests: 成功保存 {len(request_ids)}/{len(network_requests)} 条网络请求")
        return request_ids

    def save_sibling_snapshot(
        self,
        action_id: int,
        siblings_snapshot: Dict[str, Any],
        recording_id: Optional[str] = None,
    ) -> int:
        """
        保存兄弟元素快照

        Args:
            action_id: 关联的操作 ID
            siblings_snapshot: 兄弟元素快照数据
            recording_id: 录制会话 ID（用于直接关联，提高查询性能）

        Returns:
            插入的快照 ID
        """
        # 序列化 JSON 字段
        siblings = json.dumps(siblings_snapshot.get("siblings", []), ensure_ascii=False)

        timestamp = datetime.fromtimestamp(
            siblings_snapshot.get("timestamp", datetime.now().timestamp())
        )

        snapshot_id = self.db.insert(
            "sibling_snapshots",
            {
                "action_id": action_id,
                "recording_id": recording_id,  # ⭐ 新增：直接关联录制会话
                "container_selector": siblings_snapshot.get("container_selector"),
                "item_selector": siblings_snapshot.get("item_selector"),
                "list_type": siblings_snapshot.get("list_type"),
                "siblings": siblings,
                "structure_similarity": siblings_snapshot.get("structure_similarity", 0.0),
                "is_homogeneous": siblings_snapshot.get("is_homogeneous", False),
                "clicked_index": siblings_snapshot.get("clicked_index", -1),
                "total_count": siblings_snapshot.get("total_count", 0),
                "timestamp": timestamp,
            },
        )

        return snapshot_id

    def save_list_context(
        self,
        action_id: int,
        list_context: Dict[str, Any],
        recording_id: Optional[str] = None,
    ) -> int:
        """
        保存列表上下文

        Args:
            action_id: 关联的操作 ID
            list_context: 列表上下文数据
            recording_id: 录制会话 ID（用于直接关联，提高查询性能）

        Returns:
            插入的上下文 ID
        """
        # 序列化 JSON 字段
        parent_element = (
            json.dumps(list_context.get("parent_element"), ensure_ascii=False)
            if list_context.get("parent_element")
            else None
        )
        selection_rules = (
            json.dumps(list_context.get("selection_rules"), ensure_ascii=False)
            if list_context.get("selection_rules")
            else None
        )
        api_response_mapping = (
            json.dumps(list_context.get("api_response_mapping"), ensure_ascii=False)
            if list_context.get("api_response_mapping")
            else None
        )

        timestamp = datetime.fromtimestamp(
            list_context.get("timestamp", datetime.now().timestamp())
        )

        context_id = self.db.insert(
            "list_contexts",
            {
                "action_id": action_id,
                "recording_id": recording_id,  # ⭐ 新增：直接关联录制会话
                "list_pattern": list_context.get("list_pattern"),
                "parent_element": parent_element,
                "selection_rules": selection_rules,
                "api_url_pattern": list_context.get("api_url_pattern"),
                "api_response_mapping": api_response_mapping,
                "timestamp": timestamp,
            },
        )

        return context_id

    def get_recording_session(self, recording_id: str) -> Optional[Dict[str, Any]]:
        """
        获取录制会话

        Args:
            recording_id: 录制会话 ID

        Returns:
            录制会话字典或 None
        """
        result = self.db.fetchone(
            "SELECT * FROM recording_sessions WHERE recording_id = ?", (recording_id,)
        )

        if not result:
            return None

        columns = [
            "recording_id",
            "status",
            "recording_mode",
            "browser_type",
            "start_time",
            "end_time",
            "metadata",
            "created_at",
        ]

        session = dict(zip(columns, result))
        # 反序列化 metadata
        if session.get("metadata"):
            session["metadata"] = json.loads(session["metadata"])

        return session

    def get_actions(self, recording_id: str) -> List[Dict[str, Any]]:
        """
        获取录制会话的所有操作

        Args:
            recording_id: 录制会话 ID

        Returns:
            操作列表
        """
        results = self.db.fetchall(
            "SELECT * FROM actions WHERE recording_id = ? ORDER BY sequence_number", (recording_id,)
        )

        columns = [
            "action_id",
            "recording_id",
            "sequence_number",
            "action_type",
            "recording_mode",
            "app_name",
            "process_name",
            "window_title",
            "parameters",
            "url",
            "dom_element",
            "dom_tree_snapshot",
            "visual_features",
            "screenshot_before",
            "screenshot_after",
            "timestamp",
        ]

        actions = []
        for result in results:
            action = dict(zip(columns, result))
            # 反序列化 JSON 字段
            for field in ["parameters", "dom_element", "dom_tree_snapshot", "visual_features"]:
                if action.get(field):
                    action[field] = json.loads(action[field])
            actions.append(action)

        return actions

    def get_network_requests(self, action_id: int) -> List[Dict[str, Any]]:
        """
        获取操作关联的网络请求

        Args:
            action_id: 操作 ID

        Returns:
            网络请求列表
        """
        results = self.db.fetchall(
            "SELECT * FROM network_requests WHERE action_id = ?", (action_id,)
        )

        columns = [
            "request_id",
            "action_id",
            "recording_id",
            "url",
            "method",
            "request_type",
            "request_headers",
            "request_body",
            "response_status",
            "response_headers",
            "response_body",
            "duration",
            "timestamp",
            "filtered",
            "filter_reason",
            "filtered_at",
            "is_recommendation",
            "importance_level",
        ]

        requests = []
        for result in results:
            request = dict(zip(columns, result))
            # 反序列化 JSON 字段
            for field in ["request_headers", "response_headers", "filter_reason"]:
                if request.get(field):
                    request[field] = json.loads(request[field])
            requests.append(request)

        return requests

    def get_sibling_snapshot(self, action_id: int) -> Optional[Dict[str, Any]]:
        """
        获取操作的兄弟元素快照

        Args:
            action_id: 操作 ID

        Returns:
            兄弟元素快照或 None
        """
        result = self.db.fetchone(
            "SELECT * FROM sibling_snapshots WHERE action_id = ?", (action_id,)
        )

        if not result:
            return None

        columns = [
            "snapshot_id",
            "action_id",
            "recording_id",
            "container_selector",
            "item_selector",
            "list_type",
            "siblings",
            "structure_similarity",
            "is_homogeneous",
            "clicked_index",
            "total_count",
            "timestamp",
        ]

        snapshot = dict(zip(columns, result))
        # 反序列化 siblings
        if snapshot.get("siblings"):
            snapshot["siblings"] = json.loads(snapshot["siblings"])

        return snapshot

    def get_sibling_snapshot_action_ids(self, recording_id: str) -> set:
        """
        获取指定录制中所有有兄弟元素快照的 action_id 集合（用于 action_summary 批量判断）

        Args:
            recording_id: 录制会话 ID

        Returns:
            有兄弟元素快照的 action_id 集合
        """
        results = self.db.fetchall(
            "SELECT action_id FROM sibling_snapshots WHERE recording_id = ?", (recording_id,)
        )
        return {row[0] for row in results} if results else set()

    def get_list_context(self, action_id: int) -> Optional[Dict[str, Any]]:
        """
        获取操作的列表上下文

        Args:
            action_id: 操作 ID

        Returns:
            列表上下文或 None
        """
        result = self.db.fetchone(
            "SELECT * FROM list_contexts WHERE action_id = ?", (action_id,)
        )

        if not result:
            return None

        columns = [
            "context_id",
            "action_id",
            "recording_id",
            "list_pattern",
            "parent_element",
            "selection_rules",
            "api_url_pattern",
            "api_response_mapping",
            "timestamp",
        ]

        context = dict(zip(columns, result))
        # 反序列化 JSON 字段
        for field in ["parent_element", "selection_rules", "api_response_mapping"]:
            if context.get(field):
                context[field] = json.loads(context[field])

        return context

    def get_all_recording_ids(self) -> List[str]:
        """
        获取所有录制会话 ID

        Returns:
            录制会话 ID 列表
        """
        results = self.db.fetchall(
            "SELECT recording_id FROM recording_sessions ORDER BY start_time DESC"
        )
        return [row[0] for row in results]

    def delete_recording(self, recording_id: str) -> bool:
        """
        删除录制会话及相关数据

        Args:
            recording_id: 录制会话 ID

        Returns:
            是否删除成功
        """
        try:
            # 由于外键约束，先删除关联数据
            # 获取所有 action_id
            action_results = self.db.fetchall(
                "SELECT action_id FROM actions WHERE recording_id = ?", (recording_id,)
            )

            action_ids = [row[0] for row in action_results]

            # 删除关联数据
            for action_id in action_ids:
                self.db.execute("DELETE FROM network_requests WHERE action_id = ?", (action_id,))
                self.db.execute("DELETE FROM sibling_snapshots WHERE action_id = ?", (action_id,))
                self.db.execute("DELETE FROM list_contexts WHERE action_id = ?", (action_id,))

            # 删除操作
            self.db.execute("DELETE FROM actions WHERE recording_id = ?", (recording_id,))

            # 删除会话
            self.db.execute(
                "DELETE FROM recording_sessions WHERE recording_id = ?", (recording_id,)
            )

            logger.info(f"录制会话已删除: {recording_id}")
            return True
        except Exception as e:
            logger.error(f"删除录制会话失败: {e}")
            return False

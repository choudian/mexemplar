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

        rows = []
        for request in network_requests:
            rows.append({
                "action_id": action_id,
                "recording_id": recording_id,
                "url": request.get("url"),
                "method": request.get("method"),
                "request_type": request.get("request_type"),
                "request_headers": json.dumps(request.get("request_headers", {}), ensure_ascii=False),
                "request_body": request.get("request_body"),
                "response_status": request.get("response_status"),
                "response_headers": json.dumps(request.get("response_headers", {}), ensure_ascii=False),
                "response_body": request.get("response_body"),
                "duration": request.get("duration"),
                "timestamp": datetime.fromtimestamp(request.get("timestamp", 0)),
                "filtered": False,
                "filter_reason": None,
                "filtered_at": None,
            })

        try:
            request_ids = self.db.insert_many("network_requests", rows)
        except Exception as e:
            logger.error(f"批量保存网络请求失败: {e}", exc_info=True)
            return []

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



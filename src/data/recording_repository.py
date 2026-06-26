"""
录制数据仓库模块

负责录制数据的持久化存储和查询
"""

import json
import logging
import threading
from typing import Optional, List, Dict, Any
from src.utils.timezone import coerce_timestamp, from_timestamp_utc_naive, utc_now_naive
from src.data.recording_models import FilterDecision

from .duckdb_manager import DuckDBManager

logger = logging.getLogger(__name__)


class RecordingRepository:
    """录制数据仓库"""

    _desktop_tables_ensured = False
    _desktop_tables_lock = threading.Lock()

    @staticmethod
    def _resolve_db_manager(db_manager: Optional[DuckDBManager] = None) -> DuckDBManager:
        """标准化 DuckDB 管理器，必要时初始化连接。"""
        if db_manager is None:
            db_manager = DuckDBManager()
            if db_manager.conn is None:
                db_manager.initialize()
        return db_manager

    def __init__(
        self,
        db_manager: Optional[DuckDBManager] = None,
        *,
        auto_recover: bool = False,
    ):
        """
        初始化录制数据仓库

        Args:
            db_manager: DuckDB 管理器，如果为None则使用全局单例
            auto_recover: deprecated, recovery 已搬到 src/recording/recovery/，保留为 noop 以兼容既有调用与测试
        """
        self.db = self._resolve_db_manager(db_manager)

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
            from_timestamp_utc_naive(session["start_time"]) if session.get("start_time") else None
        )
        end_time = (
            from_timestamp_utc_naive(session["end_time"]) if session.get("end_time") else None
        )

        # 序列化 metadata
        metadata = json.dumps(session.get("metadata", {}), ensure_ascii=False)

        self.db.insert(
            "recording_sessions",
            {
                "recording_id": recording_id,
                "status": session.get("status", "idle"),
                "recording_mode": session.get("recording_mode", "browser"),
                "browser_type": session.get("browser_type"),
                "start_time": start_time,
                "end_time": end_time,
                "metadata": metadata,
            },
            auto_commit=True,
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
                timestamp = from_timestamp_utc_naive(action.get("timestamp", 0))

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
                        "recording_mode": action.get("recording_mode", "browser"),
                        "app_name": action.get("app_name"),
                        "process_name": action.get("process_name"),
                        "window_title": action.get("window_title"),
                        "parameters": parameters,
                        "url": action.get("url"),
                        "dom_element": dom_element,
                        "dom_tree_snapshot": dom_tree_snapshot,
                        "visual_features": visual_features,
                        "timestamp": timestamp,
                    }
                )

            # 批量插入（最后一个批次自动提交）
            is_last_batch = (i + batch_size) >= len(actions)
            action_ids.extend(self.db.insert_many("actions", batch_data, auto_commit=is_last_batch))

        logger.info(f"已保存 {len(action_ids)} 条操作记录")
        return action_ids

    _DESKTOP_ACTION_COLUMNS = (
        "action_id",
        "recording_id",
        "recording_mode",
        "type",
        "coord_x",
        "coord_y",
        "monitor_index",
        "window_title",
        "uia_summary",
        "clipboard_text",
        "clipboard_image_path",
        "text_content",
        "timestamp",
        "duration_ms",
        "frame_count",
        "has_clip",
        "clip_path",
        "clip_duration_ms",
        "clip_fps",
        "clip_resolution",
    )

    def ensure_desktop_tables(self) -> None:
        """Create desktop recording tables and indexes in DuckDB."""
        if self._desktop_tables_ensured:
            return
        with self._desktop_tables_lock:
            if self._desktop_tables_ensured:
                return
            self.db.execute("""
            CREATE TABLE IF NOT EXISTS desktop_recordings (
                recording_id VARCHAR PRIMARY KEY,
                recording_mode VARCHAR NOT NULL DEFAULT 'desktop',
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                monitor_index INTEGER NOT NULL,
                status VARCHAR NOT NULL CHECK (status IN ('recording', 'stopped', 'abandoned')),
                health_stats JSON,
                created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
            )
            """)
            self.db.execute("""
                CREATE TABLE IF NOT EXISTS desktop_actions (
                action_id VARCHAR PRIMARY KEY,
                recording_id VARCHAR NOT NULL,
                recording_mode VARCHAR NOT NULL DEFAULT 'desktop',
                type VARCHAR NOT NULL CHECK (
                    type IN (
                        'mouse_left',
                        'mouse_right',
                        'mouse_middle',
                        'wheel',
                        'drag',
                        'typing',
                        'hotkey'
                    )
                ),
                coord_x INTEGER,
                coord_y INTEGER,
                monitor_index INTEGER NOT NULL,
                window_title VARCHAR,
                uia_summary JSON,
                clipboard_text VARCHAR,
                clipboard_image_path VARCHAR,
                text_content VARCHAR,
                timestamp TIMESTAMP NOT NULL,
                duration_ms INTEGER,
                frame_count INTEGER NOT NULL DEFAULT 0,
                has_clip BOOLEAN NOT NULL DEFAULT FALSE,
                clip_path VARCHAR,
                clip_duration_ms INTEGER,
                clip_fps INTEGER,
                clip_resolution VARCHAR,
                created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
            )
            """)
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS desktop_actions_recording_timestamp_idx "
                "ON desktop_actions (recording_id, timestamp)"
            )
            self.db.execute(
                "CREATE INDEX IF NOT EXISTS desktop_actions_recording_type_idx "
                "ON desktop_actions (recording_id, type)"
            )
            self._desktop_tables_ensured = True

    def insert_desktop_recording(self, data: Dict[str, Any]) -> str:
        self.ensure_desktop_tables()
        recording_id = data["recording_id"]
        row = {
            "recording_id": recording_id,
            "recording_mode": data.get("recording_mode", "desktop"),
            "start_time": coerce_timestamp(data.get("start_time")) or utc_now_naive(),
            "end_time": coerce_timestamp(data.get("end_time")),
            "monitor_index": int(data.get("monitor_index", 0)),
            "status": data.get("status", "recording"),
            "health_stats": (
                json.dumps(data.get("health_stats"), ensure_ascii=False)
                if data.get("health_stats") is not None
                else None
            ),
        }
        self.db.insert("desktop_recordings", row, auto_commit=True)
        return recording_id

    def update_desktop_recording_status(
        self, recording_id: str, status: str, *, end_time: Any | None = None
    ) -> None:
        self.ensure_desktop_tables()
        if status not in {"recording", "stopped", "abandoned"}:
            raise ValueError(f"invalid desktop recording status: {status}")
        if end_time is None and status in {"stopped", "abandoned"}:
            end_time = utc_now_naive()
        self.db.execute(
            "UPDATE desktop_recordings SET status = ?, end_time = COALESCE(?, end_time) "
            "WHERE recording_id = ?",
            (status, coerce_timestamp(end_time), recording_id),
        )

    def update_desktop_recording_health_stats(
        self, recording_id: str, health_stats: Dict[str, Any]
    ) -> None:
        self.ensure_desktop_tables()
        self.db.execute(
            "UPDATE desktop_recordings SET health_stats = ? WHERE recording_id = ?",
            (json.dumps(health_stats, ensure_ascii=False), recording_id),
        )

    def get_desktop_recording_meta(self, recording_id: str) -> Dict[str, Any] | None:
        self.ensure_desktop_tables()
        row = self.db.fetchone(
            """
            SELECT recording_id, recording_mode, start_time, end_time, monitor_index, status,
                   health_stats, created_at
            FROM desktop_recordings
            WHERE recording_id = ?
            """,
            (recording_id,),
        )
        if row is None:
            return None
        health_stats = row[6]
        if isinstance(health_stats, str):
            try:
                health_stats = json.loads(health_stats)
            except json.JSONDecodeError:
                health_stats = None
        return {
            "recording_id": row[0],
            "recording_mode": row[1],
            "start_time": row[2],
            "end_time": row[3],
            "monitor_index": row[4],
            "status": row[5],
            "health_stats": health_stats,
            "created_at": row[7],
        }

    def insert_desktop_action(self, data: Dict[str, Any]) -> str:
        self.ensure_desktop_tables()
        action_id = data["action_id"]
        row = {
            "action_id": action_id,
            "recording_id": data["recording_id"],
            "recording_mode": data.get("recording_mode", "desktop"),
            "type": data["type"],
            "coord_x": data.get("coord_x"),
            "coord_y": data.get("coord_y"),
            "monitor_index": int(data.get("monitor_index", 0)),
            "window_title": data.get("window_title"),
            "uia_summary": (
                json.dumps(data.get("uia_summary"), ensure_ascii=False)
                if data.get("uia_summary") is not None
                else None
            ),
            "clipboard_text": data.get("clipboard_text"),
            "clipboard_image_path": data.get("clipboard_image_path"),
            "text_content": data.get("text_content"),
            "timestamp": coerce_timestamp(data.get("timestamp")) or utc_now_naive(),
            "duration_ms": data.get("duration_ms"),
            "frame_count": int(data.get("frame_count", 0)),
            "has_clip": bool(data.get("has_clip", False)),
            "clip_path": data.get("clip_path"),
            "clip_duration_ms": data.get("clip_duration_ms"),
            "clip_fps": data.get("clip_fps"),
            "clip_resolution": data.get("clip_resolution"),
        }
        self.db.insert("desktop_actions", row, auto_commit=True)
        return action_id

    def update_desktop_action_frames(self, action_id: str, frame_data: Dict[str, Any]) -> None:
        self.ensure_desktop_tables()
        sets = []
        params: list[Any] = []
        for col in (
            "frame_count",
            "has_clip",
            "clip_path",
            "clip_duration_ms",
            "clip_fps",
            "clip_resolution",
        ):
            if col in frame_data:
                sets.append(f"{col} = ?")
                params.append(frame_data[col])
        if not sets:
            return
        params.append(action_id)
        self.db.execute(
            f"UPDATE desktop_actions SET {', '.join(sets)} WHERE action_id = ?",
            params,
        )

    def list_desktop_actions(
        self,
        recording_id: str,
        *,
        action_types: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Dict[str, Any]]:
        self.ensure_desktop_tables()
        if limit > 500:
            raise ValueError("limit_too_large")
        params: list[Any] = [recording_id]
        where = ["recording_id = ?"]
        if action_types:
            placeholders = ", ".join("?" for _ in action_types)
            where.append(f"type IN ({placeholders})")
            params.extend(action_types)
        params.extend([limit, offset])
        columns = list(self._DESKTOP_ACTION_COLUMNS)
        sql = (
            f"SELECT {', '.join(columns)} FROM desktop_actions "
            f"WHERE {' AND '.join(where)} ORDER BY timestamp LIMIT ? OFFSET ?"
        )
        rows = self.db.fetchall(sql, tuple(params))
        result: list[Dict[str, Any]] = []
        for row in rows:
            item = dict(zip(columns, row))
            if isinstance(item.get("uia_summary"), str):
                try:
                    item["uia_summary"] = json.loads(item["uia_summary"])
                except json.JSONDecodeError:
                    pass
            result.append(item)
        return result

    def get_desktop_action_clip(self, recording_id: str, action_id: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT has_clip, clip_path, clip_duration_ms, clip_fps, clip_resolution
            FROM desktop_actions
            WHERE recording_id = ? AND action_id = ?
            """,
            (recording_id, action_id),
        )
        if row is None:
            return None
        columns = ["has_clip", "clip_path", "clip_duration_ms", "clip_fps", "clip_resolution"]
        return dict(zip(columns, row))

    def get_desktop_actions_by_ids(
        self,
        recording_id: str,
        action_ids: list[str],
    ) -> list[dict[str, Any]]:
        if not action_ids:
            return []
        placeholders = ", ".join("?" for _ in action_ids)
        columns = [
            "action_id",
            "type",
            "text_content",
            "clipboard_text",
            "clipboard_image_path",
            "frame_count",
            "window_title",
        ]
        sql = (
            f"SELECT {', '.join(columns)} FROM desktop_actions "
            f"WHERE recording_id = ? AND action_id IN ({placeholders})"
        )
        rows = self.db.fetchall(sql, (recording_id, *action_ids))
        return [dict(zip(columns, row)) for row in rows]

    def get_recording_mode(self, recording_id: str) -> str:
        row = self.db.fetchone(
            "SELECT recording_mode FROM recording_sessions WHERE recording_id = ?",
            (recording_id,),
        )
        if row and row[0]:
            mode = str(row[0])
            if mode == "extension_triggered":
                return "browser"
            return mode
        self.ensure_desktop_tables()
        row = self.db.fetchone(
            "SELECT recording_mode FROM desktop_recordings WHERE recording_id = ?",
            (recording_id,),
        )
        if row and row[0]:
            return str(row[0])
        raise ValueError("recording_not_found")

    def save_network_requests(
        self,
        network_requests: List[Dict[str, Any]],
        recording_id: Optional[str] = None,
    ) -> Dict[int, int]:
        """
        保存网络请求

        Args:
            network_requests: 网络请求列表；每条记录自带 action_id / filtered / filter_reason / filtered_at
            recording_id: 录制会话 ID（用于直接关联，提高查询性能）

        Returns:
            batch_index 到 request_id 的映射
        """
        if not network_requests:
            logger.debug(f"save_network_requests: 网络请求列表为空 (recording_id={recording_id})")
            return {}

        logger.debug(
            f"save_network_requests: 准备保存 {len(network_requests)} 条网络请求 (recording_id={recording_id})"
        )

        rows = []
        for request in network_requests:
            filter_reason = request.get("filter_reason")
            rows.append(
                {
                    "action_id": request.get("action_id"),
                    "recording_id": recording_id,
                    "url": request.get("url"),
                    "method": request.get("method"),
                    "request_type": request.get("request_type"),
                    "request_headers": json.dumps(
                        request.get("request_headers", {}), ensure_ascii=False
                    ),
                    "request_body": request.get("request_body"),
                    "response_status": request.get("response_status"),
                    "response_headers": json.dumps(
                        request.get("response_headers", {}), ensure_ascii=False
                    ),
                    "response_body": request.get("response_body"),
                    "duration": request.get("duration"),
                    "timestamp": (
                        coerce_timestamp(ts)
                        if (ts := request.get("timestamp")) is not None
                        else utc_now_naive()
                    ),
                    "filtered": bool(request.get("filtered", False)),
                    "filter_reason": (
                        json.dumps(filter_reason, ensure_ascii=False)
                        if filter_reason is not None
                        else None
                    ),
                    "filtered_at": coerce_timestamp(request.get("filtered_at")),
                }
            )

        request_ids = self.db.insert_many("network_requests", rows)
        request_id_map = {
            batch_index: request_id for batch_index, request_id in enumerate(request_ids)
        }

        logger.info(
            f"save_network_requests: 成功保存 {len(request_ids)}/{len(network_requests)} 条网络请求"
        )
        return request_id_map

    def save_filter_decisions(self, decisions: List[FilterDecision]) -> List[int]:
        """批量保存过滤决策。"""
        if not decisions:
            return []

        rows = []
        for decision in decisions:
            rows.append(
                {
                    "request_id": decision.request_id,
                    "action_id": decision.action_id,
                    "recording_id": decision.recording_id,
                    "decision": decision.decision,
                    "source": decision.source,
                    "confidence": decision.confidence,
                    "reason": decision.reason,
                    "pattern_matched": decision.pattern_matched,
                    "scores": (
                        json.dumps(decision.scores, ensure_ascii=False)
                        if decision.scores is not None
                        else None
                    ),
                    "request_timestamp": coerce_timestamp(decision.request_timestamp),
                    "action_timestamp": coerce_timestamp(decision.action_timestamp),
                    "timestamp": (
                        coerce_timestamp(decision.timestamp)
                        if decision.timestamp is not None
                        else utc_now_naive()
                    ),
                }
            )

        decision_ids = self.db.insert_many("filter_decisions", rows)
        logger.info(f"已保存 {len(decision_ids)} 条过滤决策")
        return decision_ids

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

        timestamp = (
            from_timestamp_utc_naive(ts)
            if (ts := siblings_snapshot.get("timestamp")) is not None
            else utc_now_naive()
        )

        snapshot_id = self.db.insert(
            "sibling_snapshots",
            {
                "action_id": action_id,
                "recording_id": recording_id,
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

    def insert_screenshot_batch(
        self, batch: list[dict[str, Any]], *, auto_commit: bool = True
    ) -> list[int]:
        """
        批量插入截图记录到 recording_screenshots 表。

        Args:
            batch: 数据字典列表，每个字典包含 recording_screenshots 表的列。
                   timestamp 字段应为已转换的 datetime 对象。
            auto_commit: 是否自动提交事务（最终批次设为 True）。

        Returns:
            插入的行 ID 列表
        """
        if not batch:
            return []

        normalized_batch: list[dict[str, Any]] = []
        for row in batch:
            normalized = dict(row)

            for key in ("timestamp", "input_started_at", "input_completed_at"):
                value = normalized.get(key)
                if isinstance(value, (int, float)):
                    normalized[key] = from_timestamp_utc_naive(value)

            normalized_batch.append(normalized)

        row_ids = self.db.insert_many(
            "recording_screenshots",
            normalized_batch,
            auto_commit=auto_commit,
        )
        logger.info(f"已保存 {len(row_ids)} 条截图记录")
        return row_ids

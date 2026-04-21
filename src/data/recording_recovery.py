"""
录制数据恢复模块

负责从 queues 队列文件恢复录制数据到 DuckDB
当 DuckDB 数据丢失或损坏时，可以从保底的 queues 文件恢复
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from .duckdb_manager import DuckDBManager
from .recording_repository import RecordingRepository
from src.recording.browser.duckdb_recording_persister import DuckDBRecordingPersister
from src.recording.browser.recorder import RecordingMode
from src.recording.filtering.ingest_hook import persist_filtered_network_requests

logger = logging.getLogger(__name__)


class RecordingRecovery:
    """录制数据恢复器"""

    def __init__(self, queues_dir: Optional[Path] = None, db_manager: Optional[DuckDBManager] = None):
        """
        初始化恢复器

        Args:
            queues_dir: queues 目录路径，默认为 data/queues
            db_manager: DuckDB 管理器，默认为全局单例
        """
        if queues_dir is None:
            from src.recording.queue_paths import get_recording_queue_dir
            queues_dir = get_recording_queue_dir()

        self.queues_dir = Path(queues_dir)
        self.db_manager = db_manager or DuckDBManager()
        self.repository = RecordingRepository(self.db_manager, auto_recover=False)
        self._event_converter = DuckDBRecordingPersister(logger=logger)

    def list_queue_files(self) -> List[Path]:
        """
        列出所有队列文件

        Returns:
            队列文件路径列表
        """
        if not self.queues_dir.exists():
            logger.warning(f"Queues 目录不存在: {self.queues_dir}")
            return []

        return sorted(self.queues_dir.glob("*_actions.jsonl"))

    def parse_queue_file(self, queue_file: Path) -> Dict[str, Any]:
        """
        解析队列文件，提取录制数据

        Args:
            queue_file: 队列文件路径

        Returns:
            解析后的录制数据
        """
        actions = []
        action_network_requests: Dict[int, List[Dict[str, Any]]] = {}
        sibling_snapshots: Dict[int, Dict[str, Any]] = {}
        standalone_network_requests = []
        timestamps = []
        recording_id = None
        recording_mode = RecordingMode.BROWSER

        try:
            with open(queue_file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)

                        # 提取 recording_id
                        if recording_id is None:
                            recording_id = event.get("recording_id")

                        raw_action = event.get("action", {})
                        event_mode = raw_action.get("recording_mode") or RecordingMode.BROWSER
                        if event_mode:
                            recording_mode = event_mode

                        action_data = self._event_converter.convert_event_to_action_dict(
                            event,
                            active_recording_mode=event_mode,
                        )

                        if (timestamp := action_data.get("timestamp")) is not None:
                            timestamps.append(timestamp)

                        if action_data.get("action_type") == "network_request":
                            extracted_request = action_data.get("_extracted_network_request")
                            if extracted_request:
                                standalone_network_requests.append(extracted_request)
                            continue

                        action_index = len(actions)
                        actions.append(action_data)

                        if action_data.get("network_requests"):
                            action_network_requests[action_index] = action_data["network_requests"]
                        if action_data.get("siblings_snapshot"):
                            sibling_snapshots[action_index] = action_data["siblings_snapshot"]

                    except json.JSONDecodeError as e:
                        logger.warning(f"解析 {queue_file.name} 第 {line_num} 行失败: {e}")
                        continue

            return {
                "recording_id": recording_id,
                "actions": actions,
                "action_network_requests": action_network_requests,
                "sibling_snapshots": sibling_snapshots,
                "standalone_network_requests": standalone_network_requests,
                "timestamps": timestamps,
                "recording_mode": recording_mode,
                "action_count": len(actions),
                "queue_file": queue_file,
            }

        except Exception as e:
            logger.error(f"读取队列文件失败 {queue_file}: {e}")
            return {
                "recording_id": None,
                "actions": [],
                "action_network_requests": {},
                "sibling_snapshots": {},
                "standalone_network_requests": [],
                "timestamps": [],
                "recording_mode": RecordingMode.BROWSER,
                "action_count": 0,
                "queue_file": queue_file,
            }

    def check_recording_exists(self, recording_id: str) -> bool:
        """
        检查录制是否已在 DuckDB 中存在

        Args:
            recording_id: 录制 ID

        Returns:
            是否存在
        """
        try:
            result = self.db_manager.fetchone(
                "SELECT recording_id FROM recording_sessions WHERE recording_id = ?",
                (recording_id,)
            )
            return result is not None
        except Exception as e:
            logger.error(f"检查录制存在性失败: {e}")
            return False

    def recover_recording(self, recording_id: str, queue_file: Path, overwrite: bool = False) -> bool:
        """
        从队列文件恢复单个录制

        Args:
            recording_id: 录制 ID
            queue_file: 队列文件路径
            overwrite: 是否覆盖已存在的数据

        Returns:
            是否恢复成功
        """
        logger.info(f"开始恢复录制: {recording_id}")

        # 检查是否已存在
        if not overwrite and self.check_recording_exists(recording_id):
            logger.info(f"录制 {recording_id} 已存在，跳过恢复（使用 --overwrite 强制覆盖）")
            return False

        try:
            # 解析队列文件
            data = self.parse_queue_file(queue_file)
            actions = data["actions"]
            action_network_requests = data["action_network_requests"]
            sibling_snapshots = data["sibling_snapshots"]
            standalone_network_requests = data["standalone_network_requests"]
            timestamps = data["timestamps"]
            recording_mode = data["recording_mode"]

            if not actions and not standalone_network_requests:
                logger.warning(f"队列文件中没有有效数据: {queue_file.name}")
                return False

            # 提取时间范围
            start_time = min(timestamps) if timestamps else 0
            end_time = max(timestamps) if timestamps else 0
            browser_type = RecordingMode.display_defaults(recording_mode)["browser_type"]

            # 保存录制会话
            session_data = {
                "recording_id": recording_id,
                "status": "completed",
                "recording_mode": recording_mode,
                "browser_type": browser_type,
                "start_time": start_time,
                "end_time": end_time,
                "metadata": json.dumps({"recovered": True, "queue_file": str(queue_file)}, ensure_ascii=False),
            }

            with self.db_manager.transaction():
                if overwrite:
                    logger.info(f"删除旧数据: {recording_id}")
                    for table in (
                        "filter_decisions", "network_requests",
                        "sibling_snapshots", "actions", "recording_sessions",
                    ):
                        self.db_manager.execute(
                            f"DELETE FROM {table} WHERE recording_id = ?",
                            (recording_id,),
                        )

                self.repository.save_recording_session(session_data)
                logger.info(f"✅ 录制会话已恢复: {recording_id}")

                action_ids = []
                if actions:
                    action_ids = self.repository.save_actions(recording_id, actions)
                    logger.info(f"✅ 已恢复 {len(action_ids)} 条操作记录")

                snapshot_count = 0
                for index, action_id in enumerate(action_ids):
                    siblings_snapshot = sibling_snapshots.get(index)
                    if siblings_snapshot:
                        self.repository.save_sibling_snapshot(action_id, siblings_snapshot, recording_id)
                        snapshot_count += 1

                if snapshot_count > 0:
                    logger.info(f"✅ 已恢复 {snapshot_count} 条兄弟元素快照")

                persist_filtered_network_requests(
                    self.repository,
                    recording_id,
                    actions,
                    action_ids,
                    action_network_requests,
                    standalone_network_requests,
                    log_prefix="✅ 已恢复",
                )

            return True

        except Exception as e:
            logger.error(f"恢复录制失败 {recording_id}: {e}", exc_info=True)
            return False

    def auto_recover_on_startup(self) -> bool:
        """
        启动时自动恢复：按优先级恢复数据

        恢复优先级：
        1. 检查是否有 WAL 文件
           - 没有 → 没问题，不需要恢复
           - 有 → 连接数据库（DuckDB 自动恢复 WAL）
        2. 检查连接是否成功
           - 成功 → WAL 已恢复 ✅
           - 失败 → WAL 可能损坏，检查队列文件（保底方案）
        3. 从队列文件恢复（如果有的话）

        Returns:
            是否执行了恢复
        """
        recovered = False
        try:
            wal_path = Path(self.db_manager.db_path).with_suffix(".duckdb.wal")
            if wal_path.exists():
                logger.info(f"📋 发现 WAL 文件: {wal_path.name}")
                logger.info("🔄 连接数据库（DuckDB 将自动恢复 WAL）...")
                try:
                    self.db_manager.connect()
                    logger.info("✅ 数据库连接成功，WAL 已自动恢复")
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"数据库连接失败: {e}")
                    if "WAL" in error_msg or "Failure while replaying" in error_msg:
                        logger.warning("⚠️ WAL 文件可能损坏，将继续检查队列文件")
                    else:
                        logger.error("❌ 数据库连接失败（非 WAL 错误）")
                        return False
            else:
                logger.debug("未发现 WAL 文件，直接检查队列目录")

            recovered = self._recover_from_queues()
            return recovered
        finally:
            self._cleanup_orphan_screenshots()

    def _recover_from_queues(self) -> bool:
        """
        从队列文件恢复数据（保底方案）

        Returns:
            是否恢复成功
        """
        queue_files = self.list_queue_files()

        if not queue_files:
            logger.debug("未发现待恢复的 actions queue 文件")
            return False

        logger.info("🔄 尝试从队列文件恢复（保底方案）...")

        # 统计队列文件对应的录制，哪些已在 DuckDB 中，哪些缺失
        missing_recordings = set()

        for queue_file in queue_files:
            data = self.parse_queue_file(queue_file)
            recording_id = data.get("recording_id")

            if not recording_id:
                logger.warning(f"无法从队列文件提取 recording_id: {queue_file.name}")
                continue

            if not self.check_recording_exists(recording_id):
                missing_recordings.add(recording_id)

        if not missing_recordings:
            logger.info("✅ 队列文件中的录制都已在数据库中")
            return False

        logger.info(f"🔄 从队列文件恢复 {len(missing_recordings)} 个缺失的录制...")

        results = {
            "recovered": 0,
            "failed": 0,
        }

        for queue_file in queue_files:
            data = self.parse_queue_file(queue_file)
            recording_id = data.get("recording_id")

            if not recording_id:
                continue

            # 只恢复缺失的录制
            if recording_id in missing_recordings:
                success = self.recover_recording(recording_id, queue_file, overwrite=False)
                if success:
                    results["recovered"] += 1
                else:
                    results["failed"] += 1

        if results["recovered"] > 0:
            logger.info(f"✅ 从队列文件恢复了 {results['recovered']} 个录制")
            if results["failed"] > 0:
                logger.warning(f"⚠️ {results['failed']} 个录制恢复失败")
            return True
        else:
            logger.error(f"❌ 从队列文件恢复失败: {results['failed']} 个失败")
            return False

    def _cleanup_orphan_screenshots(self) -> None:
        """清理孤儿 screenshots queue 文件（不入库、不重放）。"""
        if not self.queues_dir.exists():
            return

        for sq_file in self.queues_dir.glob("*_screenshots.jsonl"):
            logger.warning(f"发现孤儿截图队列文件: {sq_file.name}，已删除")
            try:
                sq_file.unlink()
            except Exception as exc:
                logger.warning(f"删除孤儿截图队列失败: {exc}")

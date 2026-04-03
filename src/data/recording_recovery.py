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
            project_root = Path(__file__).parent.parent.parent
            queues_dir = project_root / "data" / "queues"

        self.queues_dir = Path(queues_dir)
        self.db_manager = db_manager or DuckDBManager()
        self.repository = RecordingRepository(self.db_manager)

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
            {
                "recording_id": str,
                "actions": List[Dict],
                "action_count": int,
                "queue_file": Path
            }
        """
        actions = []
        recording_id = None

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

                        # 提取 action 数据
                        action_data = event.get("action", {})
                        action_data["recording_id"] = recording_id
                        actions.append(action_data)

                    except json.JSONDecodeError as e:
                        logger.warning(f"解析 {queue_file.name} 第 {line_num} 行失败: {e}")
                        continue

            return {
                "recording_id": recording_id,
                "actions": actions,
                "action_count": len(actions),
                "queue_file": queue_file,
            }

        except Exception as e:
            logger.error(f"读取队列文件失败 {queue_file}: {e}")
            return {
                "recording_id": None,
                "actions": [],
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

            if not actions:
                logger.warning(f"队列文件中没有有效数据: {queue_file.name}")
                return False

            # 如果是覆盖模式，先删除旧数据
            if overwrite:
                logger.info(f"删除旧数据: {recording_id}")
                self.db_manager.execute(
                    "DELETE FROM network_requests WHERE action_id IN (SELECT action_id FROM actions WHERE recording_id = ?)",
                    (recording_id,)
                )
                self.db_manager.execute(
                    "DELETE FROM actions WHERE recording_id = ?",
                    (recording_id,)
                )
                self.db_manager.execute(
                    "DELETE FROM recording_sessions WHERE recording_id = ?",
                    (recording_id,)
                )

            # 提取时间范围
            timestamps = [a.get("timestamp", 0) for a in actions if a.get("timestamp")]
            start_time = min(timestamps) if timestamps else 0
            end_time = max(timestamps) if timestamps else 0

            # 保存录制会话
            session_data = {
                "recording_id": recording_id,
                "status": "completed",
                "recording_mode": actions[0].get("recording_mode", "browser") if actions else "browser",
                "browser_type": "chromium",
                "start_time": start_time,
                "end_time": end_time,
                "metadata": json.dumps({"recovered": True, "queue_file": str(queue_file)}, ensure_ascii=False),
            }
            self.repository.save_recording_session(session_data)
            logger.info(f"✅ 录制会话已恢复: {recording_id}")

            # 保存操作记录
            action_ids = self.repository.save_actions(recording_id, actions)
            logger.info(f"✅ 已恢复 {len(action_ids)} 条操作记录")

            # 保存网络请求
            request_count = 0
            for i, action in enumerate(actions):
                action_id = action_ids[i] if i < len(action_ids) else None
                network_requests = action.get("network_requests", [])
                if network_requests:
                    self.repository.save_network_requests(action_id, network_requests, recording_id)
                    request_count += len(network_requests)

            if request_count > 0:
                logger.info(f"✅ 已恢复 {request_count} 条网络请求")

            return True

        except Exception as e:
            logger.error(f"恢复录制失败 {recording_id}: {e}", exc_info=True)
            return False

    def recover_all(self, overwrite: bool = False, delete_after: bool = False) -> Dict[str, Any]:
        """
        恢复所有队列文件中的录制

        Args:
            overwrite: 是否覆盖已存在的数据
            delete_after: 恢复成功后是否删除队列文件

        Returns:
            恢复结果统计
        """
        queue_files = self.list_queue_files()

        if not queue_files:
            logger.info("没有找到队列文件")
            return {
                "total": 0,
                "recovered": 0,
                "skipped": 0,
                "failed": 0,
                "details": [],
            }

        logger.info(f"找到 {len(queue_files)} 个队列文件")

        results = {
            "total": len(queue_files),
            "recovered": 0,
            "skipped": 0,
            "failed": 0,
            "details": [],
        }

        for queue_file in queue_files:
            # 解析文件获取 recording_id
            data = self.parse_queue_file(queue_file)
            recording_id = data.get("recording_id")

            if not recording_id:
                logger.warning(f"无法从队列文件提取 recording_id: {queue_file.name}")
                results["failed"] += 1
                results["details"].append({
                    "file": queue_file.name,
                    "status": "failed",
                    "reason": "无法提取 recording_id"
                })
                continue

            # 恢复录制
            success = self.recover_recording(recording_id, queue_file, overwrite)

            if success:
                results["recovered"] += 1
                results["details"].append({
                    "recording_id": recording_id,
                    "file": queue_file.name,
                    "status": "recovered",
                    "action_count": data.get("action_count", 0)
                })

                # 恢复成功后删除队列文件
                if delete_after:
                    try:
                        queue_file.unlink()
                        logger.info(f"已删除队列文件: {queue_file.name}")
                    except Exception as e:
                        logger.warning(f"删除队列文件失败: {e}")

            else:
                results["skipped"] += 1
                results["details"].append({
                    "recording_id": recording_id,
                    "file": queue_file.name,
                    "status": "skipped",
                    "reason": "已存在"
                })

        logger.info(f"恢复完成: {results['recovered']} 成功, {results['skipped']} 跳过, {results['failed']} 失败")
        return results

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
        # 第一步：检查是否有 WAL 文件
        wal_path = Path(self.db_manager.db_path).with_suffix(".duckdb.wal")

        if not wal_path.exists():
            logger.debug("没有 WAL 文件，无需恢复")
            return False

        logger.info(f"📋 发现 WAL 文件: {wal_path.name}")
        logger.info("🔄 连接数据库（DuckDB 将自动恢复 WAL）...")

        # 第二步：连接数据库（DuckDB 自动恢复 WAL）
        try:
            self.db_manager.connect()
            logger.info("✅ 数据库连接成功，WAL 已自动恢复")
            return False  # WAL 恢复成功，不需要进一步处理

        except Exception as e:
            error_msg = str(e)
            logger.error(f"数据库连接失败: {e}")

            # 检查是否为 WAL 相关错误
            if "WAL" in error_msg or "Failure while replaying" in error_msg:
                logger.warning("⚠️ WAL 文件可能损坏")
            else:
                logger.error("❌ 数据库连接失败（非 WAL 错误）")
                return False  # 非 WAL 错误，无法通过队列恢复

        # 第三步：连接失败，尝试从队列文件恢复（保底方案）
        return self._recover_from_queues()

    def _recover_from_queues(self) -> bool:
        """
        从队列文件恢复数据（保底方案）

        Returns:
            是否恢复成功
        """
        queue_files = self.list_queue_files()

        if not queue_files:
            logger.error("❌ 无法恢复：数据库连接失败，也没有队列文件作为保底")
            return False

        logger.info("🔄 尝试从队列文件恢复（保底方案）...")

        # 统计队列文件对应的录制，哪些已在 DuckDB 中，哪些缺失
        missing_recordings = []

        for queue_file in queue_files:
            data = self.parse_queue_file(queue_file)
            recording_id = data.get("recording_id")

            if not recording_id:
                logger.warning(f"无法从队列文件提取 recording_id: {queue_file.name}")
                continue

            if not self.check_recording_exists(recording_id):
                missing_recordings.append(recording_id)

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



def recover_from_queues(overwrite: bool = False, delete_after: bool = False) -> Dict[str, Any]:
    """
    从队列文件恢复录制数据的便捷函数

    Args:
        overwrite: 是否覆盖已存在的数据
        delete_after: 恢复成功后是否删除队列文件

    Returns:
        恢复结果统计
    """
    recovery = RecordingRecovery()
    return recovery.recover_all(overwrite=overwrite, delete_after=delete_after)

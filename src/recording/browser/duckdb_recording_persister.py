import json
import logging
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from src.data.duckdb_manager import DuckDBManager
from src.recording.filtering.ingest_hook import persist_filtered_network_requests

from .recorder import RecordingMode


def _default_repo_factory():
    from src.data.recording_repository import RecordingRepository

    return RecordingRepository(auto_recover=False)


class DuckDBRecordingPersister:
    def __init__(
        self,
        repo_factory: Optional[Callable[[], Any]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._repo_factory = repo_factory or _default_repo_factory
        self._logger = logger or logging.getLogger(__name__)
        self._recording_repository = None

    def _get_repository(self):
        if self._recording_repository is None:
            self._recording_repository = self._repo_factory()
        return self._recording_repository

    def close(self) -> None:
        if not self._recording_repository:
            return

        try:
            db = getattr(self._recording_repository, "db", None)
            if db and hasattr(db, "close"):
                db.close()
                self._logger.info("DuckDB 连接已关闭")
        except Exception as exc:
            self._logger.warning(f"关闭数据库连接失败: {exc}")
        finally:
            self._recording_repository = None

    def save_to_duckdb(
        self,
        *,
        recording_id: Optional[str],
        recording_start_time: Optional[float],
        action_queue_path: Optional[Path],
        active_recording_mode: str,
        end_time: float,
    ) -> int:
        repository = self._get_repository()
        mode_display = RecordingMode.display_defaults(active_recording_mode)
        session_data = {
            "recording_id": recording_id,
            "status": "completed",
            "recording_mode": active_recording_mode,
            "browser_type": mode_display["browser_type"],
            "start_time": recording_start_time,
            "end_time": end_time,
            "metadata": {
                "queue_file": str(action_queue_path) if action_queue_path else None,
                "websocket_mode": active_recording_mode == RecordingMode.BROWSER,
                "extension_triggered": active_recording_mode == RecordingMode.EXTENSION_TRIGGERED,
            },
        }

        if not action_queue_path or not action_queue_path.exists():
            repository.save_recording_session(session_data)
            self._logger.info(f"录制会话已保存到 DuckDB: {recording_id}")
            self._logger.warning("队列文件不存在，跳过操作保存")
            return 0

        screenshots_path = self._resolve_screenshots_queue_path(recording_id, action_queue_path)

        actions_list = []
        network_requests_map = {}
        standalone_network_requests = []

        try:
            with open(action_queue_path, "r", encoding="utf-8") as handle:
                for line_num, line in enumerate(handle, 1):
                    if not line.strip():
                        continue

                    try:
                        event_data = json.loads(line)
                        action_dict = self.convert_event_to_action_dict(
                            event_data,
                            active_recording_mode=active_recording_mode,
                            mode_display=mode_display,
                        )

                        if action_dict.get("action_type") == "network_request":
                            extracted_request = action_dict.get("_extracted_network_request")
                            if extracted_request:
                                standalone_network_requests.append(extracted_request)
                            self._logger.debug(
                                "跳过独立的 network_request action，直接保存到 network_requests 表"
                            )
                        else:
                            list_index = len(actions_list)
                            actions_list.append(action_dict)

                            action = event_data.get("action", {})
                            if action.get("network_requests"):
                                network_requests_map[list_index] = action["network_requests"]
                    except json.JSONDecodeError as exc:
                        self._logger.warning(f"解析事件 {line_num} 失败: {exc}")
                    except Exception as exc:
                        self._logger.warning(f"处理事件 {line_num} 失败: {exc}")
        except Exception as exc:
            self._logger.error(f"读取队列文件失败: {exc}")
            return 0

        db = getattr(repository, "db", None)
        transaction_ctx = (
            db.transaction()
            if isinstance(db, DuckDBManager)
            else nullcontext()
        )

        screenshot_count = 0
        try:
            with transaction_ctx:
                repository.save_recording_session(session_data)
                self._logger.info(f"录制会话已保存到 DuckDB: {recording_id}")

                action_ids = []
                if actions_list:
                    action_ids = repository.save_actions(recording_id, actions_list)
                    self._logger.info(f"已保存 {len(action_ids)} 条操作到 DuckDB")

                    snapshot_count = 0
                    for index, action_id in enumerate(action_ids):
                        if index < len(actions_list) and actions_list[index].get("siblings_snapshot"):
                            try:
                                repository.save_sibling_snapshot(
                                    action_id,
                                    actions_list[index]["siblings_snapshot"],
                                    recording_id,
                                )
                                snapshot_count += 1
                            except Exception as exc:
                                self._logger.warning(
                                    f"保存兄弟元素快照失败 (action_id={action_id}): {exc}"
                                )
                    if snapshot_count > 0:
                        self._logger.info(f"已保存 {snapshot_count} 条兄弟元素快照到 DuckDB")

                persist_filtered_network_requests(
                    repository,
                    recording_id,
                    actions_list,
                    action_ids,
                    network_requests_map,
                    standalone_network_requests,
                )

                screenshot_count = self._save_screenshots(repository, screenshots_path)
                if screenshot_count > 0:
                    self._logger.info(f"已保存 {screenshot_count} 条截图到 DuckDB")
        except Exception:
            self._logger.error("保存录制数据到 DuckDB 失败，已保留 queue 文件", exc_info=True)
            raise

        from src.recording.queue_paths import delete_queue_file
        delete_queue_file(action_queue_path)
        delete_queue_file(screenshots_path)

        return len(actions_list)

    def _save_screenshots(self, repository, screenshots_path: Optional[Path]):
        """读取 screenshots queue 并批量入库。"""
        if not screenshots_path:
            return 0

        from src.recording.browser.screenshot_queue_parser import (
            iter_screenshots_queue,
            batch_insert_screenshots,
        )

        if not screenshots_path.exists():
            return 0

        rows = iter_screenshots_queue(screenshots_path)
        return batch_insert_screenshots(repository, rows)

    def _resolve_screenshots_queue_path(
        self,
        recording_id: Optional[str],
        action_queue_path: Optional[Path] = None,
    ) -> Optional[Path]:
        if not recording_id:
            return None
        if action_queue_path:
            return action_queue_path.with_name(f"{recording_id}_screenshots.jsonl")
        from src.recording.queue_paths import get_recording_screenshots_queue_path
        return get_recording_screenshots_queue_path(recording_id)

    def convert_event_to_action_dict(
        self,
        event_data: Dict[str, Any],
        *,
        active_recording_mode: str,
        mode_display: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        action = event_data.get("action", {})
        if not action and event_data.get("action_type"):
            action = event_data

        if mode_display is None:
            mode_display = RecordingMode.display_defaults(active_recording_mode)

        action_dict = {
            "action_type": action.get("action_type"),
            "recording_mode": active_recording_mode,
            "app_name": mode_display["app_name"],
            "process_name": mode_display["process_name"],
            "window_title": action.get("page_title"),
            "parameters": action.get("parameters", {}),
            "url": action.get("url"),
            "dom_element": action.get("dom_element"),
            "timestamp": action.get("timestamp"),
        }

        if action.get("visual_features"):
            action_dict["visual_features"] = action["visual_features"]
        if action.get("siblings_snapshot"):
            action_dict["siblings_snapshot"] = action["siblings_snapshot"]
        if action.get("dom_tree_snapshot"):
            action_dict["dom_tree_snapshot"] = action["dom_tree_snapshot"]
        if action.get("network_requests"):
            action_dict["network_requests"] = action["network_requests"]

        if action.get("action_type") == "network_request":
            params = action.get("parameters", {})
            action_dict["_extracted_network_request"] = {
                "url": action.get("url"),
                "method": params.get("method"),
                "request_type": params.get("request_type", "xhr"),
                "request_headers": params.get("request_headers", {}),
                "request_body": params.get("request_body"),
                "response_status": params.get("response_status"),
                "response_headers": params.get("response_headers", {}),
                "response_body": params.get("response_body"),
                "duration": params.get("duration"),
                "timestamp": action.get("timestamp"),
            }
            self._logger.debug(f"提取到网络请求: {action.get('url')[:60]}...")

        return action_dict

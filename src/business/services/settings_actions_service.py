from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from src.data.repos.assistant_summary_repository import AssistantSummaryRepository
from src.data.unified_config import UnifiedConfigManager, get_unified_config
from src.utils.helpers import get_default_data_dir


class SettingsActionsService:
    def __init__(
        self,
        config: UnifiedConfigManager | None = None,
        data_dir: Path | None = None,
    ):
        self._config = config or get_unified_config()
        self._data_dir = data_dir or get_default_data_dir()

    def run_action(self, action_name: str, *, confirmed: bool = False) -> dict[str, Any]:
        handlers = {
            "test_ai_connection": self._test_ai_connection,
            "test_tool_output_summary_connection": self._test_tool_output_summary_connection,
            "browse_data_directory": self._browse_data_directory,
            "backup_data": self._backup_data,
            "export_all_data": self._export_all_data,
            "clear_assistant_memory": self._clear_assistant_memory,
            "check_updates": self._check_updates,
            "open_changelog": self._open_changelog,
            "open_documentation": self._open_documentation,
            "install_extension_certificate": self._install_extension_certificate,
        }
        handler = handlers.get(action_name)
        if handler is None:
            return self._response(action_name, "unavailable", "不支持的设置动作。")
        if action_name == "clear_assistant_memory" and not confirmed:
            return self._response(
                action_name,
                "failed",
                "需要确认后才能清空助手记忆。",
                {"code": "confirmation_required"},
            )
        try:
            return handler()
        except Exception as exc:
            return self._response(
                action_name,
                "failed",
                "设置动作执行失败。",
                {"type": type(exc).__name__},
            )

    def _test_ai_connection(self) -> dict[str, Any]:
        provider = str(self._config.get("ai.provider", default="anthropic") or "").strip()
        model = str(self._config.get("ai.model", default="") or "").strip()
        if provider not in {"anthropic", "openai"}:
            return self._response("test_ai_connection", "failed", "AI 提供商配置无效。")
        if not model:
            return self._response("test_ai_connection", "failed", "AI 模型不能为空。")
        api_key = self._config.get_ai_api_key()
        if not api_key:
            return self._response(
                "test_ai_connection", "failed", "缺少 API Key。", {"code": "missing_secret"}
            )
        return self._response(
            "test_ai_connection",
            "completed",
            "AI 连接配置可用。",
            {"provider": provider, "model": model},
        )

    def _browse_data_directory(self) -> dict[str, Any]:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        return self._response(
            "browse_data_directory",
            "completed",
            "数据目录已定位。",
            {"path": str(self._data_dir)},
        )

    def _test_tool_output_summary_connection(self) -> dict[str, Any]:
        from src.business.agents.tools.semantic_summary import (
            test_semantic_summary_connection,
        )

        provider = self._config.get_agent_tools_output_semantic_summary_provider()
        model = self._config.get_agent_tools_output_semantic_summary_model()
        api_key = self._config.get_tool_output_summary_api_key()
        details = {"provider": provider, "model": model}
        if not model:
            return self._response(
                "test_tool_output_summary_connection",
                "failed",
                "摘要模型不能为空。",
                {**details, "code": "missing_model"},
            )
        if not api_key:
            return self._response(
                "test_tool_output_summary_connection",
                "failed",
                "缺少摘要 API Key。",
                {**details, "code": "missing_secret"},
            )
        ok, reason = test_semantic_summary_connection(
            config=self._config,
            api_key=api_key,
        )
        if not ok:
            messages = {
                "missing_base_url": "OpenAI-compatible 提供商需要 API 地址。",
                "invalid_base_url": "摘要模型 API 地址格式无效。",
                "invalid_provider": "摘要模型提供商配置无效。",
                "timeout": "摘要模型连接超时。",
            }
            return self._response(
                "test_tool_output_summary_connection",
                "failed",
                messages.get(reason, "摘要模型连接失败。"),
                {**details, "code": reason},
            )
        return self._response(
            "test_tool_output_summary_connection",
            "completed",
            "摘要模型连接成功。",
            details,
        )

    def _backup_data(self) -> dict[str, Any]:
        target = self._create_archive("backups", "backup")
        return self._response("backup_data", "completed", "数据备份已创建。", {"path": str(target)})

    def _export_all_data(self) -> dict[str, Any]:
        target = self._create_archive("exports", "export")
        return self._response(
            "export_all_data", "completed", "数据导出已创建。", {"path": str(target)}
        )

    def _clear_assistant_memory(self) -> dict[str, Any]:
        repo = AssistantSummaryRepository()
        for level in (1, 2, 3):
            repo.delete_by_level(level)
        return self._response("clear_assistant_memory", "completed", "助手记忆摘要已清空。")

    def _check_updates(self) -> dict[str, Any]:
        return self._response(
            "check_updates",
            "unavailable",
            "当前构建未配置更新通道。",
            {"version": self._config.get("version", default="0.1.0")},
        )

    def _open_changelog(self) -> dict[str, Any]:
        return self._response(
            "open_changelog",
            "completed",
            "更新日志入口已返回。",
            {"path": str(Path("CHANGELOG.md"))},
        )

    def _open_documentation(self) -> dict[str, Any]:
        return self._response(
            "open_documentation",
            "completed",
            "文档入口已返回。",
            {"path": str(Path("README.md"))},
        )

    def _install_extension_certificate(self) -> dict[str, Any]:
        try:
            from src.recording.cert_manager import CertManager
        except Exception as exc:
            return self._response(
                "install_extension_certificate",
                "unavailable",
                "证书管理器不可用。",
                {"type": type(exc).__name__},
            )
        ok = CertManager().ensure_installed()
        if ok:
            return self._response(
                "install_extension_certificate", "completed", "扩展证书已安装或已存在。"
            )
        return self._response("install_extension_certificate", "failed", "扩展证书安装失败。")

    def _create_archive(self, folder_name: str, prefix: str) -> Path:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        target_dir = self._data_dir / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = target_dir / f"{prefix}-{timestamp}.zip"
        excluded_roots = {target_dir.resolve()}
        if folder_name == "exports":
            excluded_roots.add((self._data_dir / "backups").resolve())
        else:
            excluded_roots.add((self._data_dir / "exports").resolve())

        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            added = False
            for path in self._data_dir.rglob("*"):
                if path == target or any(
                    self._is_relative_to(path, root) for root in excluded_roots
                ):
                    continue
                if path.is_file():
                    archive.write(path, path.relative_to(self._data_dir))
                    added = True
            if not added:
                archive.writestr("README.txt", "No user data files were present at export time.")
        shutil.copystat(self._data_dir, target, follow_symlinks=False)
        return target

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _response(
        action_name: str,
        status: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "actionName": action_name,
            "status": status,
            "message": message,
            "details": details or {},
        }

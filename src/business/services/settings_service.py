from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.data.credential_resolver import (
    ReadOnlyCredentialResolver,
    get_real_tour_credential_resolver,
    is_real_tour_runtime,
)
from src.data.config_models import AIConfig, LargeFieldConfig, RecordingConfig, RecordingDesktopConfig, UIConfig
from src.data.unified_config import UnifiedConfigManager, get_unified_config
from src.utils import events

SettingSectionId = Literal["ai", "recording", "data", "about"]
SettingKind = Literal["string", "integer", "number", "boolean", "enum", "path", "secret", "action"]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    label: str
    section: SettingSectionId
    value_kind: SettingKind
    description: str = ""
    options: list[str] = field(default_factory=list)
    validation_rules: dict[str, Any] = field(default_factory=dict)
    default: Any = None
    secret: bool = False
    status: Literal["available", "missing_secret", "invalid", "unavailable"] = "available"


SECTION_LABELS: dict[SettingSectionId, str] = {
    "ai": "AI",
    "recording": "录制",
    "data": "数据",
    "about": "关于",
}

_AI_DEFAULTS = AIConfig()
_RECORDING_DEFAULTS = RecordingConfig()
_DESKTOP_DEFAULTS = RecordingDesktopConfig()
_LARGE_FIELD_DEFAULTS = LargeFieldConfig()
_UI_DEFAULTS = UIConfig()

SETTING_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec(
        "ai.provider",
        "提供商",
        "ai",
        "enum",
        options=["anthropic", "openai"],
        default=_AI_DEFAULTS.provider,
    ),
    SettingSpec(
        "ai.model",
        "主模型",
        "ai",
        "string",
        validation_rules={"required": True},
        default=_AI_DEFAULTS.model,
    ),
    SettingSpec("ai.base_url", "API 地址", "ai", "string", default=_AI_DEFAULTS.base_url or ""),
    SettingSpec(
        "ai.temperature",
        "温度",
        "ai",
        "number",
        validation_rules={"min": 0, "max": 2},
        default=_AI_DEFAULTS.temperature,
    ),
    SettingSpec(
        "ai.timeout",
        "请求超时",
        "ai",
        "integer",
        validation_rules={"min": 1, "max": 600},
        default=_AI_DEFAULTS.timeout,
    ),
    SettingSpec(
        "ai.thinking_level",
        "推理强度",
        "ai",
        "enum",
        options=["off", "low", "medium", "high"],
        default=_AI_DEFAULTS.thinking_level,
    ),
    SettingSpec(
        "memory.cross_session_enabled",
        "跨会话记忆",
        "ai",
        "boolean",
        description="当前版本由助手记忆服务自动管理，暂不支持在 UI 中切换。",
        default=True,
        status="unavailable",
    ),
    SettingSpec(
        "assistant.repetition_recognition_enabled",
        "重复操作识别",
        "ai",
        "boolean",
        description="重复模式检测跟随助手业务策略，暂不支持手动开关。",
        default=True,
        status="unavailable",
    ),
    SettingSpec("ai.api_key", "API Key", "ai", "secret", secret=True),
    SettingSpec(
        "recording.screenshot_quality",
        "截图质量",
        "recording",
        "integer",
        validation_rules={"min": 1, "max": 100},
        default=_RECORDING_DEFAULTS.screenshot_quality,
    ),
    SettingSpec(
        "recording.enable_video_recording",
        "录制视频",
        "recording",
        "boolean",
        default=_RECORDING_DEFAULTS.enable_video_recording,
    ),
    SettingSpec(
        "recording.video_fps",
        "视频帧率",
        "recording",
        "integer",
        validation_rules={"min": 1, "max": 60},
        default=_RECORDING_DEFAULTS.video_fps,
    ),
    SettingSpec(
        "recording.video_quality",
        "视频质量",
        "recording",
        "integer",
        validation_rules={"min": 1, "max": 100},
        default=_RECORDING_DEFAULTS.video_quality,
    ),
    SettingSpec(
        "recording.capture_network_requests",
        "捕获网络请求",
        "recording",
        "boolean",
        default=_RECORDING_DEFAULTS.capture_network_requests,
    ),
    SettingSpec(
        "recording.network_request_filter",
        "网络请求过滤",
        "recording",
        "enum",
        options=["all", "xhr_fetch", "api_only"],
        default=_RECORDING_DEFAULTS.network_request_filter,
    ),
    SettingSpec(
        "recording.noise_filter.enabled",
        "噪声过滤",
        "recording",
        "boolean",
        default=_RECORDING_DEFAULTS.noise_filter.enabled,
    ),
    SettingSpec(
        "recording.default_recording_mode",
        "默认录制模式",
        "recording",
        "enum",
        options=["browser", "desktop"],
        default=_RECORDING_DEFAULTS.default_recording_mode,
    ),
    SettingSpec(
        "recording.browser_type",
        "浏览器",
        "recording",
        "enum",
        options=["chromium", "firefox", "webkit"],
        default=_RECORDING_DEFAULTS.browser_type,
    ),
    SettingSpec(
        "recording.browser_headless",
        "无头浏览器",
        "recording",
        "boolean",
        default=_RECORDING_DEFAULTS.browser_headless,
    ),
    SettingSpec(
        "recording.desktop.enable_clip",
        "桌面动作 Clip",
        "recording",
        "boolean",
        default=_DESKTOP_DEFAULTS.enable_clip,
    ),
    SettingSpec(
        "recording.desktop.vision_model",
        "桌面视觉模型",
        "recording",
        "string",
        default=_DESKTOP_DEFAULTS.vision_model or "",
    ),
    SettingSpec(
        "recording.large_field.threshold_chars",
        "大字段阈值",
        "recording",
        "integer",
        validation_rules={"min": 100, "max": 200000},
        default=_LARGE_FIELD_DEFAULTS.threshold_chars,
    ),
    SettingSpec(
        "recording.large_field.max_chunk_chars",
        "分段读取长度",
        "recording",
        "integer",
        validation_rules={"min": 100, "max": 200000},
        default=_LARGE_FIELD_DEFAULTS.max_chunk_chars,
    ),
    SettingSpec(
        "data.database_type",
        "数据库类型",
        "data",
        "enum",
        options=["sqlite"],
        description="当前桌面版业务数据固定使用 SQLite。",
        default="sqlite",
        status="unavailable",
    ),
    SettingSpec(
        "data.vector_index_enabled",
        "向量索引",
        "data",
        "boolean",
        description="向量索引由记忆仓库按运行条件自动维护，暂不支持手动切换。",
        default=True,
        status="unavailable",
    ),
    SettingSpec(
        "recording.persistent_user_data",
        "保留浏览器登录态",
        "data",
        "boolean",
        default=_RECORDING_DEFAULTS.persistent_user_data,
    ),
    SettingSpec(
        "recording.user_data_dir",
        "浏览器用户数据目录",
        "data",
        "path",
        default=_RECORDING_DEFAULTS.user_data_dir or "",
    ),
    SettingSpec(
        "app.version",
        "版本",
        "about",
        "string",
        default="0.1.0",
        status="unavailable",
    ),
    SettingSpec(
        "ui.theme",
        "界面主题",
        "about",
        "enum",
        options=["light", "dark", "system"],
        default=_UI_DEFAULTS.theme,
    ),
    SettingSpec(
        "ui.density",
        "界面密度",
        "about",
        "enum",
        options=["compact", "comfy"],
        default=_UI_DEFAULTS.density,
    ),
)

ACTION_SPECS: tuple[SettingSpec, ...] = (
    SettingSpec("test_ai_connection", "测试 AI 连接", "ai", "action"),
    SettingSpec("install_extension_certificate", "安装扩展证书", "recording", "action"),
    SettingSpec("browse_data_directory", "打开数据目录", "data", "action"),
    SettingSpec("backup_data", "备份数据", "data", "action"),
    SettingSpec("export_all_data", "导出全部数据", "data", "action"),
    SettingSpec("clear_assistant_memory", "清空助手记忆", "data", "action"),
    SettingSpec("rebuild_vector_index", "重建向量索引", "data", "action", status="unavailable"),
    SettingSpec("check_updates", "检查更新", "about", "action"),
    SettingSpec("open_changelog", "查看更新日志", "about", "action"),
    SettingSpec("open_documentation", "打开文档", "about", "action"),
)


class SettingsValidationError(ValueError):
    def __init__(self, key: str, message: str):
        super().__init__(message)
        self.key = key
        self.message = message


class SettingsService:
    def __init__(
        self,
        config: UnifiedConfigManager | None = None,
        credential_resolver: ReadOnlyCredentialResolver | None = None,
    ):
        self._config = config or get_unified_config()
        self._credential_resolver = credential_resolver or (
            get_real_tour_credential_resolver() if is_real_tour_runtime() else None
        )
        self._specs = {spec.key: spec for spec in SETTING_SPECS}
        self._actions = {spec.key: spec for spec in ACTION_SPECS}

    def get_schema(self) -> dict[str, Any]:
        sections = []
        for section_id, label in SECTION_LABELS.items():
            sections.append(
                {
                    "id": section_id,
                    "label": label,
                    "items": [
                        self._descriptor(spec)
                        for spec in SETTING_SPECS
                        if spec.section == section_id
                    ],
                    "actions": [
                        self._descriptor(spec)
                        for spec in ACTION_SPECS
                        if spec.section == section_id
                    ],
                }
            )
        return {"sections": sections}

    def get_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for spec in SETTING_SPECS:
            if spec.secret:
                continue
            value = self._config.get(spec.key, default=spec.default)
            values[spec.key] = "" if value is None else value
        return {
            "values": values,
            "secrets": {"ai.api_key": self._secret_state("ai.api_key")},
            "status": self._status_map(),
        }

    def update_values(self, values: dict[str, Any]) -> dict[str, Any]:
        for key, value in values.items():
            spec = self._specs.get(key)
            if spec is None or spec.secret:
                raise SettingsValidationError(key, "不支持的设置项。")
            if spec.status == "unavailable":
                raise SettingsValidationError(key, "该设置当前不可修改。")
            normalized = self._normalize_value(spec, value)
            self._config.set(key, normalized, value_type=self._value_type(spec))
        events.emit("settings_changed", sender=self, keys=list(values.keys()))
        return self.get_values()

    def write_secret(self, secret_key: str, value: str) -> dict[str, Any]:
        if is_real_tour_runtime():
            raise SettingsValidationError(secret_key, "真实验收期间密钥只读。")
        if secret_key != "ai.api_key":
            raise SettingsValidationError(secret_key, "不支持的密钥项。")
        secret = value.strip()
        if not secret:
            raise SettingsValidationError(secret_key, "密钥不能为空。")
        self._config.set_ai_api_key(secret)
        events.emit("settings_changed", sender=self, keys=[secret_key])
        return self._secret_state(secret_key)

    def delete_secret(self, secret_key: str) -> dict[str, Any]:
        if is_real_tour_runtime():
            raise SettingsValidationError(secret_key, "真实验收期间密钥只读。")
        if secret_key != "ai.api_key":
            raise SettingsValidationError(secret_key, "不支持的密钥项。")
        self._config.clear_ai_api_key()
        events.emit("settings_changed", sender=self, keys=[secret_key])
        return self._secret_state(secret_key)

    def _descriptor(self, spec: SettingSpec) -> dict[str, Any]:
        return {
            "key": spec.key,
            "label": spec.label,
            "section": spec.section,
            "valueKind": spec.value_kind,
            "description": spec.description,
            "options": spec.options,
            "validationRules": spec.validation_rules,
            "status": spec.status,
        }

    def _secret_state(self, secret_key: str) -> dict[str, Any]:
        present = bool(self._get_ai_api_key()) if secret_key == "ai.api_key" else False
        return {
            "secretKey": secret_key,
            "present": present,
            "masked": "••••••••" if present else "",
        }

    def _status_map(self) -> dict[str, str]:
        direct_vision_model = self._config.get("recording.desktop.vision_model", default=None)
        if not direct_vision_model:
            vision_status = "unavailable"
        elif not self._get_ai_vision_api_key():
            vision_status = "missing_secret"
        else:
            vision_status = "available"
        return {
            "ai.api_key": "available" if self._get_ai_api_key() else "missing_secret",
            "recording.desktop.vision_model": vision_status,
        }

    def _get_ai_api_key(self) -> str | None:
        if self._credential_resolver is not None:
            return self._credential_resolver.get_ai_api_key()
        return self._config.get_ai_api_key()

    def _get_ai_vision_api_key(self) -> str | None:
        if self._credential_resolver is not None:
            return self._credential_resolver.get_ai_vision_api_key()
        return self._config.get_ai_vision_api_key()

    def _normalize_value(self, spec: SettingSpec, value: Any) -> Any:
        if spec.value_kind in {"integer", "number"}:
            try:
                normalized = int(value) if spec.value_kind == "integer" else float(value)
            except (TypeError, ValueError) as exc:
                message = "必须是整数。" if spec.value_kind == "integer" else "必须是数字。"
                raise SettingsValidationError(spec.key, message) from exc
            minimum = spec.validation_rules.get("min")
            maximum = spec.validation_rules.get("max")
            if minimum is not None and normalized < minimum:
                raise SettingsValidationError(spec.key, f"不能小于 {minimum}。")
            if maximum is not None and normalized > maximum:
                raise SettingsValidationError(spec.key, f"不能大于 {maximum}。")
            return normalized
        if spec.value_kind == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if spec.value_kind == "enum":
            normalized = str(value)
            if normalized not in spec.options:
                raise SettingsValidationError(spec.key, "不支持的选项。")
            return normalized
        normalized = "" if value is None else str(value).strip()
        if spec.validation_rules.get("required") and not normalized:
            raise SettingsValidationError(spec.key, "不能为空。")
        return normalized

    @staticmethod
    def _value_type(spec: SettingSpec) -> str:
        if spec.value_kind == "integer":
            return "int"
        if spec.value_kind == "number":
            return "float"
        if spec.value_kind == "boolean":
            return "bool"
        return "string"

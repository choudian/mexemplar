"""skills.sh API client（029 D3）。

访问 `/api/v1`：列表/搜索/详情（含完整文件树）/审计。请求使用统一配置中的
skills.sh token 发送 Bearer 鉴权。所有网络错误分类为用户可读消息（FR-448）；
审计端点失败降级为 "unavailable"，不阻塞安装流。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://skills.sh/api/v1"
_TIMEOUT_SECONDS = 10.0

UNAVAILABLE_MESSAGE = "技能市场暂时无法访问，请稍后重试。"
AUTH_REQUIRED_MESSAGE = "skills.sh API token 未配置，请通过技能市场搜索结果或 GitHub 直装安装。"
AUTH_INVALID_MESSAGE = "skills.sh API token 无效或已过期，请重新搜索后重试或使用 GitHub 直装。"


class SkillsShUnavailableError(RuntimeError):
    """skills.sh 不可达/超时/服务端错误——消息面向用户。"""

    def __init__(self, message: str = UNAVAILABLE_MESSAGE):
        super().__init__(message)


class SkillsShAuthenticationError(SkillsShUnavailableError):
    """skills.sh 缺少或拒绝 token——消息面向用户。"""


class SkillsShNotFoundError(KeyError):
    """请求的技能在 skills.sh 不存在。"""


@dataclass(frozen=True)
class StoreSkillSummary:
    source_ref: str  # "{source}/{slug}"
    name: str
    source: str
    installs: int
    source_url: str


@dataclass(frozen=True)
class StoreSkillDetail:
    summary: StoreSkillSummary
    files: list[dict[str, Any]] = field(default_factory=list)  # [{path, content}]


class SkillsShClient:
    """技能市场只读 client；`http_client` 可注入便于测试。"""

    def __init__(
        self,
        http_client: httpx.Client | None = None,
        *,
        api_key_provider: Callable[[], str | None] | None = None,
    ):
        self._http = http_client
        self._api_key_provider = api_key_provider

    # -- Public API -----------------------------------------------------------

    def search(self, query: str, *, limit: int = 30) -> list[StoreSkillSummary]:
        query = (query or "").strip()
        if not query:
            return self.curated(limit=limit)
        payload = self._get_json("/skills/search", params={"q": query, "limit": limit})
        return self._parse_summaries(payload)

    def curated(self, *, limit: int = 30) -> list[StoreSkillSummary]:
        payload = self._get_json("/skills", params={"limit": limit})
        return self._parse_summaries(payload)

    def detail(self, source_ref: str) -> StoreSkillDetail:
        source_ref = source_ref.strip().strip("/")
        payload = self._get_json(f"/skills/{source_ref}", not_found_ok=True)
        if payload is None:
            raise SkillsShNotFoundError(source_ref)
        summary = self._parse_summary(payload, fallback_ref=source_ref)
        raw_files = payload.get("files") or []
        files = [
            {"path": str(item.get("path") or ""), "content": self._file_content(item)}
            for item in raw_files
            if isinstance(item, dict) and item.get("path")
        ]
        return StoreSkillDetail(summary=summary, files=files)

    def audit(self, source_ref: str) -> dict[str, Any]:
        """审计结果；任何失败（含需认证）降级为 unavailable，不抛。"""
        try:
            payload = self._get_json(
                f"/skills/audit/{source_ref.strip().strip('/')}", not_found_ok=True
            )
            if isinstance(payload, dict) and payload:
                return {"status": "available", "result": payload}
        except SkillsShUnavailableError:
            pass
        except Exception:
            logger.debug("skills.sh audit lookup failed for %s", source_ref, exc_info=True)
        return {"status": "unavailable"}

    # -- Internal -------------------------------------------------------------

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        not_found_ok: bool = False,
    ) -> Any:
        headers = self._auth_headers()
        try:
            if self._http is not None:
                response = self._http.get(f"{_BASE_URL}{path}", params=params, headers=headers)
            else:
                with httpx.Client(timeout=_TIMEOUT_SECONDS, follow_redirects=True) as client:
                    response = client.get(f"{_BASE_URL}{path}", params=params, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("skills.sh request failed: %s %s", path, exc)
            raise SkillsShUnavailableError() from exc

        if response.status_code == 404 and not_found_ok:
            return None
        if response.status_code == 401:
            raise SkillsShAuthenticationError(AUTH_INVALID_MESSAGE)
        if response.status_code >= 500:
            raise SkillsShUnavailableError()
        if response.status_code == 429:
            raise SkillsShUnavailableError("技能市场请求过于频繁，请稍后重试。")
        if response.status_code >= 400:
            raise SkillsShUnavailableError()
        try:
            return response.json()
        except ValueError as exc:
            raise SkillsShUnavailableError() from exc

    def _auth_headers(self) -> dict[str, str]:
        token = self._read_api_key()
        if not token:
            raise SkillsShAuthenticationError(AUTH_REQUIRED_MESSAGE)
        return {"Authorization": f"Bearer {token}"}

    def _read_api_key(self) -> str | None:
        if self._api_key_provider is not None:
            value = self._api_key_provider()
        else:
            from src.data.unified_config import get_unified_config

            value = get_unified_config().get_skill_store_skills_sh_api_key()
        if not isinstance(value, str):
            return None
        return value.strip() or None

    def _parse_summaries(self, payload: Any) -> list[StoreSkillSummary]:
        items = []
        raw_items = payload.get("skills") if isinstance(payload, dict) else None
        if raw_items is None and isinstance(payload, dict):
            raw_items = payload.get("items")
        if raw_items is None and isinstance(payload, list):
            raw_items = payload
        for raw in raw_items or []:
            if isinstance(raw, dict):
                try:
                    items.append(self._parse_summary(raw))
                except Exception:
                    logger.debug("skip unparsable skills.sh item", exc_info=True)
        return items

    @staticmethod
    def _parse_summary(raw: dict[str, Any], *, fallback_ref: str = "") -> StoreSkillSummary:
        source_ref = str(raw.get("id") or fallback_ref).strip().strip("/")
        if not source_ref:
            raise ValueError("skills.sh item missing id")
        name = str(raw.get("name") or raw.get("slug") or source_ref.rsplit("/", 1)[-1])
        source = str(raw.get("source") or source_ref.rsplit("/", 1)[0])
        installs_raw = raw.get("installs")
        installs = int(installs_raw) if isinstance(installs_raw, (int, float)) else 0
        source_url = str(
            raw.get("url") or raw.get("installUrl") or f"https://skills.sh/{source_ref}"
        )
        return StoreSkillSummary(
            source_ref=source_ref,
            name=name,
            source=source,
            installs=installs,
            source_url=source_url,
        )

    @staticmethod
    def _file_content(raw: dict[str, Any]) -> str:
        content = raw.get("content")
        if content is None:
            content = raw.get("contents")
        return str(content or "")

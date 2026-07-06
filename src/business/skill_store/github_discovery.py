"""GitHub 直装发现与取数（029 D3 / US2）。

匿名 REST API：发现仓库根目录 SKILL.md 与 skills/*/SKILL.md（一层枚举），
按发现路径拉取技能目录全部文本文件。限额/不可达分类为用户可读错误。
source_ref 形态：``owner/repo``（根技能）或 ``owner/repo/skills/<name>``。
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any

import httpx

from src.business.skill_store.skills_sh_client import (
    StoreSkillDetail,
    StoreSkillSummary,
)

logger = logging.getLogger(__name__)

_API = "https://api.github.com"
_TIMEOUT_SECONDS = 10.0

_REPO_PATTERN = re.compile(
    r"^(?:https?://github\.com/)?(?P<owner>[\w.\-]+)/(?P<repo>[\w.\-]+?)(?:\.git)?/?$"
)


class GithubRepoInputError(ValueError):
    """输入解析不出 owner/repo。"""


class GithubUnavailableError(RuntimeError):
    """GitHub 不可达/限额耗尽——消息面向用户。"""


class GithubSkillNotFoundError(KeyError):
    """指定 source_ref 下没有 SKILL.md。"""


def parse_repo_input(raw: str) -> tuple[str, str]:
    matched = _REPO_PATTERN.match((raw or "").strip())
    if not matched:
        raise GithubRepoInputError("请输入 owner/repo 或完整 GitHub 仓库链接")
    return matched.group("owner"), matched.group("repo")


class GithubFetcher:
    """匿名 GitHub 取数；`http_client` 可注入便于测试。"""

    def __init__(self, http_client: httpx.Client | None = None):
        self._http = http_client

    # -- Discover ---------------------------------------------------------------

    def discover(self, repo_input: str) -> list[dict[str, str]]:
        """发现仓库中的技能；返回 [{sourceRef, name, path}]，无匹配返回 []。"""
        owner, repo = parse_repo_input(repo_input)
        found: list[dict[str, str]] = []

        root_listing = self._get_json(f"/repos/{owner}/{repo}/contents/")
        if root_listing is None:
            return []
        root_names = {
            str(item.get("name")): item for item in root_listing if isinstance(item, dict)
        }
        if "SKILL.md" in root_names:
            found.append({"sourceRef": f"{owner}/{repo}", "name": repo, "path": "SKILL.md"})
        skills_dir = root_names.get("skills")
        if skills_dir is not None and skills_dir.get("type") == "dir":
            sub_listing = self._get_json(f"/repos/{owner}/{repo}/contents/skills") or []
            for item in sub_listing:
                if not isinstance(item, dict) or item.get("type") != "dir":
                    continue
                name = str(item.get("name") or "")
                inner = self._get_json(f"/repos/{owner}/{repo}/contents/skills/{name}") or []
                if any(isinstance(f, dict) and f.get("name") == "SKILL.md" for f in inner):
                    found.append(
                        {
                            "sourceRef": f"{owner}/{repo}/skills/{name}",
                            "name": name,
                            "path": f"skills/{name}/SKILL.md",
                        }
                    )
        return found

    # -- Detail（供 install_service 复用统一安装管线） ----------------------------

    def fetch_detail(self, source_ref: str) -> StoreSkillDetail:
        owner, repo, subdir = self._split_source_ref(source_ref)
        base_path = f"{subdir}/" if subdir else ""
        listing = self._get_json(f"/repos/{owner}/{repo}/contents/{subdir}")
        if listing is None:
            raise GithubSkillNotFoundError(source_ref)
        files = self._collect_files(owner, repo, listing, prefix="")
        if not any(f["path"].split("/")[-1] == "SKILL.md" for f in files):
            raise GithubSkillNotFoundError(source_ref)
        name = subdir.rsplit("/", 1)[-1] if subdir else repo
        summary = StoreSkillSummary(
            source_ref=source_ref,
            name=name,
            source=f"{owner}/{repo}",
            installs=0,
            source_url=f"https://github.com/{owner}/{repo}"
            + (f"/tree/HEAD/{subdir}" if subdir else ""),
        )
        del base_path
        return StoreSkillDetail(summary=summary, files=files)

    # -- Internal -----------------------------------------------------------------

    @staticmethod
    def _split_source_ref(source_ref: str) -> tuple[str, str, str]:
        parts = (source_ref or "").strip().strip("/").split("/")
        if len(parts) < 2:
            raise GithubRepoInputError("请输入 owner/repo 或完整 GitHub 仓库链接")
        owner, repo = parts[0], parts[1]
        subdir = "/".join(parts[2:])
        return owner, repo, subdir

    def _collect_files(
        self,
        owner: str,
        repo: str,
        listing: list[Any],
        *,
        prefix: str,
        depth: int = 0,
    ) -> list[dict[str, str]]:
        # 深度限制防病态嵌套；文件数量/大小上限由 file_store 统一校验
        if depth > 3:
            return []
        files: list[dict[str, str]] = []
        for item in listing:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            item_path = f"{prefix}{name}"
            if item.get("type") == "file":
                content = self._fetch_file_content(item)
                if content is not None:
                    files.append({"path": item_path, "content": content})
            elif item.get("type") == "dir":
                sub_url = str(item.get("url") or "")
                sub_listing = self._get_json_absolute(sub_url) or []
                files.extend(
                    self._collect_files(
                        owner, repo, sub_listing, prefix=f"{item_path}/", depth=depth + 1
                    )
                )
        return files

    def _fetch_file_content(self, item: dict[str, Any]) -> str | None:
        """取文件文本；二进制（UTF-8 解码失败）返回 None 跳过。"""
        payload = self._get_json_absolute(str(item.get("url") or ""))
        if not isinstance(payload, dict):
            return None
        raw = payload.get("content")
        if not raw:
            return ""
        try:
            return base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            logger.debug("skip binary file %s", item.get("path"))
            return None

    def _get_json(self, path: str) -> Any:
        return self._get_json_absolute(f"{_API}{path}")

    def _get_json_absolute(self, url: str) -> Any:
        if not url:
            return None
        try:
            if self._http is not None:
                response = self._http.get(url)
            else:
                with httpx.Client(
                    timeout=_TIMEOUT_SECONDS,
                    follow_redirects=True,
                    headers={"Accept": "application/vnd.github+json"},
                ) as client:
                    response = client.get(url)
        except httpx.HTTPError as exc:
            raise GithubUnavailableError("GitHub 暂时无法访问，请稍后重试。") from exc
        if response.status_code == 404:
            return None
        if response.status_code in (403, 429):
            raise GithubUnavailableError("GitHub 匿名访问额度已用尽，请约一小时后重试。")
        if response.status_code >= 400:
            raise GithubUnavailableError("GitHub 暂时无法访问，请稍后重试。")
        try:
            return response.json()
        except ValueError as exc:
            raise GithubUnavailableError("GitHub 返回了无法解析的内容。") from exc

"""Thin wrapper around the official `npx skills` CLI for read-only discovery."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Protocol


class SkillsCliUnavailableError(RuntimeError):
    """The skills CLI is unavailable or failed in a user-actionable way."""


@dataclass(frozen=True)
class CliSkillSearchResult:
    source_ref: str
    name: str
    source: str
    installs: int
    source_url: str


class _Runner(Protocol):
    def __call__(
        self,
        args: list[str],
        *,
        timeout: float,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_RESULT_RE = re.compile(
    r"^(?P<source>[\w.\-]+/[\w.\-]+)@(?P<skill>[\w.\-]+)\s+"
    r"(?P<installs>[\d.]+[KMB]?)\s+installs\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https://skills\.sh/\S+")


def search_skills_with_cli(
    query: str,
    *,
    limit: int = 30,
    timeout_seconds: float = 45.0,
    runner: _Runner | None = None,
) -> list[CliSkillSearchResult]:
    """Search skills.sh via the official CLI and parse its non-interactive output."""
    normalized_query = " ".join(str(query or "").split())
    if not normalized_query:
        return []
    npx = _find_npx()
    command = [npx, "--yes", "skills", "find", *normalized_query.split()]
    env = {
        **os.environ,
        "CI": "1",
        "NO_COLOR": "1",
        "FORCE_COLOR": "0",
        "TERM": "dumb",
    }
    run = runner or _run_process
    try:
        completed = run(command, timeout=timeout_seconds, env=env)
    except subprocess.TimeoutExpired as exc:
        raise SkillsCliUnavailableError("skills CLI 搜索超时，请稍后重试。") from exc
    except OSError as exc:
        raise SkillsCliUnavailableError("无法启动 skills CLI，请确认已安装 Node.js/npm。") from exc
    if completed.returncode != 0:
        text = _strip_ansi((completed.stderr or completed.stdout or "").strip())
        if "could not determine executable" in text.lower():
            message = "无法启动 skills CLI，请确认 npm 可正常使用。"
        else:
            message = "skills CLI 搜索失败，请稍后重试。"
        raise SkillsCliUnavailableError(message)
    return _parse_find_output(completed.stdout, limit=limit)


def _find_npx() -> str:
    for candidate in ("npx", "npx.cmd"):
        path = shutil.which(candidate)
        if path:
            return path
    raise SkillsCliUnavailableError("未找到 npx，请安装 Node.js/npm 后重试。")


def _run_process(
    args: list[str],
    *,
    timeout: float,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
        check=False,
    )


def _parse_find_output(raw: str, *, limit: int) -> list[CliSkillSearchResult]:
    lines = [_strip_ansi(line).strip() for line in (raw or "").splitlines()]
    results: list[CliSkillSearchResult] = []
    index = 0
    while index < len(lines):
        match = _RESULT_RE.match(lines[index])
        if not match:
            index += 1
            continue
        source = match.group("source")
        skill = match.group("skill")
        url = ""
        for lookahead in lines[index + 1 : index + 3]:
            url_match = _URL_RE.search(lookahead)
            if url_match:
                url = url_match.group(0)
                break
        source_ref = f"{source}@{skill}"
        results.append(
            CliSkillSearchResult(
                source_ref=source_ref,
                name=skill,
                source=source,
                installs=_parse_install_count(match.group("installs")),
                source_url=url or f"https://skills.sh/{source}/{skill}",
            )
        )
        if len(results) >= limit:
            break
        index += 1
    return results


def _strip_ansi(value: str) -> str:
    return _ANSI_RE.sub("", value or "")


def _parse_install_count(raw: str) -> int:
    text = (raw or "0").strip().upper()
    multiplier = 1
    if text.endswith("K"):
        multiplier = 1_000
        text = text[:-1]
    elif text.endswith("M"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.endswith("B"):
        multiplier = 1_000_000_000
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return 0

"""GithubFetcher 发现与取数测试（029 T019，mock httpx）。"""

from __future__ import annotations

import base64

import httpx
import pytest

from src.business.skill_store.github_discovery import (
    GithubFetcher,
    GithubRepoInputError,
    GithubUnavailableError,
    parse_repo_input,
)


def _client(routes: dict[str, object], status_overrides: dict[str, int] | None = None):
    status_overrides = status_overrides or {}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for key, payload in routes.items():
            if url.endswith(key) or url.rstrip("/").endswith(key.rstrip("/")):
                return httpx.Response(status_overrides.get(key, 200), json=payload)
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class TestParseRepoInput:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("owner/repo", ("owner", "repo")),
            ("https://github.com/owner/repo", ("owner", "repo")),
            ("https://github.com/owner/repo.git", ("owner", "repo")),
            ("https://github.com/owner/repo/", ("owner", "repo")),
        ],
    )
    def test_valid_inputs(self, raw, expected):
        assert parse_repo_input(raw) == expected

    @pytest.mark.parametrize("raw", ["", "just-words", "https://gitlab.com/a/b", "a/b/c/d"])
    def test_invalid_inputs(self, raw):
        with pytest.raises(GithubRepoInputError):
            parse_repo_input(raw)


class TestDiscover:
    def test_discovers_root_and_subdir_skills(self):
        routes = {
            "/repos/o/r/contents/": [
                {"name": "SKILL.md", "type": "file"},
                {"name": "skills", "type": "dir"},
            ],
            "/repos/o/r/contents/skills": [
                {"name": "alpha", "type": "dir"},
                {"name": "beta", "type": "dir"},
            ],
            "/repos/o/r/contents/skills/alpha": [{"name": "SKILL.md", "type": "file"}],
            "/repos/o/r/contents/skills/beta": [{"name": "README.md", "type": "file"}],
        }
        fetcher = GithubFetcher(http_client=_client(routes))
        found = fetcher.discover("o/r")
        refs = {item["sourceRef"] for item in found}
        assert refs == {"o/r", "o/r/skills/alpha"}

    def test_missing_repo_returns_empty(self):
        fetcher = GithubFetcher(http_client=_client({}))
        assert fetcher.discover("ghost/none") == []

    def test_rate_limit_classified(self):
        routes = {"/repos/o/r/contents/": {"message": "rate limited"}}
        fetcher = GithubFetcher(
            http_client=_client(routes, status_overrides={"/repos/o/r/contents/": 403})
        )
        with pytest.raises(GithubUnavailableError) as exc_info:
            fetcher.discover("o/r")
        assert "额度" in str(exc_info.value)


class TestFetchDetail:
    def test_fetches_files_and_decodes_content(self):
        skill_md = "---\nname: gh-skill\n---\nbody"
        routes = {
            "/repos/o/r/contents/": [
                {
                    "name": "SKILL.md",
                    "type": "file",
                    "url": "https://api.github.com/file/skill",
                },
            ],
            "/file/skill": {"content": _b64(skill_md)},
        }
        fetcher = GithubFetcher(http_client=_client(routes))
        detail = fetcher.fetch_detail("o/r")
        assert detail.summary.source_ref == "o/r"
        assert detail.files[0]["path"] == "SKILL.md"
        assert detail.files[0]["content"] == skill_md

    def test_binary_files_skipped(self):
        routes = {
            "/repos/o/r/contents/": [
                {"name": "SKILL.md", "type": "file", "url": "https://api.github.com/f/1"},
                {"name": "logo.png", "type": "file", "url": "https://api.github.com/f/2"},
            ],
            "/f/1": {"content": _b64("---\nname: s\n---\nbody")},
            "/f/2": {"content": base64.b64encode(b"\x89PNG\x00\xff").decode("ascii")},
        }
        fetcher = GithubFetcher(http_client=_client(routes))
        detail = fetcher.fetch_detail("o/r")
        assert [f["path"] for f in detail.files] == ["SKILL.md"]

    def test_no_skill_md_raises_not_found(self):
        routes = {
            "/repos/o/r/contents/": [
                {"name": "README.md", "type": "file", "url": "https://api.github.com/f/3"},
            ],
            "/f/3": {"content": _b64("readme")},
        }
        fetcher = GithubFetcher(http_client=_client(routes))
        import pytest as _pytest

        with _pytest.raises(KeyError):
            fetcher.fetch_detail("o/r")

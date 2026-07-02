from __future__ import annotations

import json
import time

import pytest

from src.business.agents.tools.semantic_summary import (
    build_deterministic_preview,
    clear_semantic_summary_cache_for_tests,
    extract_deterministic_facts,
    normalize_tool_output,
    resolve_extraction_goal,
    select_semantic_input,
    summarize_tool_output,
)


def _summary_payload(label: str = "ok") -> str:
    return json.dumps(
        {
            "overview": label,
            "keyFindings": [f"finding:{label}"],
            "errors": [],
            "importantData": ["count=3"],
            "nextActions": ["continue"],
            "extractionGoal": "",
            "coverage": "complete",
            "mode": "single",
            "advisory": True,
        }
    )


class FakeConfig:
    def __init__(self, **overrides):
        self.values = {
            "enabled": True,
            "provider": "openai",
            "model": "summary-model",
            "base_url": "",
            "temperature": 0.2,
            "trigger_chars": 20_000,
            "max_input_chars": 120_000,
            "chunk_chars": 20_000,
            "max_map_chunks": 6,
            "map_concurrency": 3,
            "total_timeout_seconds": 12.0,
            "map_max_tokens": 500,
            "reduce_max_tokens": 900,
            "summary_max_chars": 4000,
            "api_key": "sk-summary-secret",
        }
        self.values.update(overrides)

    def __getattr__(self, name):
        prefix = "get_agent_tools_output_semantic_summary_"
        if name == "get_tool_output_summary_api_key":
            return lambda: self.values["api_key"]
        if name.startswith(prefix):
            key = name[len(prefix) :]
            return lambda: self.values[key]
        raise AttributeError(name)


class FakeClient:
    def __init__(self, responder, calls):
        self._responder = responder
        self._calls = calls

    def chat(self, prompt: str) -> str:
        self._calls.append(prompt)
        return self._responder(prompt)


@pytest.fixture(autouse=True)
def _clear_summary_cache():
    clear_semantic_summary_cache_for_tests()
    yield
    clear_semantic_summary_cache_for_tests()


def test_deterministic_preview_and_facts_keep_errors_from_head_middle_and_tail():
    text = (
        "ERROR head failure\n"
        + ("normal\n" * 500)
        + "WARNING middle warning\n"
        + ("normal\n" * 500)
        + "FAILED tail failure\n"
    )
    preview = build_deterministic_preview(text, max_chars=2400, tool_name="exec")
    facts = extract_deterministic_facts(
        {
            "outcome": "timeout",
            "payload": {"status": "failed", "exitCode": 7, "count": 3},
            "error": {"code": "command_timeout", "message": "timed out"},
            "limits": {"truncated": True},
        }
    )

    assert "head failure" in preview
    assert "middle warning" in preview
    assert "tail failure" in preview
    assert facts["outcome"] == "timeout"
    assert facts["exitCode"] == 7
    assert facts["errorCode"] == "command_timeout"
    assert facts["truncated"] is True


def test_over_budget_selection_uses_head_errors_uniform_and_tail():
    text = "HEAD\n" + ("a" * 30_000) + "\nERROR sentinel\n" + ("b" * 30_000) + "\nTAIL"

    selected, coverage = select_semantic_input(text, max_chars=20_000)

    assert len(selected) <= 20_000
    assert "HEAD" in selected
    assert "ERROR sentinel" in selected
    assert "TAIL" in selected
    assert coverage == "sampled"


def test_map_budget_preserves_tail_when_advanced_limits_do_not_align():
    calls: list[str] = []
    config = FakeConfig(
        max_input_chars=20_000,
        chunk_chars=1000,
        max_map_chunks=2,
    )

    summary = summarize_tool_output(
        tool_name="read_file",
        tool_args={},
        source_text="HEAD\n" + ("x" * 10_000) + "\nERROR middle\n" + ("y" * 10_000) + "\nTAIL",
        source_obj={},
        config=config,
        client_factory=lambda **_: FakeClient(lambda _prompt: _summary_payload("bounded"), calls),
    )

    assert summary is not None
    map_prompts = [prompt for prompt in calls if "[MAP " in prompt]
    assert len(map_prompts) == 2
    assert "HEAD" in "".join(map_prompts)
    assert "ERROR middle" in "".join(map_prompts)
    assert "TAIL" in "".join(map_prompts)


def test_extraction_goal_prefers_explicit_and_supports_web_and_custom_args():
    assert (
        resolve_extraction_goal("exec", {"extractionGoal": " find failing tests "})
        == "find failing tests"
    )
    assert resolve_extraction_goal("web_fetch", {"prompt": "extract pricing"}) == "extract pricing"
    assert resolve_extraction_goal("custom_tool", {"query": "quarterly revenue"}) == (
        "quarterly revenue"
    )
    assert len(resolve_extraction_goal("exec", {"extractionGoal": "x" * 2000})) == 1000


def test_single_summary_redacts_prompt_and_validates_fixed_shape():
    calls: list[str] = []
    config = FakeConfig(chunk_chars=50_000)

    summary = summarize_tool_output(
        tool_name="exec",
        tool_args={"extractionGoal": "find token=goal-secret failures"},
        source_text="token=raw-secret\nERROR build failed",
        source_obj={"payload": {"stderr": "ERROR build failed"}},
        config=config,
        client_factory=lambda **_: FakeClient(lambda _prompt: _summary_payload("single"), calls),
    )

    assert summary is not None
    assert summary["overview"] == "single"
    assert summary["mode"] == "single"
    assert summary["advisory"] is True
    assert summary["extractionGoal"] == "find token=*** failures"
    assert len(calls) == 1
    assert "raw-secret" not in calls[0]
    assert "goal-secret" not in calls[0]
    assert "untrusted data" in calls[0].lower()


def test_semantic_summary_cache_reuses_same_content_goal_and_config():
    calls: list[str] = []
    config = FakeConfig(chunk_chars=50_000)

    first = summarize_tool_output(
        tool_name="web_fetch",
        tool_args={"prompt": "repository stars"},
        source_text="# Trending\n\n## acme/project\n\n3,210 stars.",
        source_obj={},
        config=config,
        client_factory=lambda **_: FakeClient(lambda _prompt: _summary_payload("cached"), calls),
    )
    second = summarize_tool_output(
        tool_name="web_fetch",
        tool_args={"prompt": "repository stars"},
        source_text="# Trending\n\n## acme/project\n\n3,210 stars.",
        source_obj={},
        config=config,
        client_factory=lambda **_: FakeClient(
            lambda _prompt: (_ for _ in ()).throw(AssertionError("cache miss")),
            calls,
        ),
    )

    assert first == second
    assert first is not second
    assert len(calls) == 1


def test_semantic_summary_cache_is_scoped_by_extraction_goal():
    calls: list[str] = []
    config = FakeConfig(chunk_chars=50_000)

    stars = summarize_tool_output(
        tool_name="web_fetch",
        tool_args={"prompt": "repository stars"},
        source_text="# Trending\n\n## acme/project\n\n3,210 stars.",
        source_obj={},
        config=config,
        client_factory=lambda **_: FakeClient(lambda _prompt: _summary_payload("stars"), calls),
    )
    forks = summarize_tool_output(
        tool_name="web_fetch",
        tool_args={"prompt": "repository forks"},
        source_text="# Trending\n\n## acme/project\n\n3,210 stars.",
        source_obj={},
        config=config,
        client_factory=lambda **_: FakeClient(lambda _prompt: _summary_payload("forks"), calls),
    )

    assert stars["overview"] == "stars"
    assert forks["overview"] == "forks"
    assert len(calls) == 2


def test_opaque_registered_secret_is_removed_before_and_after_provider_call():
    calls: list[str] = []
    secret = "opaque-provider-credential-123"

    summary = summarize_tool_output(
        tool_name="exec",
        tool_args={"extractionGoal": f"find {secret}"},
        source_text=f"raw value {secret}",
        source_obj={},
        config=FakeConfig(api_key=secret),
        client_factory=lambda **_: FakeClient(lambda _prompt: _summary_payload(secret), calls),
    )

    assert summary is not None
    assert secret not in calls[0]
    assert secret not in json.dumps(summary, ensure_ascii=False)


def test_map_reduce_uses_successful_maps_after_partial_failure():
    calls: list[str] = []
    config = FakeConfig(chunk_chars=1000, max_input_chars=6000, max_map_chunks=6)

    def respond(prompt: str) -> str:
        if "[MAP 2/" in prompt:
            raise RuntimeError("map unavailable")
        if "[REDUCE]" in prompt:
            return _summary_payload("reduced")
        return _summary_payload("mapped")

    summary = summarize_tool_output(
        tool_name="read_file",
        tool_args={"extractionGoal": "find API changes"},
        source_text=("line\n" * 900),
        source_obj={"payload": {"content": "line"}},
        config=config,
        client_factory=lambda **_: FakeClient(respond, calls),
    )

    assert summary is not None
    assert summary["overview"] == "reduced"
    assert summary["mode"] == "map_reduce"
    assert any("[REDUCE]" in prompt for prompt in calls)


def test_invalid_json_reduce_failure_and_timeout_return_none():
    invalid = summarize_tool_output(
        tool_name="exec",
        tool_args={},
        source_text="x" * 100,
        source_obj={},
        config=FakeConfig(),
        client_factory=lambda **_: FakeClient(lambda _prompt: "not-json", []),
    )

    reduce_failed = summarize_tool_output(
        tool_name="exec",
        tool_args={},
        source_text="x" * 5000,
        source_obj={},
        config=FakeConfig(chunk_chars=1000),
        client_factory=lambda **_: FakeClient(
            lambda prompt: (
                (_ for _ in ()).throw(RuntimeError("reduce failed"))
                if "[REDUCE]" in prompt
                else _summary_payload("map")
            ),
            [],
        ),
    )

    started = time.monotonic()
    timed_out = summarize_tool_output(
        tool_name="exec",
        tool_args={},
        source_text="x" * 100,
        source_obj={},
        config=FakeConfig(total_timeout_seconds=0.05),
        client_factory=lambda **_: FakeClient(
            lambda _prompt: (time.sleep(0.25), _summary_payload("late"))[1],
            [],
        ),
    )

    assert invalid is None
    assert reduce_failed is None
    assert timed_out is None
    assert time.monotonic() - started < 0.2


def test_json_response_must_be_the_entire_document_but_may_use_one_fence():
    calls: list[str] = []
    wrapped = summarize_tool_output(
        tool_name="exec",
        tool_args={},
        source_text="output",
        source_obj={},
        config=FakeConfig(),
        client_factory=lambda **_: FakeClient(
            lambda _prompt: f"prefix {_summary_payload('wrapped')} suffix",
            calls,
        ),
    )
    fenced = summarize_tool_output(
        tool_name="exec",
        tool_args={},
        source_text="output",
        source_obj={},
        config=FakeConfig(),
        client_factory=lambda **_: FakeClient(
            lambda _prompt: f"```json\n{_summary_payload('fenced')}\n```",
            calls,
        ),
    )

    assert wrapped is None
    assert fenced is not None
    assert fenced["overview"] == "fenced"


def test_unconfigured_summary_model_skips_provider_call():
    calls: list[str] = []

    summary = summarize_tool_output(
        tool_name="web_fetch",
        tool_args={"prompt": "repository stars"},
        source_text="# Trending\n\n## acme/project\n\n3,210 stars",
        source_obj=None,
        config=FakeConfig(model=""),
        client_factory=lambda **_: FakeClient(lambda _prompt: _summary_payload("unused"), calls),
    )

    assert summary is None
    assert calls == []


def test_invalid_compatible_endpoint_skips_provider_call():
    calls: list[dict] = []

    for base_url in (
        "not-a-url",
        "ftp://compatible.example/v1",
        "https://user:password@compatible.example/v1",
        "https://compatible example/v1",
    ):
        summary = summarize_tool_output(
            tool_name="exec",
            tool_args={},
            source_text="output",
            source_obj={},
            config=FakeConfig(provider="openai-compatible", base_url=base_url),
            client_factory=lambda **kwargs: calls.append(kwargs),
        )

        assert summary is None

    assert calls == []


def test_valid_compatible_endpoint_calls_provider():
    calls: list[str] = []

    summary = summarize_tool_output(
        tool_name="exec",
        tool_args={},
        source_text="output",
        source_obj={},
        config=FakeConfig(
            provider="openai-compatible",
            base_url="https://compatible.example/v1",
        ),
        client_factory=lambda **_: FakeClient(
            lambda _prompt: _summary_payload("compatible"),
            calls,
        ),
    )

    assert summary is not None
    assert summary["overview"] == "compatible"
    assert len(calls) == 1


def test_summary_shape_respects_configured_character_cap():
    calls: list[str] = []
    oversized = json.dumps(
        {
            "overview": "o" * 2000,
            "keyFindings": ["f" * 600] * 12,
            "errors": ["e" * 600] * 12,
            "importantData": ["d" * 600] * 12,
            "nextActions": ["a" * 600] * 12,
        }
    )

    summary = summarize_tool_output(
        tool_name="exec",
        tool_args={"extractionGoal": "g" * 1000},
        source_text="result",
        source_obj={},
        config=FakeConfig(summary_max_chars=500),
        client_factory=lambda **_: FakeClient(lambda _prompt: oversized, calls),
    )

    assert summary is not None
    assert len(json.dumps(summary, ensure_ascii=False)) <= 500


def test_web_fetch_normalization_extracts_body_and_transport_facts():
    markdown = "# Trending\n\n## owner/project\n\nUseful repository with 12,345 stars."
    normalized = normalize_tool_output(
        "web_fetch",
        json.dumps(
            {
                "success": True,
                "url": "https://example.test/trending",
                "content": markdown,
                "truncated": True,
                "status": 200,
                "bytes": 98765,
                "content_type": "text/html; charset=utf-8",
                "result": "legacy prompt preview",
            },
            ensure_ascii=False,
        ),
        None,
    )

    assert normalized.text == markdown
    assert normalized.content_type == "markdown"
    assert normalized.facts == {
        "url": "https://example.test/trending",
        "httpStatus": 200,
        "bytes": 98765,
        "truncated": True,
        "contentType": "text/html; charset=utf-8",
    }


def test_web_fetch_preview_scores_trending_content_and_ignores_error_words_in_links():
    markdown = """
# GitHub

- [Pull requests](/pulls)
- [Issues](/issues)
- [Python traceback guide](/topics/python-traceback)
- [Sign in](/login)

## [acme/fast-parser](https://github.com/acme/fast-parser)

Fast repository parser for production workloads.

Python · 18,420 stars today · 932 forks

## [contoso/data-grid](https://github.com/contoso/data-grid)

High performance repository for large data tables.

TypeScript · 9,870 stars today · 411 forks

Cookie preferences and privacy footer. Sign in to continue.
""".strip()

    preview = build_deterministic_preview(
        markdown,
        700,
        tool_name="web_fetch",
        extraction_goal="repository stars",
        content_type="markdown",
    )

    assert "acme/fast-parser" in preview
    assert "18,420 stars" in preview
    assert "contoso/data-grid" in preview
    assert "Python traceback guide" not in preview
    assert "Cookie preferences" not in preview
    assert "Sign in to continue" not in preview


def test_web_fetch_prompt_terms_raise_matching_markdown_blocks():
    markdown = "\n\n".join(
        [
            "# Weekly report",
            "General announcements and community updates for this week.",
            (
                "## Download metrics\n"
                "The package registry recorded 99,999 downloads across platforms "
                "during the latest reporting window, with detailed regional growth."
            ),
            "## Release notes\nVersion 4.2 improves rendering and accessibility.",
            "## Repository metrics\nThe repository gained 7,654 stars and 321 forks.",
            "## Events\nConference schedule and speaker registration details.",
        ]
    )

    untargeted = build_deterministic_preview(
        markdown,
        100,
        tool_name="web_fetch",
        content_type="markdown",
    )
    targeted = build_deterministic_preview(
        markdown,
        100,
        tool_name="web_fetch",
        extraction_goal="repository stars",
        content_type="markdown",
    )

    assert "7,654 stars" in targeted
    assert "7,654 stars" not in untargeted


def test_web_fetch_semantic_prompt_uses_normalized_body_without_json_shell():
    calls: list[str] = []
    source = json.dumps(
        {
            "success": True,
            "url": "https://example.test/trending",
            "content": "# Trending\n\n## acme/project\n\nRepository has 3,210 stars.",
            "status": 200,
            "bytes": 1200,
            "content_type": "text/html",
        }
    )

    summary = summarize_tool_output(
        tool_name="web_fetch",
        tool_args={"prompt": "repository stars"},
        source_text=source,
        source_obj=None,
        config=FakeConfig(),
        client_factory=lambda **_: FakeClient(lambda _prompt: _summary_payload("web"), calls),
    )

    assert summary is not None
    assert "acme/project" in calls[0]
    assert '\\"success\\"' not in calls[0]
    assert '"success": true' not in calls[0]

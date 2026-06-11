import json
from pathlib import Path

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType, ResultType, ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema
from src.business.agents.tools import builtin_general_tools as general_tools
from src.business.agents.tools.builtin_contracts import ERROR_CODES, error_json, success_json
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from tests.conftest import MockLLMClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _config() -> AgentConfig:
    return AgentConfig(
        agent_type=AgentType.PM,
        system_prompt="test",
        max_iterations=5,
    )


def _tool_results(loop: AgentLoop, session_id: str):
    ctx = loop._get_context_manager(session_id)
    return [m for m in ctx._msg_repo.get_context(session_id) if m.role == "tool"]


def _run(tool_calls, tools, mock_config, session_id):
    loop = AgentLoop(
        _config(),
        MockLLMClient(
            [
                LLMResponse(content=None, tool_calls=tool_calls),
                LLMResponse(content="done", tool_calls=[]),
            ]
        ),
        mock_config,
    )
    result = loop.run(session_id=session_id, user_input="go", tools=tools)
    return loop, result


def test_common_envelope_contract_schema_and_error_catalog_are_stable():
    schema = json.loads(
        (
            PROJECT_ROOT
            / "specs"
            / "015-agent-builtin-tools-upgrade"
            / "contracts"
            / "tool-result-envelope.schema.json"
        ).read_text(encoding="utf-8")
    )
    result = json.loads(
        error_json(
            "read_file",
            "baseline_required",
            "baseline required",
            outcome="rejected",
        )
    )

    assert schema["required"] == ["schemaVersion", "tool", "outcome", "payload", "createdAt"]
    assert result["schemaVersion"] == 1
    assert result["error"]["code"] == "baseline_required"
    for code in [
        "path_outside_workspace",
        "baseline_required",
        "baseline_stale",
        "command_timeout",
        "output_reference_expired",
    ]:
        assert code in ERROR_CODES


def test_builtin_read_file_agent_loop_persists_one_envelope_result(
    tmp_path, monkeypatch, mock_config
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "demo.txt").write_text("hello\n", encoding="utf-8")
    read_tool = next(td for td in general_tools.BUILTIN_GENERAL_TOOLS if td.name == "read_file")

    loop, result = _run(
        [ToolCallInfo(id="call-1", name="read_file", args={"path": "demo.txt"})],
        [read_tool],
        mock_config,
        "builtin-read-one-result",
    )
    tool_results = _tool_results(loop, "builtin-read-one-result")
    payload = json.loads(tool_results[0].content)

    assert result.result_type == ResultType.COMPLETED
    assert len(tool_results) == 1
    assert payload["schemaVersion"] == 1
    assert payload["tool"] == "read_file"
    assert payload["outcome"] == "success"


def test_builtin_read_file_missing_path_keeps_stable_error_code(tmp_path, monkeypatch, mock_config):
    monkeypatch.chdir(tmp_path)
    read_tool = next(td for td in general_tools.BUILTIN_GENERAL_TOOLS if td.name == "read_file")

    loop, _ = _run(
        [ToolCallInfo(id="call-1", name="read_file", args={"path": "missing.txt"})],
        [read_tool],
        mock_config,
        "builtin-read-missing-result",
    )
    payload = json.loads(_tool_results(loop, "builtin-read-missing-result")[0].content)

    assert payload["schemaVersion"] == 1
    assert payload["tool"] == "read_file"
    assert payload["outcome"] == "rejected"
    assert payload["error"]["code"] == "path_not_found"


def test_builtin_pre_hook_rejection_still_persists_one_envelope_result(
    tmp_path, monkeypatch, mock_config
):
    monkeypatch.chdir(tmp_path)
    write_tool = next(td for td in general_tools.BUILTIN_GENERAL_TOOLS if td.name == "write_file")
    monkeypatch.setattr(general_tools, "_ask_user_confirm", lambda message, **kwargs: False)

    loop, _ = _run(
        [
            ToolCallInfo(
                id="call-1",
                name="write_file",
                args={"path": "new.txt", "content": "no"},
            )
        ],
        [write_tool],
        mock_config,
        "builtin-reject-one-result",
    )
    tool_results = _tool_results(loop, "builtin-reject-one-result")
    payload = json.loads(tool_results[0].content)

    assert len(tool_results) == 1
    assert payload["schemaVersion"] == 1
    assert payload["error"]["code"] == "permission_denied"
    assert not (tmp_path / "new.txt").exists()


def test_unknown_tool_still_persists_exactly_one_result(mock_config):
    loop, _ = _run(
        [ToolCallInfo(id="call-1", name="missing_tool", args={})],
        [],
        mock_config,
        "builtin-unknown-one-result",
    )

    assert len(_tool_results(loop, "builtin-unknown-one-result")) == 1


def test_oversized_builtin_result_compacts_to_one_result_with_reference(
    tmp_path, monkeypatch, mock_config
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path / "data",
    )
    large_exec = ToolDefinition(
        name="exec",
        schema=make_tool_schema("exec", "large", {}, []),
        handler=lambda: success_json("exec", {"stdout": "x" * 25000}),
    )

    loop, _ = _run(
        [ToolCallInfo(id="call-1", name="exec", args={})],
        [large_exec],
        mock_config,
        "builtin-compact-one-result",
    )
    tool_results = _tool_results(loop, "builtin-compact-one-result")
    payload = json.loads(tool_results[0].content)

    assert len(tool_results) == 1
    assert payload["payload"]["compacted"] is True
    assert payload["references"][0]["referenceId"].startswith("out_")


def test_governance_failure_persists_one_safe_result_without_raw_output(
    tmp_path, monkeypatch, mock_config
):
    monkeypatch.chdir(tmp_path)
    secret = "secret-value-that-must-not-be-persisted"
    large_exec = ToolDefinition(
        name="exec",
        schema=make_tool_schema("exec", "large", {}, []),
        handler=lambda: success_json("exec", {"stdout": secret * 1000}),
    )
    monkeypatch.setattr(
        "src.business.agents.agent_loop.govern_tool_result",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("governance unavailable")),
    )

    loop, _ = _run(
        [ToolCallInfo(id="call-1", name="exec", args={})],
        [large_exec],
        mock_config,
        "builtin-governance-fallback",
    )
    tool_results = _tool_results(loop, "builtin-governance-fallback")
    payload = json.loads(tool_results[0].content)

    assert len(tool_results) == 1
    assert payload["error"]["code"] == "compaction_failed_fallback"
    assert secret not in tool_results[0].content


def test_agent_loop_passes_tool_args_to_governance_once(monkeypatch, mock_config):
    captured = []

    def capture_governance(**kwargs):
        captured.append(kwargs)
        return kwargs["content"]

    monkeypatch.setattr(
        "src.business.agents.agent_loop.govern_tool_result",
        capture_governance,
    )
    tool = ToolDefinition(
        name="custom_tool",
        schema=make_tool_schema(
            "custom_tool",
            "custom",
            {"query": {"type": "string"}},
            ["query"],
        ),
        handler=lambda query: f"result:{query}",
        has_side_effects=False,
    )

    loop, _ = _run(
        [
            ToolCallInfo(
                id="call-1",
                name="custom_tool",
                args={"query": "find regression"},
            )
        ],
        [tool],
        mock_config,
        "governance-tool-args",
    )

    assert len(captured) == 1
    assert captured[0]["tool_args"] == {"query": "find regression"}
    assert len(_tool_results(loop, "governance-tool-args")) == 1


def test_multi_tool_summary_success_and_fallback_keep_one_result_per_call(
    tmp_path, monkeypatch, mock_config
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path / "data",
    )

    def fake_summary(**kwargs):
        if kwargs["tool_args"]["query"] != "summarize":
            return None
        return {
            "overview": "summary",
            "keyFindings": [],
            "errors": [],
            "importantData": [],
            "nextActions": [],
            "extractionGoal": "summarize",
            "coverage": "complete",
            "mode": "single",
            "advisory": True,
        }

    monkeypatch.setattr(
        "src.business.agents.tools.output_governance.summarize_tool_output",
        fake_summary,
    )
    tool = ToolDefinition(
        name="custom_tool",
        schema=make_tool_schema(
            "custom_tool",
            "large custom output",
            {"query": {"type": "string"}},
            ["query"],
        ),
        handler=lambda query: f"{query}\n" + ("x" * 25_000),
        has_side_effects=False,
    )

    loop, _ = _run(
        [
            ToolCallInfo(
                id="call-summary",
                name="custom_tool",
                args={"query": "summarize"},
            ),
            ToolCallInfo(
                id="call-fallback",
                name="custom_tool",
                args={"query": "fallback"},
            ),
        ],
        [tool],
        mock_config,
        "multi-tool-summary-pairing",
    )
    tool_results = _tool_results(loop, "multi-tool-summary-pairing")
    payloads = [json.loads(result.content)["payload"] for result in tool_results]

    assert len(tool_results) == 2
    assert payloads[0]["semanticSummary"]["overview"] == "summary"
    assert "semanticSummary" not in payloads[1]


def test_large_result_secret_stays_out_of_visible_result_activity_and_logs(
    tmp_path, monkeypatch, mock_config, caplog
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path / "data",
    )
    activities = []
    monkeypatch.setattr(
        AgentLoop,
        "_emit_activity",
        lambda _self, _ctx, _kind, **kwargs: activities.append(kwargs),
    )
    secret = "raw-ui-log-secret"
    tool = ToolDefinition(
        name="custom_tool",
        schema=make_tool_schema("custom_tool", "large custom output", {}, []),
        handler=lambda: (f"token={secret}\n" * 2000),
        has_side_effects=False,
    )

    loop, _ = _run(
        [ToolCallInfo(id="call-secret", name="custom_tool", args={})],
        [tool],
        mock_config,
        "large-result-secret-boundary",
    )
    visible_result = _tool_results(loop, "large-result-secret-boundary")[0].content

    assert secret not in visible_result
    assert all(secret not in str(activity.get("text", "")) for activity in activities)
    assert secret not in caplog.text

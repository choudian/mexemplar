import json
from datetime import datetime, timedelta, timezone

from src.business.agents.tools.builtin_contracts import success_json, use_tool_runtime
from src.business.agents.tools.output_governance import (
    cleanup_tool_outputs,
    get_tool_output_health_counters,
    govern_tool_result,
    load_tool_output_handler,
)
from src.data.repos.tool_output_repository import ToolOutputRepository
from src.utils.agent_tool_health import reset_agent_tool_health_for_tests


def _obj(result: str) -> dict:
    return json.loads(result)


def test_output_governance_compacts_large_envelope_and_creates_reference(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path / "data",
    )
    content = success_json("exec", {"stdout": "x" * 100000, "stderr": ""})

    governed = _obj(
        govern_tool_result(
            tool_name="exec",
            tool_call_id="call-1",
            session_id="session-1",
            content=content,
            workspace_root=tmp_path,
        )
    )

    assert governed["payload"]["compacted"] is True
    assert governed["references"][0]["referenceId"].startswith("out_")
    assert len(json.dumps(governed, ensure_ascii=False)) <= 12000
    assert "storage_key" not in json.dumps(governed, ensure_ascii=False).lower()


def test_output_governance_reference_keeps_raw_source_but_visible_paths_are_redacted(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path / "data",
    )
    content = success_json("exec", {"stdout": "token=secret-value\n" + ("x" * 25000)})

    governed = _obj(
        govern_tool_result(
            tool_name="exec",
            tool_call_id="call-1",
            session_id="session-1",
            content=content,
            workspace_root=tmp_path,
        )
    )
    reference_id = governed["references"][0]["referenceId"]
    loaded_blob = ToolOutputRepository().load_authorized_bytes(
        reference_id,
        session_id="session-1",
        workspace_root=tmp_path,
    )
    loaded_visible = _obj(
        load_tool_output_handler(
            reference_id,
            sessionId="session-1",
            workspaceRoot=str(tmp_path),
        )
    )

    assert "secret-value" not in json.dumps(governed, ensure_ascii=False)
    assert loaded_blob is not None
    assert b"secret-value" in loaded_blob.data
    assert "secret-value" not in loaded_visible["payload"]["content"]
    assert "token=***" in loaded_visible["payload"]["content"]


def test_load_tool_output_authorizes_session_workspace_and_redacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    repo = ToolOutputRepository()
    model = repo.create_reference(
        session_id="session-1",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data="token=secret-value\nline2",
        workspace_root=tmp_path,
    )

    loaded = _obj(
        load_tool_output_handler(
            model.reference_id,
            sessionId="session-1",
            workspaceRoot=str(tmp_path),
        )
    )
    denied = _obj(
        load_tool_output_handler(
            model.reference_id,
            sessionId="other-session",
            workspaceRoot=str(tmp_path),
        )
    )
    wrong_workspace = tmp_path / "other-workspace"
    wrong_workspace.mkdir()
    denied_workspace = _obj(
        load_tool_output_handler(
            model.reference_id,
            sessionId="session-1",
            workspaceRoot=str(wrong_workspace),
        )
    )

    assert loaded["outcome"] == "success"
    assert "secret-value" not in loaded["payload"]["content"]
    assert loaded["payload"]["content"].startswith("token=***")
    assert denied["error"]["code"] == "permission_denied"
    assert denied_workspace["error"]["code"] == "output_reference_not_found"
    assert "secret-value" not in json.dumps(denied_workspace, ensure_ascii=False)


def test_load_tool_output_ignores_model_session_override_when_runtime_exists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    model = ToolOutputRepository().create_reference(
        session_id="owner-session",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data="owned",
        workspace_root=tmp_path,
    )

    with use_tool_runtime(
        session_id="other-session",
        tool_call_id="call-2",
        tool_name="load_tool_output",
        workspace_root=tmp_path,
    ):
        denied = _obj(
            load_tool_output_handler(
                model.reference_id,
                sessionId="owner-session",
                workspaceRoot=str(tmp_path),
            )
        )

    assert denied["outcome"] == "rejected"
    assert denied["error"]["code"] == "permission_denied"


def test_load_tool_output_rejects_expired_reference_and_removes_blob(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    repo = ToolOutputRepository()
    model = repo.create_reference(
        session_id="session-1",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data="expired",
        workspace_root=tmp_path,
    )
    blob_path = repo.blob_path(model)
    assert blob_path.exists()
    model.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    repo.session.commit()

    result = _obj(
        load_tool_output_handler(
            model.reference_id,
            sessionId="session-1",
            workspaceRoot=str(tmp_path),
        )
    )

    assert result["outcome"] == "rejected"
    assert result["error"]["code"] == "output_reference_expired"
    assert not blob_path.exists()


def test_retention_cleanup_records_health_counters(tmp_path, monkeypatch):
    reset_agent_tool_health_for_tests()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    repo = ToolOutputRepository()
    model = repo.create_reference(
        session_id="session-1",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data="expired",
        workspace_root=tmp_path,
    )
    model.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
    repo.session.commit()

    cleanup = cleanup_tool_outputs()
    counters = get_tool_output_health_counters()

    assert cleanup["expiredMetadata"] >= 1
    assert counters["retention_cleanup_expired_metadata"] >= 1
    assert counters["retention_cleanup_removed_blobs"] >= 1


def test_output_governance_falls_back_to_one_safe_result_on_reference_failure(monkeypatch):
    class FailingRepository:
        def create_reference(self, **kwargs):
            raise RuntimeError("storage unavailable")

    monkeypatch.setattr(
        "src.business.agents.tools.output_governance.ToolOutputRepository",
        lambda: FailingRepository(),
    )
    content = success_json("exec", {"stdout": "x" * 25000})

    governed = _obj(
        govern_tool_result(
            tool_name="exec",
            tool_call_id="call-1",
            session_id="session-1",
            content=content,
            workspace_root=".",
        )
    )

    assert governed["payload"]["compacted"] is True
    assert governed.get("references", []) == []
    assert "compaction_failed_fallback" in governed["warnings"]


def test_output_governance_withholds_invalid_upgraded_tool_result():
    secret = "token=invalid-envelope-secret"

    governed = _obj(
        govern_tool_result(
            tool_name="exec",
            tool_call_id="call-1",
            session_id="session-1",
            content=secret,
            workspace_root=".",
        )
    )

    assert governed["error"]["code"] == "handler_contract_violation"
    assert secret not in json.dumps(governed, ensure_ascii=False)

    forged = _obj(
        govern_tool_result(
            tool_name="exec",
            tool_call_id="call-1",
            session_id="session-1",
            content=success_json(
                "read_file",
                {"content": secret},
                references=[
                    {
                        "referenceId": "out_fake",
                        "kind": "tool_payload",
                        "sizeBytes": 1,
                        "storage_key": secret,
                    }
                ],
            ),
            workspace_root=".",
        )
    )

    assert forged["error"]["code"] == "handler_contract_violation"
    assert secret not in json.dumps(forged, ensure_ascii=False)


def test_small_custom_result_keeps_original_format():
    content = "custom tool result"

    assert (
        govern_tool_result(
            tool_name="custom_tool",
            tool_call_id="call-custom",
            session_id="session-1",
            content=content,
            tool_args={"query": "demo"},
            workspace_root=".",
        )
        == content
    )


def test_large_custom_result_compacts_and_reuses_existing_reference(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    repo = ToolOutputRepository()
    model = repo.create_reference(
        session_id="session-1",
        tool_name="custom_tool",
        tool_call_id="call-custom",
        kind="tool_payload",
        data="raw source",
        workspace_root=tmp_path,
    )
    content = success_json(
        "custom_tool",
        {"content": "x" * 25000},
        references=[
            {
                "referenceId": model.reference_id,
                "kind": model.kind,
                "sizeBytes": model.size_bytes,
                "contentType": model.content_type,
                "sha256": model.sha256,
            }
        ],
    )

    governed = _obj(
        govern_tool_result(
            tool_name="custom_tool",
            tool_call_id="call-custom",
            session_id="session-1",
            content=content,
            tool_args={"goal": "find issues"},
            workspace_root=tmp_path,
        )
    )

    assert governed["payload"]["compacted"] is True
    assert governed["payload"]["facts"]["outcome"] == "success"
    assert governed["references"][0]["referenceId"] == model.reference_id
    assert len(governed["references"]) == 1


def test_semantic_summary_is_advisory_and_does_not_replace_facts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "src.business.agents.tools.output_governance.summarize_tool_output",
        lambda **_kwargs: {
            "overview": "model says success",
            "keyFindings": [],
            "errors": [],
            "importantData": [],
            "nextActions": [],
            "extractionGoal": "find failure",
            "coverage": "complete",
            "mode": "single",
            "advisory": True,
        },
    )
    content = success_json(
        "exec",
        {"status": "failed", "exitCode": 9, "stderr": "ERROR\n" + "x" * 25000},
    )

    governed = _obj(
        govern_tool_result(
            tool_name="exec",
            tool_call_id="call-1",
            session_id="session-1",
            content=content,
            tool_args={"extractionGoal": "find failure"},
            workspace_root=tmp_path,
        )
    )

    assert governed["payload"]["facts"]["status"] == "failed"
    assert governed["payload"]["facts"]["exitCode"] == 9
    assert governed["payload"]["semanticSummary"]["advisory"] is True


def test_over_artifact_limit_still_respects_visible_cap(monkeypatch):
    original_get_config_int = __import__(
        "src.business.agents.tools.output_governance",
        fromlist=["get_config_int"],
    ).get_config_int

    def tiny_artifact_limit(getter, default, **kwargs):
        if getter == "get_agent_tools_output_max_artifact_bytes":
            return 1000
        return original_get_config_int(getter, default, **kwargs)

    monkeypatch.setattr(
        "src.business.agents.tools.output_governance.get_config_int",
        tiny_artifact_limit,
    )
    governed = govern_tool_result(
        tool_name="custom_tool",
        tool_call_id="call-1",
        session_id="session-1",
        content="x" * 1_000_000,
        workspace_root=".",
    )
    parsed = _obj(governed)

    assert len(governed) <= 12000
    assert parsed.get("references", []) == []
    assert "max_artifact_bytes_exceeded" in parsed["warnings"]


def test_handler_clipping_metadata_triggers_compaction(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    content = success_json(
        "custom_tool",
        {"content": "short"},
        warnings=["handler_output_clipped"],
    )

    governed = _obj(
        govern_tool_result(
            tool_name="custom_tool",
            tool_call_id="call-1",
            session_id="session-1",
            content=content,
            workspace_root=tmp_path,
        )
    )

    assert governed["payload"]["compacted"] is True
    assert governed["references"]


def test_load_tool_output_second_stage_reuses_source_reference(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    model = ToolOutputRepository().create_reference(
        session_id="session-1",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data="ERROR source\n" + ("x" * 100000),
        workspace_root=tmp_path,
    )
    loaded = load_tool_output_handler(
        model.reference_id,
        maxBytes=64000,
        sessionId="session-1",
        workspaceRoot=str(tmp_path),
    )
    governed = _obj(
        govern_tool_result(
            tool_name="load_tool_output",
            tool_call_id="call-2",
            session_id="session-1",
            content=loaded,
            tool_args={"extractionGoal": "find source error"},
            workspace_root=tmp_path,
        )
    )

    assert governed["payload"]["compacted"] is True
    assert governed["references"][0]["referenceId"] == model.reference_id
    assert len(governed["references"]) == 1


def test_web_fetch_compaction_uses_markdown_body_and_transport_facts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    markdown = (
        "# Trending\n\n"
        "## acme/project\n\n"
        "Production repository with 12,345 stars.\n\n" + ("Detailed project notes.\n\n" * 1200)
    )
    content = json.dumps(
        {
            "success": True,
            "url": "https://example.test/trending",
            "content": markdown,
            "truncated": True,
            "status": 200,
            "bytes": 54321,
            "duration_ms": 42,
            "content_type": "text/html; charset=utf-8",
            "result": "legacy prompt result",
        },
        ensure_ascii=False,
    )

    governed = _obj(
        govern_tool_result(
            tool_name="web_fetch",
            tool_call_id="call-web",
            session_id="session-1",
            content=content,
            tool_args={"prompt": "repository stars"},
            workspace_root=tmp_path,
        )
    )

    preview = governed["payload"]["preview"]
    facts = governed["payload"]["facts"]
    assert "acme/project" in preview
    assert "12,345 stars" in preview
    assert '\\"content\\"' not in preview
    assert '"success"' not in preview
    assert facts["url"] == "https://example.test/trending"
    assert facts["httpStatus"] == 200
    assert facts["bytes"] == 54321
    assert facts["truncated"] is True
    assert facts["contentType"] == "text/html; charset=utf-8"


def test_semantic_summary_failure_keeps_deterministic_web_preview_and_reference(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )

    def fail_summary(**_kwargs):
        raise RuntimeError("summary provider unavailable")

    monkeypatch.setattr(
        "src.business.agents.tools.output_governance.summarize_tool_output",
        fail_summary,
    )
    content = json.dumps(
        {
            "success": True,
            "url": "https://example.test/trending",
            "content": "# Trending\n\n## acme/project\n\n12,345 stars\n\n" + ("notes\n" * 5000),
            "truncated": False,
            "status": 200,
            "bytes": 40000,
            "content_type": "text/html",
        }
    )

    governed = _obj(
        govern_tool_result(
            tool_name="web_fetch",
            tool_call_id="call-web",
            session_id="session-1",
            content=content,
            tool_args={"prompt": "repository stars"},
            workspace_root=tmp_path,
        )
    )

    assert "semanticSummary" not in governed["payload"]
    assert "acme/project" in governed["payload"]["preview"]
    assert governed["payload"]["facts"]["httpStatus"] == 200
    assert governed["references"][0]["referenceId"].startswith("out_")


def test_load_tool_output_compaction_summarizes_each_window_not_full_artifact(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.data.repos.tool_output_repository.get_default_data_dir",
        lambda: tmp_path,
    )
    repo = ToolOutputRepository()
    page_size = 30000
    model = repo.create_reference(
        session_id="session-1",
        tool_name="exec",
        tool_call_id="call-1",
        kind="combined_output",
        data=("FIRST_PAGE_ALPHA\n" + ("a" * (page_size - 17)))
        + ("SECOND_PAGE_BETA\n" + ("b" * (page_size - 17))),
        workspace_root=tmp_path,
    )

    def load_and_govern(offset: int, call_id: str) -> dict:
        loaded = load_tool_output_handler(
            model.reference_id,
            offset=offset,
            maxBytes=page_size,
            sessionId="session-1",
            workspaceRoot=str(tmp_path),
        )
        return _obj(
            govern_tool_result(
                tool_name="load_tool_output",
                tool_call_id=call_id,
                session_id="session-1",
                content=loaded,
                tool_args={"extractionGoal": "inspect current page"},
                workspace_root=tmp_path,
            )
        )

    first = load_and_govern(0, "call-page-1")
    second = load_and_govern(page_size, "call-page-2")

    assert "FIRST_PAGE_ALPHA" in first["payload"]["preview"]
    assert "SECOND_PAGE_BETA" not in first["payload"]["preview"]
    assert "SECOND_PAGE_BETA" in second["payload"]["preview"]
    assert "FIRST_PAGE_ALPHA" not in second["payload"]["preview"]
    assert first["payload"]["facts"]["offset"] == 0
    assert first["payload"]["facts"]["windowBytes"] == page_size
    assert first["payload"]["facts"]["totalBytes"] == page_size * 2
    assert first["payload"]["facts"]["hasMore"] is True
    assert first["payload"]["facts"]["nextPageToken"] == str(page_size)
    assert second["payload"]["facts"]["offset"] == page_size
    assert second["payload"]["facts"]["hasMore"] is False
    assert first["references"][0]["referenceId"] == model.reference_id
    assert second["references"][0]["referenceId"] == model.reference_id
    assert len(list((tmp_path / "tool_outputs").glob("**/*.blob"))) == 1

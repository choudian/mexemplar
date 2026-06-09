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

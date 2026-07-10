import ast
from pathlib import Path


def test_external_coding_tools_do_not_hardcode_target_branch_git_mutations() -> None:
    source = Path("src/business/agents/tools/external_coding_tools.py").read_text(encoding="utf-8")

    forbidden = ["git merge", "git push", "git reset", "git clean"]
    assert all(token not in source for token in forbidden)


def test_quota_probe_model_has_no_raw_secret_fields() -> None:
    source = Path("src/business/external_coding/quota_probe.py").read_text(encoding="utf-8")

    assert "raw_response" not in source
    assert "access_token" not in source


def test_external_coding_execution_adapters_never_import_business_layer() -> None:
    for path in Path("src/execution").glob("external_coding*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        )
        assert not any(name.startswith("src.business") for name in imported), path


def test_external_coding_tools_are_not_in_main_assistant_static_tools() -> None:
    source = Path("src/business/orchestration/agent/tool_registry.py").read_text(encoding="utf-8")
    static_tools_section = source.split("static_tools = [", 1)[1].split("def tool_factory", 1)[0]

    assert "create_external_coding_tools" not in static_tools_section
    assert "executor_collaboration_tools" in source
    assert "create_external_coding_tools" in source


def test_start_session_requires_owner_type_and_owner_id() -> None:
    """F1 (Constitution IV): Owner-bound constraint is enforced in service and tool schema."""
    service_source = Path("src/business/external_coding/service.py").read_text(encoding="utf-8")
    tools_source = Path("src/business/agents/tools/external_coding_tools.py").read_text(
        encoding="utf-8"
    )

    # Service must call _coerce_owner which raises ValueError for missing owner
    assert "_coerce_owner" in service_source
    assert "ownerId is required" in service_source

    # Tool schema must mark ownerType and ownerId as required
    assert '"ownerType"' in tools_source
    assert '"ownerId"' in tools_source
    required_field = tools_source.split('required=["', 1)[1].split('"]', 1)[0]
    assert "ownerType" in required_field
    assert "ownerId" in required_field


def test_merge_authority_belongs_to_exemplar_only() -> None:
    """F2 (Constitution IV): Merge/rollback authority belongs to Exemplar, not external tools."""
    service_source = Path("src/business/external_coding/service.py").read_text(encoding="utf-8")
    tools_source = Path("src/business/agents/tools/external_coding_tools.py").read_text(
        encoding="utf-8"
    )
    git_ops_source = Path("src/business/external_coding/git_ops.py").read_text(encoding="utf-8")

    # Service must have merge_session and create_rollback_plan methods
    assert "def merge_session(" in service_source
    assert "def create_rollback_plan(" in service_source

    # External coding tools must NOT expose direct git merge/push/reset/clean operations
    # Only Exemplar-owned merge/merge-analysis/rollback-plan are allowed
    assert "git merge" not in tools_source
    assert "git push" not in tools_source
    assert "git reset" not in tools_source

    # git_ops must not have push or clean methods
    assert "def push(" not in git_ops_source
    assert "def clean(" not in git_ops_source

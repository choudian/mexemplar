from src.business.external_coding.artifacts import (
    preview_markdown,
    tail_file,
    write_handoff,
)
from src.business.external_coding.validators import (
    validate_plan_markdown,
    validate_result_markdown,
)


def test_plan_validator_accepts_semantic_markdown_without_fixed_headings() -> None:
    text = """
    目标：实现外部 coding session。
    改动计划：新增 service、repository 和 UI。
    影响范围：src/business、src/data、frontend。
    假设与非目标：只支持 Claude Code 和 Codex CLI。
    风险：CLI 参数可能变化。
    测试：跑 unit 和 API contract test。
    待确认问题：无。
    建议：可以继续实现。
    """

    assert validate_plan_markdown(text).valid


def test_result_validator_rejects_empty_report() -> None:
    result = validate_result_markdown("done")

    assert not result.valid
    assert "status" in result.missing


def test_handoff_never_persists_secret_context(tmp_path) -> None:
    path = write_handoff(
        tmp_path,
        objective="实现安全修复",
        context="ANTHROPIC_API_KEY=must-not-be-written",
        plan_path=tmp_path / "PLAN.md",
        result_path=tmp_path / "RESULT.md",
        worktree_path=tmp_path / "worktree",
    )

    content = path.read_text(encoding="utf-8")
    assert "must-not-be-written" not in content
    assert "<redacted>" in content


def test_artifact_preview_and_log_tail_are_bounded(tmp_path) -> None:
    artifact = tmp_path / "large.txt"
    artifact.write_text("prefix-" + ("x" * 50_000) + "-suffix", encoding="utf-8")

    preview = preview_markdown(artifact, max_chars=32)
    tail = tail_file(artifact, max_chars=32)

    assert preview is not None and len(preview) <= 32
    assert preview.startswith("prefix-")
    assert tail is not None and len(tail) <= 32
    assert tail.endswith("-suffix")

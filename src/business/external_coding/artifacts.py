"""Filesystem artifact helpers for external coding sessions."""

from __future__ import annotations

from pathlib import Path

from src.business.services.ui_event_safety_service import redact_public_ui_event_text
from src.utils.sensitive_text import redact_sensitive_text

PLAN_FILENAME = "PLAN.md"
RESULT_FILENAME = "RESULT.md"
HANDOFF_FILENAME = "HANDOFF.md"
PROMPT_DIRECTORY = "prompts"
MAX_ARTIFACT_CHARS = 1_000_000


def ensure_artifact_dir(root: Path, coding_session_id: str) -> Path:
    artifact_dir = root / coding_session_id
    (artifact_dir / "logs").mkdir(parents=True, exist_ok=True)
    return artifact_dir


def write_handoff(
    artifact_dir: Path,
    *,
    objective: str,
    context: str,
    plan_path: Path,
    result_path: Path,
    worktree_path: Path,
) -> Path:
    handoff = artifact_dir / HANDOFF_FILENAME
    safe_objective = _safe_prompt_text(
        redact_sensitive_text(objective, redact_emails=True),
        max_chars=8000,
    )
    safe_context = _safe_prompt_text(
        redact_sensitive_text(context, redact_emails=True),
        max_chars=20_000,
    )
    content = f"""# External Coding Handoff

## Objective

{safe_objective or "No objective provided."}

## Context

{safe_context or "No additional context provided."}

## Protocol

1. First produce a Markdown plan at `{plan_path}`.
2. Do not write code during the plan phase.
3. Wait for Exemplar approval before implementation.
4. After implementation, write a Markdown result report at `{result_path}`.
5. Disclose tests, dependency/network actions, lockfile changes, deviations and risks.
6. Do not merge, push, reset or clean the target branch.

## Workspace

- Worktree: `{worktree_path}`
- Artifact directory: `{artifact_dir}`
"""
    handoff.write_text(content, encoding="utf-8")
    return handoff


def write_attempt_prompt(
    artifact_dir: Path,
    *,
    phase: str,
    attempt_number: int,
    handoff_path: Path,
    plan_path: Path,
    result_path: Path,
    approval_feedback: str = "",
    resume_instruction: str = "",
    external_session_ref: str | None = None,
) -> Path:
    """Create an immutable, phase-specific prompt for one process attempt."""
    prompt_dir = artifact_dir / PROMPT_DIRECTORY
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = prompt_dir / f"{phase}-{attempt_number}.md"
    feedback = _safe_prompt_text(approval_feedback, max_chars=2000)
    instruction = _safe_prompt_text(resume_instruction, max_chars=2000)
    resume_context = (
        "Resume the existing external conversation recorded by Exemplar."
        if external_session_ref
        else "This invocation starts a new external conversation for the same codingSessionId."
    )

    if phase == "plan":
        phase_instructions = f"""## Plan Phase

Read the complete assignment in `{handoff_path}`.
Read `AGENTS.md` in the worktree root and any nearer module instructions that
apply to files you inspect.

Do not modify files in the coding worktree. Read and investigate only, then write
the proposed plan to `{plan_path}`. The plan must cover the target restatement,
planned changes, expected impact area, assumptions and non-goals, risks, test
plan, open questions, and a recommendation on whether implementation should
proceed. Do not implement the plan in this attempt.
"""
        if feedback:
            phase_instructions += f"\n## Dispatching Agent Feedback\n\n{feedback}\n"
    elif phase == "implement":
        phase_instructions = f"""## Implementation Phase

Read the complete assignment in `{handoff_path}` and the approved plan in
`{plan_path}`. Read `AGENTS.md` in the worktree root and any nearer module
instructions before editing. The dispatching agent approved that plan.
Implement it in the coding worktree, run the appropriate verification, and
write the final report to `{result_path}`. The report must disclose changed
files, deviations, tests, test results, dependency or network actions, lockfile
changes, risks, follow-up needs, and completion notes.
"""
        if feedback:
            phase_instructions += f"\n## Approval Notes\n\n{feedback}\n"
    else:
        raise ValueError("attempt prompt phase must be plan or implement")

    if instruction:
        phase_instructions += f"\n## Resume Instruction\n\n{instruction}\n"
    content = f"""# External Coding Attempt

{resume_context}

{phase_instructions.strip()}

## Safety Boundary

Do not merge, push, reset, clean, rebase, or delete the target branch. Exemplar
alone performs merge and rollback actions after reviewing the result.
"""
    prompt_path.write_text(content, encoding="utf-8")
    return prompt_path


def _safe_prompt_text(value: str, *, max_chars: int) -> str:
    safe = redact_public_ui_event_text(
        "externalCodingInstruction",
        value,
        max_preview_chars=max_chars,
        max_len=max_chars,
    )
    return str(safe or "").strip()


def read_text_if_exists(path: Path, *, max_chars: int = MAX_ARTIFACT_CHARS) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            data = handle.read(max(1, max_chars) * 4)
    except OSError:
        return None
    return data.decode("utf-8", errors="replace")[:max_chars]


def preview_markdown(path: Path | None, *, max_chars: int = 1200) -> str | None:
    if path is None:
        return None
    text = read_text_if_exists(path, max_chars=max_chars)
    if text is None:
        return None
    compact = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    preview = compact[:max_chars]
    return redact_public_ui_event_text("artifactPreview", preview, max_preview_chars=max_chars)


def tail_file(path: Path | None, *, max_chars: int) -> str | None:
    if path is None or not path.exists() or not path.is_file():
        return None
    byte_window = max(1, max_chars) * 4
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - byte_window))
            data = handle.read(byte_window)
    except OSError:
        return None
    tail = data.decode("utf-8", errors="replace")[-max_chars:]
    return redact_public_ui_event_text("logTail", tail, max_preview_chars=max_chars)

---
name: speckit-worktree-create
description: Spawn an isolated git worktree for a new or existing feature branch (used as the before_specify hook to keep main untouched)
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: github-spec-kit
  source: worktree:commands/speckit.worktree.create.md
---

# Create Worktree

Spawn an isolated git worktree for a feature branch so you can work on multiple features in parallel without switching branches. Each worktree gets its own directory with a full working copy.

This skill operates in **two modes**:

- **existing-branch mode** (default): create a worktree for a branch that already exists.
- **new-feature mode**: create a brand-new feature branch *and* its worktree atomically, without modifying the main working directory. This is the mode used by the `before_specify` hook so that `/speckit-specify` can develop a new feature in isolation from `main`.

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

The user input may be one of:

- A branch name (e.g., `003-user-auth`) — switches to **existing-branch mode**.
- The literal word `current` — **existing-branch mode** for the current branch.
- A natural-language feature description (e.g., `add OAuth2 login`) — switches to **new-feature mode**.
- Empty — fall back to existing-branch mode for the most recent feature branch.

When this skill is invoked as a `before_specify` hook, the user input is the **feature description** the user typed after `/speckit-specify`. Always treat it as new-feature mode in that context.

## Prerequisites

1. Verify a spec-kit project exists by checking for `.specify/` directory.
2. Verify git is available and the project is a git repository.
3. For **existing-branch mode**: check that the target branch exists (local or remote).
4. For **new-feature mode**: no branch existence check (we will create it).

## Outline

### Mode selection

Decide the mode from the user input:

- If the input is empty, or matches an existing branch (`git rev-parse --verify <input>` succeeds), or equals `current` → **existing-branch mode**.
- Otherwise, treat the input as a **feature description** → **new-feature mode**.

### Existing-branch mode

1. **Determine target branch**:
   - If user specifies a branch name, use that.
   - If user says `current`, use the current branch.
   - If no input, pick the most recently created feature branch.
   - Validate the branch exists in git.

2. **Choose worktree location**:
   - Default location: `.worktrees/{branch-name}/` relative to the repository root.
   - If `.worktrees/` directory does not exist, create it.
   - Add `.worktrees/` to `.gitignore` if not already present.
   - Verify the worktree does not already exist for this branch.

3. **Create the worktree**:
   - Run `git worktree add .worktrees/{branch-name} {branch-name}`.
   - If the branch is remote-only, track it: `git worktree add .worktrees/{branch-name} -b {branch-name} origin/{branch-name}`.
   - Verify the worktree was created successfully.

4. **Verify spec artifacts**: confirm `specs/{branch-name}/` exists in the worktree and list available artifacts (spec.md, plan.md, tasks.md).

5. **Report** (see Reporting section below).

### New-feature mode

This mode replaces the legacy `git.feature` hook. The main working directory is **never** modified — neither its branch nor its working tree.

1. **Compute the branch name** by invoking `create-new-feature.sh` in dry-run mode (it computes the name without checking out a branch). Pass through `GIT_BRANCH_NAME` if set, and respect `branch_numbering` from `.specify/extensions/git/git-config.yml` or `.specify/init-options.json`:

   - Generate a concise short name (2-4 words) from the feature description.
   - **Bash (sequential)**: `.specify/extensions/git/scripts/bash/create-new-feature.sh --json --dry-run --short-name "<short-name>" "<feature description>"`
   - **Bash (timestamp)**: add `--timestamp`.
   - **PowerShell (sequential)**: `.specify/extensions/git/scripts/powershell/create-new-feature.ps1 -Json -DryRun -ShortName "<short-name>" "<feature description>"`
   - **PowerShell (timestamp)**: add `-Timestamp`.

   Parse the resulting JSON to obtain `BRANCH_NAME` and `FEATURE_NUM`.

   **Important**:
   - Do not pass `--number` — the script auto-detects.
   - Always include `--json` / `-Json`.
   - The script must not be invoked twice for the same feature.

2. **Choose worktree location**: `.worktrees/{BRANCH_NAME}/`. Ensure `.worktrees/` exists and is in `.gitignore`. Refuse if the worktree path already exists.

3. **Create branch + worktree atomically** from the main repository root (do **not** `cd` into the worktree to do this):
   - Run `git worktree add -b {BRANCH_NAME} .worktrees/{BRANCH_NAME} HEAD`.
   - This creates a new branch `{BRANCH_NAME}` based on the current `HEAD` of the main worktree, *and* checks it out inside `.worktrees/{BRANCH_NAME}/`.
   - The main worktree's branch and working tree are unchanged — verify with `git rev-parse --abbrev-ref HEAD` (should match the original branch).

4. **No spec artifacts yet**: the spec directory will be created by `/speckit-specify` next, inside the worktree. Do not pre-create it.

5. **Report** (see Reporting section below) and emit the structured payload below so `/speckit-specify` can pick it up.

## Reporting

After either mode succeeds, output a human summary **and** a JSON payload (so the calling command — typically `/speckit-specify` — can parse it).

Human summary:

```markdown
# Worktree Created

| Field | Value |
|-------|-------|
| **Mode** | new-feature \| existing-branch |
| **Branch** | {BRANCH_NAME} |
| **Worktree path** | .worktrees/{BRANCH_NAME}/ |
| **Spec artifacts** | spec.md ✅, plan.md ✅, tasks.md ❌  *(existing-branch mode only)* |

## Next Steps
- `cd .worktrees/{BRANCH_NAME}/` to work in the isolated worktree.
- (new-feature mode) Continue with `/speckit-specify` — it will write the spec inside this worktree.
- (existing-branch mode) Run `/speckit-implement` inside the worktree to build the feature.
- Run `/speckit-worktree-list` to see all active worktrees.
- When done, run `/speckit-worktree-clean` to remove the worktree.
```

JSON payload (single line, machine-readable — emit on its own line, prefixed with `WORKTREE_RESULT:` so callers can grep for it):

```
WORKTREE_RESULT: {"BRANCH_NAME":"{BRANCH_NAME}","FEATURE_NUM":"{FEATURE_NUM}","WORKTREE_PATH":".worktrees/{BRANCH_NAME}","MODE":"new-feature"}
```

For existing-branch mode `FEATURE_NUM` is whatever numeric/timestamp prefix the branch name carries (or the full branch name if there is no prefix).

## Rules

- **Never modify the main working directory** — branch creation in new-feature mode goes through `git worktree add -b ... HEAD`, which leaves the main worktree untouched.
- **Always update .gitignore** — ensure `.worktrees/` is ignored to prevent accidental commits.
- **One worktree per branch** — refuse to create a duplicate worktree for the same branch.
- **In existing-branch mode, validate the branch exists** — do not silently fall through to new-feature mode.
- **Preserve existing worktrees** — never overwrite or remove an existing worktree.
- **In new-feature mode, never create the spec directory** — that is `/speckit-specify`'s job.

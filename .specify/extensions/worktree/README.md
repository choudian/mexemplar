# spec-kit-worktree

A [Spec Kit](https://github.com/github/spec-kit) extension that spawns isolated git worktrees for parallel feature development — work on multiple features simultaneously without checkout switching.

## Problem

Spec Kit creates a new branch for each feature, but developers can only work on one branch at a time in a single working directory. This creates friction:

- Switching branches with `git checkout` discards local context (open files, editor state)
- Running multiple AI agents on different features requires separate clones
- Long-running implementations block work on other features
- No way to compare two features side-by-side in their own directories
- Stale worktrees from old features accumulate without cleanup tooling

## Solution

The Worktree Isolation extension adds three commands for managing parallel feature workspaces:

| Command | Purpose | Modifies Files? |
|---------|---------|-----------------|
| `/speckit.worktree.create` | Spawn an isolated git worktree for a new or existing feature branch | Yes — creates worktree directory, updates .gitignore |
| `/speckit.worktree.list` | Show all active worktrees with feature status and task progress | No — read-only |
| `/speckit.worktree.clean` | Remove stale or merged worktrees and reclaim disk space | Yes — removes worktree directories |

## Installation

```bash
specify extension add --from https://github.com/Quratulain-bilal/spec-kit-worktree/archive/refs/tags/v1.0.0.zip
```

## How It Works

Git worktrees let you check out multiple branches simultaneously in separate directories. Each worktree is a lightweight working copy that shares the same `.git` repository — no extra clone needed.

```
your-project/                    ← main working directory (main branch)
├── .worktrees/
│   ├── 003-user-auth/           ← worktree (003-user-auth branch)
│   │   ├── specs/
│   │   ├── src/
│   │   └── ...
│   ├── 004-chat-system/         ← worktree (004-chat-system branch)
│   │   ├── specs/
│   │   ├── src/
│   │   └── ...
│   └── 005-api-gateway/         ← worktree (005-api-gateway branch)
├── specs/
├── src/
└── ...
```

## Workflow

```
/speckit.specify                  ← Create a new feature (generates branch)
       │
       ▼
/speckit.worktree.create          ← Spawn isolated worktree for the feature
       │
       ▼
cd .worktrees/{branch}/           ← Work in isolation
/speckit.implement                ← Build the feature
       │
       ▼
/speckit.worktree.list            ← Check all worktrees and progress
       │
       ▼
/speckit.worktree.clean           ← Remove merged/stale worktrees
```

## Commands

### `/speckit.worktree.create`

Spawns an isolated worktree for a feature branch:

- Creates worktree in `.worktrees/{branch-name}/`
- Automatically adds `.worktrees/` to `.gitignore`
- Supports both local and remote-tracking branches
- Verifies spec artifacts are accessible in the worktree
- One worktree per branch — prevents duplicates

### `/speckit.worktree.list`

Read-only dashboard showing all active worktrees:

- Branch name, path, and last activity date
- Spec artifact availability (spec.md, plan.md, tasks.md)
- Task completion progress (percentage)
- Status classification: Active, Idle, Stale, Merged, Orphaned
- Recommends cleanup actions for merged/orphaned worktrees

### `/speckit.worktree.clean`

Safely removes worktrees that are no longer needed:

- Shows cleanup plan with confirmation before removing anything
- Warns about uncommitted changes (refuses to remove unless confirmed)
- Safe defaults: only removes merged and orphaned worktrees
- Runs `git worktree prune` after cleanup
- Never deletes the git branch — only removes the working directory

## Hooks

The extension registers an optional hook:

- **after_specify**: Offers to create an isolated worktree after a new feature is specified

## Design Decisions

- **`.worktrees/` directory** — all worktrees live in a single, gitignored directory at the repo root
- **Never auto-remove** — cleanup always requires confirmation, especially for worktrees with uncommitted changes
- **Branch-safe** — removing a worktree never deletes the git branch itself
- **Shared `.git`** — worktrees share the same git repository, no extra clone overhead
- **Status-aware** — list command shows spec-kit context (artifacts, task progress), not just git metadata

## Requirements

- Spec Kit >= 0.4.0
- Git >= 2.15.0 (worktree support)

## Related

- Issue [#61](https://github.com/github/spec-kit/issues/61) — Spawn Worktree When Creating New Branch (36+ upvotes)

## License

MIT

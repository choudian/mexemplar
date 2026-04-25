# Blueprint

Pre-implementation blueprint generator. Reads spec artifacts and produces a single `blueprint.md` with complete, ready-to-use content for every task — so you can review, understand, and type through the implementation before `/speckit.implement` runs.

![Spec Kit >= 0.2.0](https://img.shields.io/badge/spec--kit-%3E%3D0.2.0-blue)
![Version 1.0.0](https://img.shields.io/badge/version-1.0.0-green)
![License MIT](https://img.shields.io/badge/license-MIT-brightgreen)

A [Spec Kit](https://github.com/github/spec-kit) community extension.

## Workflow Position

```
/speckit.specify                        → spec.md
/speckit.clarify                        → clarifications
/speckit.plan                           → plan.md
/speckit.tasks                          → tasks.md
                                          ↓ after_tasks hook (optional)
/speckit.blueprint.generate [mode]      → blueprint.md  ★
                                          ↓ before_implement hook (safety net)
/speckit.implement                      → code
/speckit.checklist                      → verify
```

Spec Kit's core workflow goes from `tasks.md` directly to `/speckit.implement`. This extension inserts a step between them: generate a complete blueprint, review it, then implement.

## What It Does

Reads `tasks.md`, `spec.md`, `plan.md` (and optionally `data-model.md`, `contracts/`) from the feature directory and generates `blueprint.md` containing:

- Complete content for every new file — ready to copy-paste or type through
- Before/after diffs for every modified file — with exact line references
- Key decisions with requirement traceability (FR-xxx → Task ID)
- Dependency-ordered implementation phases
- A task checklist at the end

Two modes:

| Mode | Output |
|------|--------|
| `doc-only` (default) | `blueprint.md` only — nothing written to disk |
| `scaffold` | `blueprint.md` + new files on disk (structural files complete, core logic as TODO stubs) |

## Why

When AI writes all the code, the developer can lose familiarity with the codebase. The blueprint gives you a chance to:

- **Read the implementation before it exists** — understand what files will be created, how they connect, and what patterns they follow
- **Type through it yourself** — learn the project's conventions, spot design issues, and catch incorrect assumptions before any code is committed

The blueprint persists in `specs/{feature}/` as a record of what was intended — useful for onboarding, design review, or revisiting decisions later.

## Installation

```bash
specify extension add blueprint
```

From repository directly:

```bash
specify extension add blueprint --from https://github.com/chordpli/spec-kit-blueprint/archive/refs/tags/v1.0.0.zip
```

## Usage

### Generate (doc-only)

```
/speckit.blueprint.generate
```

Produces `specs/{feature}/blueprint.md`. No files created on disk.

### Generate (scaffold)

```
/speckit.blueprint.generate scaffold
```

Produces `blueprint.md` + creates new files on disk. Structural files (type definitions, interfaces, configuration, wiring) are complete. Core implementation and test files contain TODO stubs with requirements from the spec. The developer references `blueprint.md` for the full implementation.

### Implement after review

```
/speckit.implement
```

`/speckit.implement` can work entirely from `blueprint.md`. Review the blueprint, then run implement.

### Validate scaffold

```
/speckit.blueprint.validate
/speckit.blueprint.validate specs/003-user-auth
```

Checks: blueprint exists, all referenced files exist on disk, TODO markers present in core files, no over-implemented scaffolds.

Exit code `0` = pass. Exit code `1` = failure.

## Commands

### `/speckit.blueprint.generate [mode]`

| Argument | Description |
|----------|-------------|
| _(none)_ | doc-only — generate `blueprint.md` only |
| `scaffold` | Generate blueprint + stub files with TODO markers |

**Requires**: `tasks.md` in the feature directory.

**Produces**: `specs/{feature}/blueprint.md` — structured by phase and task, with full content blocks, before/after diffs, key decisions, implementation order, and checklist.

### `/speckit.blueprint.validate [feature-dir]`

| Argument | Description |
|----------|-------------|
| _(none)_ | Auto-detect feature directory from current branch |
| `specs/NNN-name` | Use specified directory |

**Checks**: blueprint exists, new files exist, TODO markers in core files, no over-implementation.

## Hooks

One optional hook:

| Hook | When | Prompt |
|------|------|--------|
| `after_tasks` | After `/speckit.tasks` completes | "Generate blueprint from tasks?" |

Answer `y` to generate in doc-only mode. You can always run the command manually with a different mode afterward.

Disable hook: `specify extension disable blueprint`

## Validation Script

The validate command runs a bundled Bash script:

```bash
bash .specify/extensions/blueprint/scripts/bash/validate-scaffold.sh specs/{feature}
```

Color-coded output: green (pass), yellow (warning), red (failure). Usable in CI or pre-commit hooks.

## Troubleshooting

| Error | Solution |
|-------|----------|
| "Run `/speckit.tasks` first" | Generate tasks before running blueprint |
| "blueprint.md not found" | Run `/speckit.blueprint.generate` first |
| "File MISSING" | Re-run scaffold mode or create the file manually |
| "No TODO markers found" | Core file may have been generated outside scaffold mode |
| Command not available | Check `specify extension list`, restart agent session, reinstall |

## License

MIT — see [LICENSE](LICENSE)

## Support

- **Issues**: <https://github.com/chordpli/spec-kit-blueprint/issues>
- **Spec Kit**: <https://github.com/github/spec-kit>

---

*Extension Version: 1.0.0 | Spec Kit: >=0.2.0*

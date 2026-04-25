---
description: "Generate a pre-implementation blueprint from spec artifacts with optional file scaffolding"
---

# Blueprint Generator

## Why This Exists

In AI-driven development, `/speckit.implement` can execute tasks directly — but the developer loses the chance to understand what's being built. This extension generates `blueprint.md` as a **pre-implementation blueprint** that sits between `/speckit.tasks` and `/speckit.implement`.

By typing through the blueprint, the developer:
- Learns the project's code conventions and architecture by following real examples
- Understands the structure and dependencies before code is written
- Catches design mistakes, missing edge cases, or incorrect assumptions early
- Stays code-literate even when AI handles the actual implementation

The blueprint is the single source of truth: every file, every change, every task — complete and ready to follow.

## User Input

```text
$ARGUMENTS
```

Parse the user's input for a mode keyword:

| Keyword | Mode | Behavior |
|---------|------|----------|
| _(default)_ | `doc-only` | Generate `blueprint.md` only. No files created on disk. |
| `scaffold` | `scaffold` | Generate `blueprint.md` + create new files as scaffolds (structural files complete, core logic as TODO) |

Examples:
- `/speckit.blueprint.generate` → doc-only
- `/speckit.blueprint.generate scaffold` → blueprint + scaffold files

> **Want full implementation?** Run `/speckit.implement` after reviewing the blueprint. The blueprint is designed so that `/speckit.implement` can work entirely from `blueprint.md`.

## Workflow

### Step 1: Load Context

Run the prerequisites check from the repository root:

```bash
.specify/scripts/bash/check-prerequisites.sh --json --paths-only
```

Parse `FEATURE_DIR` from the output. Then load the following spec artifacts from that directory:

- **Required**: `tasks.md`, `spec.md`, `plan.md`
- **Optional**: `data-model.md`, `contracts/` directory

If `tasks.md` is missing, abort with the message: "Run `/speckit.tasks` first."

Also read existing reference files to match project patterns:
1. For each directory that appears in `tasks.md` file paths, read 1-2 existing files in that directory to learn conventions
2. Read one example of each file type being generated (e.g., if generating a config file, read an existing config file first)
3. Limit reference reading to at most 10 files — enough to infer patterns, not enough to exhaust context

### Step 2: Extract and Categorize Files

Parse `tasks.md` to extract every file path mentioned. Check each path against disk and classify each task:

| Category | Condition | Blueprint Content |
|----------|-----------|-------------------|
| **New file** | Does not exist on disk | Full file content in blueprint |
| **Modified file** | Exists on disk, changes needed | Diff-style changes (before/after) with line references |
| **Delete file** | Task explicitly says "delete" | Deletion instruction + impact analysis |
| **Already complete** | File exists and already matches the task requirements | No code block needed — listed in Pre-completed Tasks table |

### Handling already-complete tasks

If a task's file already exists on disk and fully satisfies the task requirements (e.g., from a prior scaffolding phase), do NOT repeat the code in the blueprint body. Instead:

1. List it in a **Pre-completed Tasks** summary table at the top of each Phase
2. Mark it as `[X]` in the final Checklist
3. Keep the task ID — never merge multiple task IDs into one heading

### Step 3: Generate blueprint.md

Create `specs/{feature}/blueprint.md` with the following structure:

````markdown
# Blueprint: {Feature Name}

**Branch**: `{branch}` | **Date**: {date}
**Mode**: {doc-only|scaffold}
**Total Tasks**: {count} | **Files**: {new} new, {modified} modified, {deleted} deleted

## Key Decisions

- {Decision 1 and its implementation impact} → T{ID}
- {Decision 2} → T{ID}, T{ID}

## Implementation Order

```
{Dependency graph derived from tasks.md}
```

---

## Phase N: {Phase Title}

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T{ID}: {description} | `{path}` | Already complete — {brief reason} |

> Only include this table if the phase has already-complete tasks. Tasks listed here do NOT get a full heading or code block below.

---

### T{ID}: {Task Description}

**File**: `{path/to/file}` ({new|modify|delete})

**Requirements**: FR-xxx, FR-yyy

**Dependencies**: T{prev}

```{language-or-format}
{Complete file content for NEW files}
{OR diff-style before/after for MODIFIED files}
```

**Verification**: {How to verify this task is done}

---

{Repeat for each task that requires work}

## Checklist

- [X] T001: {description} ← already complete
- [ ] T002: {description}
- [ ] T003: {description}
...
````

### Step 3a: Content Rules (CRITICAL)

The blueprint is a **complete implementation blueprint**. A developer must be able to copy-paste every code block and have it work as-is (compile, run, apply, deploy — whatever "working" means for that file type).

> **ABSOLUTE RULE**: `blueprint.md` NEVER contains `TODO`, `FIXME`, ellipsis placeholders (`// ...`, `# ...`), or any form of stub/incomplete content in any syntax. The mode (`doc-only`, `scaffold`) only affects what is written to disk in Step 4 — it does NOT affect the completeness of content in the blueprint itself.

**For every NEW file**: Write the COMPLETE file content. Every declaration, every import, every function body must contain real, working content. No placeholders.

**For every MODIFIED file**: Show the change as before/after blocks:

````markdown
**Before** (line {N}):
```{language-or-format}
{existing content}
```

**After**:
```{language-or-format}
{new content}
```
````

**Before block rules**:
- Show the ACTUAL existing content — never abbreviate with `// ... stub` or `// ... rest of file`
- If the entire file should be replaced, write `**Replace entire file**:` followed by one code block with the full new content
- The Before block must contain enough real content for the developer to locate the exact insertion point by searching
- When a single file has multiple Before/After blocks, list them in **bottom-to-top order** (highest line number first) so applying changes sequentially does not shift earlier line references. If changes are too interleaved, use a single **Replace entire file** block instead.

**For core implementation files** (the primary logic of the project — whatever form that takes):
- Write complete implementation with all logic — no stubs, no TODO comments
- Include comments explaining non-obvious decisions only (not as placeholders for unwritten content)
- Reference requirement IDs (FR-xxx) for traceability

**For verification/test files**:
- Write complete test/verification content with real assertions and expected values
- Match the project's existing test patterns and conventions

**For configuration and infrastructure files**:
- Write complete, valid configuration — not partial snippets
- Never include real secrets — use obvious placeholders (`your-api-key-here`, `changeme`, `<REPLACE_ME>`)

### Step 4: Optionally Create Files on Disk

Based on the mode determined in User Input. **This step is the ONLY place where TODO markers may appear (scaffold mode files on disk). The blueprint document itself is always complete.**

| Where | Core implementation | Structural / config |
|-------|--------------------|--------------------|
| `blueprint.md` | Complete — NO TODO | Complete — NO TODO |
| Scaffold files on disk | TODO stubs with requirements | Complete (same as blueprint) |

**`doc-only`**: Skip file creation entirely. Only `blueprint.md` is written.

**`scaffold`**: For each NEW file, write to disk:
- **Structural files** (type definitions, interfaces/contracts, schemas, enums, configuration, routing/wiring): Write complete content (same as blueprint) — these are needed for other files to work
- **Core implementation files** (the files containing primary logic): Write the structure with TODO comments containing step-by-step requirements from the spec
- **Verification/test files**: Write the structure with TODO comments containing test scenarios

Note: The scaffold files on disk are intentionally incomplete (TODO stubs). The developer references `blueprint.md` for the full implementation.

**Modified files**: Never auto-edit in any mode. The blueprint provides the diff for manual or assisted application.

> **Need full file generation?** Skip this extension and run `/speckit.implement` directly — it generates complete files from your spec artifacts.

### Step 4b: Self-Verification

Before finalizing the blueprint, scan ALL content blocks for violations:
- `TODO`, `FIXME`, `HACK`, `XXX`, or any placeholder markers in any syntax
- Ellipsis placeholders (`// ...`, `# ...`, `/* ... */`)
- Empty function/method bodies with no real logic
- Comments describing unwritten content (e.g., "implement this", "add logic here")

If ANY are found in the blueprint, replace them with actual implementation before proceeding.

Also scan for secrets:
- API keys, passwords, tokens, or connection strings that look real (not obviously fake placeholders)
- Environment/config file contents with actual credential values

Also verify:
- Every import/dependency reference either exists on disk or is created by an earlier task in the blueprint
- Every task ID from `tasks.md` appears in the blueprint (either as a heading or in a Pre-completed table)

### Step 5: Report

Output a summary:
- Path to the generated `blueprint.md`
- Mode used (`doc-only` or `scaffold`)
- File counts: {new} new, {modified} modified, {deleted} deleted
- If `scaffold` mode: list of files created on disk
- Suggested next step (e.g., "Review the blueprint, then run `/speckit.implement`")

## Rules

- **ZERO TODO in the blueprint**: `blueprint.md` must NEVER contain `TODO`, `FIXME`, `// ...`, or any stub/placeholder content in any syntax. Every content block must be complete and working. TODO markers are ONLY allowed in scaffold files written to disk (Step 4).
- **ONE task = ONE ID**: Never merge multiple task IDs into one heading (e.g., `T041–T044` is forbidden). Each task from `tasks.md` must have its own entry — either a full heading with content, or a row in the Pre-completed Tasks table. This preserves 1:1 traceability between `tasks.md` and the blueprint.
- **No abbreviation in Before blocks**: Before blocks must show actual existing content, not `// ... stub` or `// ... rest of file`. The developer must be able to locate the exact content to replace by searching the Before block.
- **Already-complete tasks stay lean**: Tasks whose files already satisfy requirements go in the Pre-completed Tasks table per phase, not as full headings with empty content blocks. This keeps the blueprint focused on real work.
- **Read before generating**: Before generating content that calls or references existing modules/files, read their actual signatures and APIs from disk. Never assume interface shapes — verify against actual implementation to prevent mismatched names, parameters, or contracts.
- **Final version for multi-modified files**: If a file is modified 3 or more times across different phases, include a final consolidated version of the complete file as an appendix at the end of its last phase.
- **Key Decision traceability**: Every entry in the Key Decisions section must include at least one Task ID back-reference (e.g., `→ T055`) linking the decision to the task(s) it affects.
- **Dependency completeness**: When a task introduces new dependencies between modules, packages, or external libraries, include all necessary build/dependency configuration changes (build manifests, dependency declarations, module registrations) as explicit content blocks in the relevant task.
- **ZERO SECRETS**: `blueprint.md` and any files created on disk must NEVER contain real or realistic-looking secrets, passwords, API keys, tokens, or connection strings. Use obviously fake placeholders. For environment/config files with sensitive values, always use placeholder values and note that real values must be configured separately.
- **Configuration completeness**: When generated content references environment variables, config keys, or external service endpoints, the blueprint MUST include a corresponding configuration file change listing every new variable with a placeholder value and a comment explaining its purpose.
- **Migration/schema rules**: For tasks involving schema or state changes (database migrations, API version bumps, protocol changes, etc.), include both the forward change and the rollback/revert strategy where applicable. Preserve the project's naming conventions for versioned files.
- Output filename is always `blueprint.md` (lowercase)
- Follow the project's constitution and CLAUDE.md architecture rules
- Match existing patterns — read reference files before generating
- All content blocks must be complete and valid — a developer can copy-paste and it works
- Every task from `tasks.md` must appear in the blueprint — no omissions (either as a heading or in the Pre-completed table)
- Modified files show before/after diffs with line references (~{N})
- `blueprint.md` is the single source of truth — a developer should be able to implement the entire feature using only this document
- Use full file paths in all tables and headings — never abbreviate with `...`
- Follow the language used in existing spec/plan/tasks documents (do not switch languages mid-document)

## Markdown Formatting Rules

- After every bold label (`**Required changes**:`, `**Current state**:`, etc.) — add a blank line before content
- Before `**Requirements**:` — add a blank line
- Before and after every code block (```) — add a blank line
- After every `---` separator — add a blank line
- Numbered lists must have a blank line before the first item

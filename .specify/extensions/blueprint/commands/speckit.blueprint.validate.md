---
description: "Validate scaffold files against the blueprint"
---

# Validate Blueprint Scaffold

Validate that scaffold files created by `/speckit.blueprint.generate scaffold` are correct — files exist, TODO markers are present in business logic, and no scaffold file is over-implemented.

## User Input

```text
$ARGUMENTS
```

If arguments contain a directory path, use it as the feature directory. Otherwise, auto-detect from the current branch.

## Prerequisites

- `blueprint.md` must exist (run `/speckit.blueprint.generate` first)
- Scaffold mode must have been used to create files

## Execution

Run the validation script from the repository root:

**Bash (macOS/Linux)**:

```bash
bash .specify/extensions/blueprint/scripts/bash/validate-scaffold.sh "$FEATURE_DIR"
```

Where `$FEATURE_DIR` is the `specs/{feature}/` directory path. If not provided by the user, resolve it automatically:

1. Get the current git branch name
2. Extract the numeric prefix (e.g., `003` from `003-user-auth`)
3. Find the matching directory under `specs/`

## Validation Checks

The script performs four checks:

1. **Blueprint Document**: Verifies `blueprint.md` exists
2. **File Existence**: All NEW files referenced in the blueprint exist on disk
3. **TODO Markers**: Service and test files contain TODO comments (confirming scaffold mode)
4. **Over-Implementation Detection**: No scaffold file is suspiciously complete (zero TODOs + many methods + many lines)

## Output

The script outputs color-coded results:
- Green checkmarks for passing checks
- Yellow warnings for non-critical issues
- Red failures for problems that must be fixed

Exit code 0 means pass (possibly with warnings), exit code 1 means failure.

## Troubleshooting

### "blueprint.md not found"
Run `/speckit.blueprint.generate scaffold` first to generate the blueprint and scaffold files.

### "File MISSING"
A file referenced in the blueprint was not created. Re-run `/speckit.blueprint.generate scaffold` or create the file manually.

### "No TODO markers found"
A service or test file appears fully implemented. In scaffold mode, business logic should contain TODO comments. Check if the file should have been generated in scaffold mode.

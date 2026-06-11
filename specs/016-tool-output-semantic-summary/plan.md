# Implementation Plan: Tool Output Semantic Summary

**Branch**: `016-tool-output-semantic-summary` | **Date**: 2026-06-11 | **Spec**: [spec.md](./spec.md)

## Summary

Extend the 015 output-governance save boundary with deterministic high-signal extraction and an optional dedicated low-cost LLM summarizer. The governance boundary receives the original tool arguments, reuses or creates one raw-output reference before summary work, keeps verified facts authoritative, and synchronously attempts a bounded single-call or Map-Reduce summary within 12 seconds. A new Tool Output settings section configures the dedicated model and keyring secret.

## Technical Context

**Language/Version**: Python 3.11+ / runtime 3.12; React 18 + TypeScript/Vite
**Primary Dependencies**: `AgentLoop`, `ToolOutputRepository`, `LangChainLLMClient`, `TraceContext`, unified config, keyring, pytest, Vitest
**Storage**: Existing SQLite metadata/private blobs and persisted message content; no migration
**Performance Goals**: 12-second total summary budget, at most 6 map calls with concurrency 3, visible result at most `visible_char_cap`
**Constraints**: exactly-one result pairing, fail-open deterministic fallback, no plaintext secret fallback, no raw prompt/output in ordinary logs or UI events

## Constitution Check

| Principle | Status | Evidence |
|-----------|--------|----------|
| Layering | PASS | UI uses typed settings API; business summary code uses Repository/config boundaries. |
| Data discipline | PASS | Existing `ToolOutputRepository` is reused; no direct SQL or migration. |
| Config/secrets | PASS | All values use unified config; dedicated secret is keyring-only. |
| Verification | PASS | Deterministic extraction, timeout/failure, pairing, leak, settings, and frontend tests are required. |
| Living docs | PASS | Feature artifacts and active architecture/constraints/AI entries are updated. |

## Configuration Contract

Namespace: `agent_tools.output.semantic_summary.*`

| Key | Default | Validation | UI |
|-----|---------|------------|----|
| `enabled` | `true` | boolean | basic |
| `provider` | `anthropic` | supported provider enum | basic |
| `model` | `""` | string; empty disables calls | basic |
| `base_url` | `""` | required for `openai-compatible` | basic |
| `temperature` | `0.2` | 0..2 | basic |
| `trigger_chars` | `20000` | 1000..1,000,000 | advanced |
| `max_input_chars` | `120000` | 1000..1,000,000 | advanced |
| `chunk_chars` | `20000` | 1000..120,000 | advanced |
| `max_map_chunks` | `6` | 1..20 | advanced |
| `map_concurrency` | `3` | 1..10 | advanced |
| `total_timeout_seconds` | `12` | 1..120 | advanced |
| `map_max_tokens` | `500` | 64..4000 | advanced |
| `reduce_max_tokens` | `900` | 64..8000 | advanced |
| `summary_max_chars` | `4000` | 500..20,000 | advanced |

Secret: keyring username `tool_output_summary_api_key`; no config fallback.

## Design

### Governance Flow

1. Parse upgraded envelopes when possible; leave small plain legacy/custom text unchanged.
2. Determine compaction from raw size, truncation/clipping metadata, or an existing reference.
3. Redact the visible object and derive deterministic facts/preview.
4. Reuse an authorized existing reference; otherwise persist the original handler result before summary work when within artifact limits.
5. Resolve an extraction goal from explicit `extractionGoal`, `web_fetch.prompt`, or conservative custom argument inference.
6. Attempt semantic summary using redacted selected text.
7. Validate/redact/bound the semantic JSON. On any failure, omit it and keep deterministic fields/reference.
8. Fit the compact envelope within the existing visible cap and save exactly once.

### Semantic Summarizer

- Tool-aware text extraction prefers stdout/stderr, file content, search matches, web body, and loaded reference content; unknown tools use structured JSON text.
- Over-budget selection allocates 15% head, 35% error/warning contexts, 35% uniform samples, and 15% tail.
- A single chunk uses one summary request with mode `single`.
- Multiple chunks run map calls in a bounded thread pool, then one reduce call. Partial maps continue; all-map or reduce failure returns no semantic summary.
- Every provider request receives only the remaining total deadline and no business retry.
- Prompts identify tool output as untrusted data and require JSON only.
- `TraceContext(source="tool_output_summary")` wraps each provider call.

### Settings

- Extend generic settings descriptor with `advanced`.
- Add section id `tool_output`, masked dedicated secret, advanced disclosure, and connection test action.
- Connection validation instantiates the configured client and performs a minimal bounded call, returning only provider/model metadata.
- Real Grand Tour uses the read-only resolver and existing paid-call budget.

## Files

```text
src/business/agents/tools/
├── output_governance.py
└── semantic_summary.py
src/business/agents/agent_loop.py
src/business/services/settings_service.py
src/business/services/settings_actions_service.py
src/data/config_models.py
src/data/unified_config.py
src/data/credential_resolver.py
src/utils/agent_tool_health.py
src/desktop_api/schemas.py
frontend/src/api/settings.ts
frontend/src/screens/settings/*
tests/business/agents/test_tool_output_semantic_summary.py
tests/business/agents/test_builtin_output_governance.py
tests/integration/test_agent_builtin_tool_contracts.py
tests/integration/test_settings_secret_storage.py
tests/desktop_api/test_settings_api.py
frontend/tests/unit/settings-screen.test.tsx
```

## Test Strategy

- Unit: selection budgets, error-location retention, single/map-reduce, partial maps, invalid JSON, timeout, redaction, injection text, goal inference.
- Governance: all result shapes, reference reuse, over-limit output, load-output re-compaction, deterministic fallback.
- Integration: AgentLoop argument propagation and exactly-one pairing across multiple tools.
- Settings/data/API: defaults/getters, keyring-only secret, connection action, provider validation, descriptor shape.
- Frontend: section navigation, advanced disclosure, save, secret write/delete, connection result and user-readable error.
- Guardrails/docs: provider inventory, AI entry mirrors, active architecture and constraints.


# Tech Debt Report: Assistant Brain Redesign

**Generated**: 2026-05-22
**Feature**: specs/010-assistant-brain-redesign
**Spec Reference**: [spec.md](./spec.md)

## Executive Summary

| Severity | Count | Immediate Action Required |
|----------|-------|---------------------------|
| Critical | 0 | None |
| Large | 1 | Review and prioritize before tuning behavior |
| Medium | 3 | Tasks created in [tasks.md](./tasks.md) |
| Small | 1 cleanup set | Fixed during cleanup |

## Large Issues Requiring Analysis

### [ISSUE-001] Brain tuning constants bypass unified configuration

**Category**: Architecture / Configuration
**Location**: `src/business/brain/context_builder.py`, `src/business/brain/retrieval_service.py`, `src/business/brain/archive_service.py`, `src/business/brain/decay_router.py`, `src/business/brain/background_worker.py`, `src/business/brain/specialist_service.py`
**Related Spec**: CC-006, CC-008; context injection, decay, retrieval, prediction, archive layering, and automatic recruitment behavior.
**Constitution Impact**: Constitution III requires runtime configuration through `get_unified_config()` and forbids hardcoded configuration values. `docs/PROJECT_CONSTRAINTS.md` also says `brain.*` tuning placeholders must go through unified config.

#### Problem Description

Cleanup found several behavior-shaping constants still hardcoded in brain services:

- Context and retrieval scoring weights: relevance, recency, effectiveness, exploration, invalidation penalty, revived-session bonus.
- Exploration and decay thresholds: loaded-count exploration threshold, insight soft-delete threshold.
- Time and size bounds: hot-zone half-life, archive half-life, archive scan limit, summary truncation length, prediction evidence limit.
- Recruitment and prompt-generation defaults: fallback delegation threshold, generated specialist name length, example count, feedback signal limits, LLM temperature.

Some values already use `brain.*` config accessors, but related scoring and lifecycle knobs remain split across modules. That makes behavior difficult to tune safely and creates drift from the feature constraint that all numerical thresholds are placeholders.

#### Impact if Not Addressed

- Brain behavior cannot be tuned consistently after real-world usage without source changes.
- Similar ranking logic can diverge between prompt injection and explicit retrieval.
- The implementation remains partially non-compliant with the configuration discipline in the constitution.
- Future Settings UI exposure would be harder because the authoritative list of knobs is not in one config surface.

#### Options

**Option 1: Centralize BrainTuningConfig (Recommended)**
- **Approach**: Add typed accessors or a `BrainTuningConfig` value object backed by `get_unified_config()`, then route scoring, decay, retrieval, archive, prediction, and recruitment knobs through it.
- **Pros**: Restores constitution compliance, creates one tunable contract, and keeps tests explicit.
- **Cons**: Touches several services and test fixtures.
- **Effort**: M
- **Risk**: Medium

**Option 2: Incremental Config Accessors**
- **Approach**: Add `get_brain_*` accessors only for the constants that currently block near-term tuning, leaving low-risk display/truncation bounds hardcoded for now.
- **Pros**: Smaller change and lower immediate test churn.
- **Cons**: Keeps some split-brain configuration and may require another cleanup pass.
- **Effort**: S
- **Risk**: Low

**Option 3: Defer**
- **Approach**: Document constants as temporary and revisit after first live usage.
- **Pros**: No immediate implementation effort.
- **Cons**: Continues constitution/config drift and makes tuning depend on code edits.
- **Recommended deferral period**: No later than the first post-MVP tuning cycle.

#### Recommendation

Use Option 1 before exposing or tuning any brain behavior outside tests. Add one focused task set that defines the config surface, updates `config.example.json` and `config.example.comments.md`, adjusts affected service constructors/tests, and adds a guardrail proving brain tuning values are not hardcoded outside the config module or test fixtures.

## Cross-References

- **Specification**: [spec.md](./spec.md)
- **Implementation Plan**: [plan.md](./plan.md)
- **Tasks**: [tasks.md](./tasks.md)
- **Constitution**: ../../.specify/memory/constitution.md

## Next Steps

1. Review ISSUE-001 and choose a remediation option.
2. Implement the medium TD tasks in [tasks.md](./tasks.md).
3. Create implementation tasks for the approved config-centralization approach.
4. Re-run `/speckit.implement` and `/speckit.cleanup` after remediation.

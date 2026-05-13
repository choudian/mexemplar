# Tech Debt Report: UI Stack Redesign

**Generated**: 2026-05-13
**Feature**: `specs/008-ui-stack-redesign`
**Spec Reference**: `specs/008-ui-stack-redesign/spec.md`

## Executive Summary

| Severity | Count | Immediate Action Required |
|----------|-------|---------------------------|
| Critical | 0 | None |
| Large | 1 | Review and prioritize |
| Medium | 1 | Task created in `tasks.md` |
| Small | 4 | Fixed during cleanup |

## Large Issues Requiring Analysis

### [ISSUE-001] Health Probe SQL Boundary

**Category**: Architecture
**Location**: `src/business/services/desktop_health_service.py`
**Related Spec**: FR-020, CC-002, CC-003
**Constitution Impact**: Principle II requires business data to go through repositories and says business code must not spell SQL directly.

#### Problem Description

`DesktopHealthService._probe_sqlite()` imports SQLAlchemy `text` and executes `SELECT 1` directly to prove SQLite availability. The query is static and does not touch user data, but it still sits in a business service and bypasses the repository/data-access boundary. This makes the health-check exception implicit rather than documented and weakens the guardrail around direct SQL in business code.

#### Impact if Not Addressed

- Future health checks may expand from a harmless probe into real business-data SQL.
- Reviewers cannot distinguish intentional infrastructure probes from forbidden business SQL.
- Architecture guard tests have no clean boundary to enforce for desktop health checks.

#### Options

**Option 1: Move Probe Behind Data-Layer Health API (Recommended)**
- **Approach**: Add a data-layer method such as `SqlAlchemyManager.health_check()` or a dedicated repository/data service that owns the `SELECT 1`; make `DesktopHealthService` call that method.
- **Pros**: Preserves layered boundaries and gives guard tests a clear allowed surface.
- **Cons**: Adds a small data-layer API for an infrastructure concern.
- **Effort**: S
- **Risk**: Low

**Option 2: Document A Narrow Exception**
- **Approach**: Keep the direct probe but document it in `docs/PROJECT_CONSTRAINTS.md` as a non-data infrastructure readiness exception.
- **Pros**: Minimal code churn.
- **Cons**: Leaves direct SQL in business code and creates a precedent that needs careful policing.
- **Effort**: S
- **Risk**: Medium

**Option 3: Defer**
- **Approach**: Leave the current implementation and revisit when desktop health checks expand.
- **Pros**: No immediate effort.
- **Cons**: Debt becomes easier to copy into future probes.
- **Recommended deferral period**: No later than the next desktop health or sidecar reliability change.

#### Recommendation

Choose Option 1. Move the probe behind a data-layer-owned health API and add a guard test that rejects direct SQL imports in `src/business/services/desktop_health_service.py` while allowing the data-layer probe.

## Cross-References

- **Specification**: `specs/008-ui-stack-redesign/spec.md`
- **Implementation Plan**: `specs/008-ui-stack-redesign/plan.md`
- **Tasks**: `specs/008-ui-stack-redesign/tasks.md`
- **Constitution**: `.specify/memory/constitution.md`

## Next Steps

1. Review ISSUE-001 before the next feature iteration.
2. Implement TD001 when refactoring desktop API runtime ownership.
3. Decide whether ISSUE-001 should be fixed immediately or tracked as the next architecture cleanup task.
4. Re-run `/speckit.cleanup` after remediation.

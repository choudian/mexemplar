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
| Post-fix | 6 bugs + 5 enhancements | Applied in commit 1b4777f, see below |

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

---

## Post-Implementation Fixes (2026-05-23)

Commit `1b4777f` 在 010 文档定稿后进行了多项修复和增强，以下为记录。

### Bug Fixes Applied

| ID | Category | Location | Description |
|----|----------|----------|-------------|
| FIX-001 | Batch Execution | `src/business/agents/agent_loop.py` | 批次执行中断策略修复：新增 `has_side_effects` 标记到 `ToolDefinition`；当前标记为无副作用的工具（web_search、web_fetch、read_file、list_dir、动态用户工具、组合工具、搜索工具）失败时不再级联中断后续调用。动态用户工具/组合工具的无副作用分类是当前实现默认值；后续若有逐工具元数据，应按真实行为设置 `has_side_effects`。 |
| FIX-002 | Distillation | `src/business/brain/distillation_service.py` | 空结果处理修复：所有请求分区条目为空时，不再标记 `completed`，而是调用 `_retry_or_fail_segment()` 走标准重试/失败路径。 |
| FIX-003 | Distillation | `src/business/brain/distillation_service.py` | Zone key 容错：distillation 输出包含未请求的分区 key 时，视为 out-of-schema producer output，记录 warning 并忽略未知 key，继续处理已请求的 active-zone payload；这不改变“未激活分区不进入 schema”的规格约束。 |
| FIX-004 | Prediction | `src/business/brain/prediction_service.py` | 验证响应解析收紧：`_parse_verification_response()` 改为仅匹配前缀（`startswith`），避免响应文本中间含 "hit"/"miss" 等词导致误判。 |
| FIX-005 | Session Recovery | `src/business/agents/agent_loop.py` | 会话恢复扩展：`suspended` 状态的会话现在也能被恢复为 `active`（此前只处理 `completed` 和 `failed`）。 |
| FIX-006 | Validation | `src/desktop_api/routers/brain.py` | 条目编辑空内容防护 + 专员创建 tool_whitelist 类型清洗（仅保留非空字符串）。 |

### Enhancements Applied

| ID | Category | Location | Description |
|----|----------|----------|-------------|
| ENH-001 | Auto-Approve | `frontend/src/screens/assistant/MessageComposer.tsx`, `ConfirmationToast.tsx`, `src/desktop_api/routers/assistant.py` | 新增"全部允许"功能：MessageComposer 输入栏 Toggle + ConfirmationToast "全部允许"按钮 + 后端 `POST /api/assistant/confirmations/auto-approve` 端点。会话级内存状态，不持久化。 |
| ENH-002 | Summary Messages | `frontend/src/screens/assistant/AssistantScreen.tsx`, `src/data/repos/message_repository.py` | 新增 `summary` 消息角色：压缩后产生的摘要以可折叠 `<details>` 展示；`_display_filter` 支持 `compressed + summary` 组合。 |
| ENH-003 | Builtin Tool Deps | `src/execution/tool_executor.py`, `src/business/agents/tools/builtin_general_tools.py` | 内置工具依赖走 `tool_venv`：新增 `BUILTIN_TOOL_DEPS` + `ensure_builtin_deps()`，`web_search` 改为在 `tool_venv` 子进程执行。应用启动时预装依赖。 |
| ENH-004 | Telemetry | `src/business/orchestration/agent/teaching_failure_tracker.py` | 教学失败追踪器增强日志：补全 agent_error 接收、非教学 agent 跳过、workflow_id 缺失等关键节点的 info/warning 级别日志。 |
| ENH-005 | Logging | `src/desktop_api/__main__.py` | Sidecar 启动时激活文件日志（`data/logs/mexemplar.log`），verbose 模式下用 DEBUG 级别。 |

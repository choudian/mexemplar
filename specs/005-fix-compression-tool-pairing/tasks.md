# Tasks: 修复上下文压缩 tool_call/tool_result 配对断裂

**Input**: Design documents from `/specs/005-fix-compression-tool-pairing/`
**Prerequisites**: plan.md (required), spec.md (required)
**Bugfix**: 2026-04-27 — [BUG-ADHOC] 修正空压缩区语义、补足 compatibility 回归测试，并收敛并行标记。

**Tests**: Constitution IV 要求"改静默失败路径必须补测试"，本 feature 必须包含测试。

**Organization**: 按 User Story 组织，每个 story 独立可测。

## Constitution-Driven Minimums

- ✅ 无 SQLite/DuckDB schema 变更
- ✅ 无新配置项
- ✅ 补充压缩/上下文管理测试（当前无任何测试覆盖，且需覆盖 compatibility regression）
- ✅ 更新 `docs/ARCHITECTURE.md` 压缩流程描述

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Project Paths

- **Source**: `src/` at repository root
- **Tests**: `tests/` at repository root
- **Test runner**: `uv run pytest tests/`
- **Formatter**: `uv run black src/ tests/`
- **Linter**: `uv run flake8 src/ tests/`

---

## Phase 1: Setup

**Purpose**: 创建测试目录和共享 fixture

- [x] T001 创建测试目录 `tests/business/memory/` 并添加 `__init__.py`
- [x] T002 在 `tests/business/memory/conftest.py` 中创建共享 fixture：mock Message 工厂函数（支持指定 role、tool_calls、tool_call_id、sequence）和 mock MessageRepository

---

## Phase 2: User Story 1 - 长会话压缩后 Agent 不再崩溃 (P1) 🎯 MVP

**Goal**: 修复 _split_messages 边界调整，跨越压缩/保留边界的 tool 组整体移入保留区

**Independent Test**: 构造 tool 组跨越边界的消息列表，调用 compress，验证返回消息中无孤立 tool result

### Tests for User Story 1

- [x] T003 [P] [US1] 在 `tests/business/memory/test_compression_tool_pairing.py` 编写边界调整测试：test_no_tool_groups_in_compress（无 tool 组 → 不调整）、test_tool_group_fully_in_compress（tool 组完全在压缩区 → 不调整）、test_tool_group_straddles_boundary（assistant 在压缩区、部分 tool result 在保留区 → 整组移入保留区）

### Implementation for User Story 1

- [x] T004 [US1] 在 `src/business/memory/compression_handler.py` 新增 `_adjust_boundary_for_tool_pairs(self, compress_msgs: List[Message], keep_msgs: List[Message]) -> Tuple[List[Message], List[Message]]`：收集 keep_msgs 中 tool role 的 tool_call_id，从 compress_msgs 末尾向前查找包含这些 id 的 assistant(tool_calls) 消息，将该 assistant 消息及压缩区内属于同一 tool 组的连续 tool result 消息整体移入 keep_msgs 前部

- [x] T005 [US1] 在 `src/business/memory/compression_handler.py` 的 `_split_messages` 方法中，在现有 compress_msgs/keep_msgs 划分后调用 `_adjust_boundary_for_tool_pairs` 替换原结果

- [x] T006 [US1] 在 `src/business/memory/compression_handler.py` 的 `compress` 方法中，增加边界调整后 compress_msgs 为空的处理：跳过 LLM 调用和持久化，直接返回 `system + keep_msgs`

- [x] T007 [US1] 在 `tests/business/memory/test_compression_tool_pairing.py` 补充测试：test_tool_group_assistant_in_compress_all_results_in_keep（assistant 在压缩区、全部 tool result 在保留区）、test_multiple_tool_groups_only_last_straddles（多个 tool 组仅最后一个跨越边界）

**Checkpoint**: 边界调整逻辑完成，tool 组不再被拆分

---

## Phase 3: User Story 2 - 多次压缩不累积残留 (P2)

**Goal**: 验证被保留的边界 tool 组在二次压缩时能被正常压缩

### Tests for User Story 2

- [x] T008 [P] [US2] 在 `tests/business/memory/test_compression_tool_pairing.py` 补充测试：test_re_compress_absorbs_previous_boundary_group（上一轮保留的 tool 组在二次压缩时完全在压缩区内部 → 正常压缩，不重复保留）、test_empty_compress_after_adjustment（调整后压缩区为空 → 跳过压缩）

**Checkpoint**: 多次压缩场景验证通过，tool 组不累积

---

## Phase 4: User Story 3 - 压缩后"继续"能正常恢复 (P3)

**Goal**: assemble_context 兜底校验，检测并剔除孤立 tool result

### Tests for User Story 3

- [x] T009 [P] [US3] 在 `tests/business/memory/test_context_orphan_cleanup.py` 编写上下文兼容性回归测试：test_no_orphans（无孤立 → 不变）、test_orphan_tool_result_removed（孤立 tool result → 剔除）、test_mixed_valid_and_orphan（有效保留、孤立剔除）、test_warning_logged（剔除时记 warning 日志）、test_reference_handler_still_applies_after_cleanup（边界保留的大 tool result 仍可被引用替换）、test_pending_tool_calls_unchanged_after_orphan_cleanup（清理孤立 tool result 不影响未配对 tool_call 检测）

### Implementation for User Story 3

- [x] T010 [US3] 在 `src/business/memory/context_manager.py` 新增 `_cleanup_orphan_tool_results(self, messages: List[Message]) -> List[Message]`：收集所有 assistant(tool_calls) 中的 id 集合，过滤掉 tool_call_id 不在该集合中的 tool 消息，剔除时 logger.warning

- [x] T011 [US3] 在 `src/business/memory/context_manager.py` 的 `assemble_context` 方法中，在压缩后、引用替换前调用 `_cleanup_orphan_tool_results`

**Checkpoint**: 兜底校验完成，即使边界调整有遗漏也不会发 400

---

## Phase 5: Polish & Cross-Cutting Concerns

- [x] T012 更新 `docs/ARCHITECTURE.md` 中压缩流程描述，说明边界调整步骤和孤立校验
- [x] T013 [P] 更新 `CLAUDE.md` 中"当前代码现实"部分，补充压缩边界调整和孤立校验的描述
- [x] T014 运行 `uv run pytest tests/business/memory/` 验证所有测试通过
- [x] T015 [P] 运行 `uv run black src/business/memory/ tests/business/memory/` 和 `uv run flake8 src/business/memory/ tests/business/memory/` 确保格式和规范

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: 无依赖，立即开始
- **Phase 2 (US1)**: 依赖 T001-T002
- **Phase 3 (US2)**: 依赖 Phase 2（补充测试，同一文件）
- **Phase 4 (US3)**: 依赖 T001-T002（可与 Phase 2/3 并行）
- **Phase 5 (Polish)**: 依赖所有前置 Phase

### User Story Dependencies

- **US1 (P1)**: 核心修复，无跨 story 依赖
- **US2 (P2)**: US1 的自然验证延伸，依赖 US1 实现
- **US3 (P3)**: 独立兜底层，可与 US1/US2 并行

### Parallel Opportunities

- T001 完成后开始 T002
- T003, T009 可并行（不同测试文件）
- T004-T007 顺序执行（同一文件递进修改）
- T010, T011 顺序执行（同一文件递进修改）
- T012, T013, T015 可并行

---

## Parallel Example: Phase 2 + Phase 4 并行

```bash
# 开发者 A：US1 边界调整
Task T003: "边界调整测试 test_compression_tool_pairing.py"
Task T004: "实现 _adjust_boundary_for_tool_pairs"
Task T005: "接入 _split_messages"
Task T006: "处理空压缩区"

# 开发者 B（并行）：US3 兜底校验
Task T009: "孤立校验测试 test_context_orphan_cleanup.py"
Task T010: "实现 _cleanup_orphan_tool_results"
Task T011: "接入 assemble_context"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: 创建测试目录和 fixture（T001-T002）
2. Phase 2: 实现边界调整 + 测试（T003-T007）
3. **STOP and VALIDATE**: 运行测试，构造边界场景验证
4. 此时核心 bug 已修复

### Full Delivery

1. MVP（Phase 1 + 2）
2. Phase 3: 补充二次压缩测试（T008）
3. Phase 4: 兜底校验（T009-T011）
4. Phase 5: 文档更新 + 全量验证（T012-T015）

---

## Notes

- 本 feature 改动集中在 `compression_handler.py` 和 `context_manager.py`，无跨层影响
- 所有测试使用 mock Message 和 mock MessageRepository，不依赖真实 DB
- 压缩区的 tool 组识别依赖 AgentLoop 保证的消息连续性（见 spec Assumptions）

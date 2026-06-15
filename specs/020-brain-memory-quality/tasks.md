---
description: "Migrated task list for brain memory quality prompt improvements"
---

# Tasks: 大脑记忆质量提示词升级

**Input**: Reverse-engineered implementation and [plan.md](./plan.md)  
**Status**: migrated — implementation predates these artifacts  
**Tests**: 既有行为测试存在；新增 prompt regression coverage 尚未完成。

## Phase 1 - Segment 沉淀质量

- [X] T001 [US1] 在 `src/business/brain/distillation_service.py` 增加面向未来使用价值的记忆筛选标准
- [X] T002 [US1] 增加自包含、一条一事、宁缺毋滥和低质量输出反例
- [X] T003 [US1] 为 hot/persistent/archive/subconscious/failure 分区增加判断问题和示例
- [X] T004 [US1] 明确允许无合格内容时返回空数组，并保留 `distillation_output` 工具调用
- [X] T005 [US1] 将 feedback signal 限定为参考指导，避免逐条复制为新记忆

## Phase 2 - 潜意识模式质量

- [X] T006 [US2] 在 `src/business/brain/distillation_service.py` 将潜意识条目限定为跨对话重复模式
- [X] T007 [US2] 增加至少两条不同对话证据的 prompt 指导
- [X] T008 [US2] 排除单次事件、明确偏好、宽泛人格判断和对话过程描述
- [X] T009 [US2] 要求潜意识 `content` 可支持预判，`reason` 指向支撑记忆

## Phase 3 - Prediction 质量与验证

- [X] T010 [US3] 在 `src/business/brain/prediction_service.py` 强化具体、可证伪和带时间窗的预测规则
- [X] T011 [US3] 要求预测至少由两条记忆支撑，并允许依据不足时返回空结果
- [X] T012 [US3] 明确 `hit`、`partial`、`miss`、`expired` 四种验证前缀的语义
- [X] T013 [US3] 保持既有 prediction tool schema、parser 和 worker 行为不变

## Phase 4 - Spec Kit 迁移文档

- [X] T014 创建 `specs/020-brain-memory-quality/spec.md` 并标记为 Migrated
- [X] T015 创建 `specs/020-brain-memory-quality/plan.md`，记录实际设计和 constitution check
- [X] T016 创建 `specs/020-brain-memory-quality/tasks.md`，区分已实现项和测试缺口
- [X] T017 创建 `specs/020-brain-memory-quality/checklists/requirements.md`

## Phase 5 - Verification Gaps

- [ ] T018 [P] [US1] 在 `tests/business/brain/test_distillation_service.py` 增加 P1/P2/P4 prompt 边界和关键质量规则回归测试
- [ ] T019 [P] [US2] 在 `tests/business/brain/test_prediction_worker.py` 增加潜意识重复证据、反例和空结果指导回归测试
- [ ] T020 [P] [US3] 在 `tests/business/brain/test_prediction_worker.py` 增加 prediction 生成约束与四状态验证语义回归测试
- [X] T021 运行 `uv run pytest tests/business/brain/test_distillation_service.py tests/business/brain/test_prediction_worker.py -q`（41 passed，7 个既有弃用警告）

## Identified Gaps

1. “至少两条记忆/不同对话证据”目前只是 prompt 软约束，schema 和业务逻辑没有确定性校验。
2. 当前测试验证结构化解析、持久化和 worker 行为，但未锁定新增 prompt 质量规则。
3. 没有离线样本集或人工评分基线，暂时无法量化提示词升级对 precision/recall 的实际改善。

## Dependencies

- T018、T019、T020 可并行实施。
- T021 已在迁移时运行，用于确认现有结构化解析、持久化和 worker 行为没有回归。
- T018-T020 完成后应再次运行同一聚焦测试命令。
- 本 feature 不依赖 migration、Repository、API、事件、配置、前端或 Tauri 任务。

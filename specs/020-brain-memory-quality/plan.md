# Implementation Plan: 大脑记忆质量提示词升级

**Branch**: `020-brain-memory-quality` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)  
**Status**: Migrated from an implementation completed before Spec Kit artifacts were created.

## Summary

在不改变大脑数据模型、结构化输出 schema 和后台 worker 行为的前提下，重写三类 LLM 指令：

1. Segment 多分区沉淀：加入价值判断、自包含、一条一事、宁缺毋滥、分区判断问题和正反例。
2. 周期性潜意识沉淀：要求跨对话重复证据，排除单次事件、明确偏好和宽泛人格标签。
3. Prediction 生成/验证：要求具体、可证伪、有验证时机且至少两条记忆支撑，并明确四种验证状态。

实现仅涉及 `src/business/brain/distillation_service.py` 和
`src/business/brain/prediction_service.py` 中的 prompt builder。

## Technical Context

**Language/Version**: Python 3.11+（运行时 3.12）  
**Primary Dependencies**: 现有 LLM client、BrainRepository、BrainBackgroundWorker  
**Storage**: N/A — 不改变持久化  
**Testing**: pytest；现有 brain 行为测试 + 待补 prompt regression tests  
**Target Platform**: Tauri 2 桌面应用中的 Python sidecar  
**Project Type**: Desktop app，business-only change  
**Performance Goals**: 不增加 LLM 调用次数；仅增加少量 prompt token  
**Constraints**: 保持 phase-aware schema、tool 名称、重试、事务和 worker 调度兼容  
**Scale/Scope**: 2 个 Python 业务文件，4 个 prompt 构建路径

## Constitution Check

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. 分层边界与事件协调 | 是否保持依赖方向且事件契约不被绕过？ | 通过。只改 `src/business/brain/` 内部 prompt；无新依赖、事件或监听器。 |
| II. 数据边界与持久化纪律 | 是否改变 SQLite/DuckDB 或绕过 Repository？ | 通过。无数据模型、SQL、Repository、migration 或 DuckDB 改动。 |
| III. 统一配置与密钥安全 | 是否新增配置或 secret 路径？ | 通过。无新增配置和 secret；prompt 不包含运行时凭据。 |
| IV. 可验证交付 | 是否覆盖确定性行为和静默失败风险？ | 部分完成。既有 worker/schema 行为测试存在且应回归；新增 prompt 质量规则尚缺专门 regression tests，已在 tasks 中作为 gap 保留。 |
| V. 活文档与规格驱动交付 | 是否补齐规格并识别活文档影响？ | 通过。补录 `spec/plan/tasks/checklist`；运行结构和开发约束未变，因此无需修改活文档。 |

## Project Structure

### Documentation

```text
specs/020-brain-memory-quality/
├── checklists/
│   └── requirements.md
├── plan.md
├── spec.md
└── tasks.md
```

未生成以下产物：

- `research.md`：没有待决技术选型，实际实现沿用现有 prompt builder 和结构化 tool call。
- `data-model.md`：没有实体、字段、状态或持久化变化。
- `contracts/`：没有 API、事件、tool schema 或跨模块契约变化。
- `quickstart.md`：没有新的运行、配置或手工验收入口。

### Source Code

```text
src/business/brain/
├── distillation_service.py  # Segment 与潜意识沉淀 prompt
└── prediction_service.py    # Prediction 生成与验证 prompt

tests/business/brain/
├── test_distillation_service.py  # 既有 schema/事务/all-empty 行为测试
└── test_prediction_worker.py     # 既有生成/验证/worker 行为测试
```

**Structure Decision**: 保持现有 service 内私有 prompt builder，不增加 prompt abstraction。
当前只有少量紧密绑定业务流程的字符串，抽取新模块不会减少实质复杂度。

## Reconstructed Implementation Approach

### Phase 1 - Segment 沉淀质量规则

- 将“提取重要信息”改为面向未来使用价值的筛选问题。
- 增加自包含、一条一事和宁缺毋滥三项质量标准。
- 为聊天过程摘要、通用知识、宽泛印象和单次事件误判提供反例。
- 按 P1/P2/P4 继续增量拼接已激活 zone 的规则。
- 将 `reason` 定义为未来使用场景，而不只是抽象的“为什么值得保留”。
- 将 feedback signal 限定为参考指导，避免被机械复制成新记忆。

### Phase 2 - 潜意识模式质量规则

- 将潜意识条目定义为跨对话重复出现的行为模式。
- 要求至少两条不同对话证据，但保持为 prompt 软约束。
- 明确排除单次事件、用户已明确说出的偏好、泛化人格判断和对话过程描述。
- 要求 `content` 包含可用于预判的具体模式，`reason` 指向支撑记忆。

### Phase 3 - Prediction 质量与验证语义

- 生成 prompt 强调具体行动、可证伪和 `verification_checkpoint`。
- 要求至少两条记忆支撑，没有依据时允许空结果。
- 验证 prompt 明确四种前缀的判定含义，保持既有 startswith parser 兼容。

## Compatibility Assessment

- Prompt 更长会增加少量输入 token，但不新增模型调用。
- 结构化输出 tool 名称和 schema 未改，现有解析代码保持兼容。
- “允许空数组”与现有 Segment all-empty 重试并存：prompt 允许模型诚实返回空结果，
  service 仍按 010 feature 的既有规则执行一次额外重试。
- “至少两条证据”没有确定性校验，模型仍可能违反；本计划不虚构硬保证。

## Test Strategy

### Existing Coverage

- `tests/business/brain/test_distillation_service.py` 覆盖 phase schema、输出验证、
  all-empty 重试和事务写入。
- `tests/business/brain/test_prediction_worker.py` 覆盖预测生成、验证、重试回退、
  潜意识写入和 worker 调度。

### Identified Gap

现有测试不锁定本 feature 新增的 prompt 质量规则。后续应添加低脆弱性的 regression tests，
断言关键语义标记和 phase 边界，而不是逐字符快照整个 prompt：

- P1/P2/P4 各自包含正确 zone，且低 phase 不包含未激活 zone。
- Segment prompt 包含空结果许可、低质量反例和 feedback signal 限定。
- 潜意识 prompt 包含重复证据要求和证据来源要求。
- Prediction prompt 包含两条证据、可证伪、checkpoint 和四状态语义。

## Active Documentation

无需更新 `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md` 或 AI 入口镜像：
运行结构、边界、配置和公开行为契约均未变化。新的需求与实施记录保留在本 feature 规格中。

## Complexity Tracking

无 constitution 例外。测试缺口不是获批例外，已作为未完成任务显式保留。

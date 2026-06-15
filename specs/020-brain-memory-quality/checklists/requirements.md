# Requirements Quality Checklist: 大脑记忆质量提示词升级

**Purpose**: 验证迁移规格准确描述已实现行为、软约束边界和测试缺口  
**Created**: 2026-06-15  
**Feature**: [spec.md](../spec.md)

## Specification Quality

- [x] CHK001 已说明这是实现后补录的 migrated specification
- [x] CHK002 用户故事按记忆提取、潜意识模式和 prediction 自校准拆分
- [x] CHK003 每个用户故事都有独立测试方法和 Given/When/Then 验收场景
- [x] CHK004 功能需求描述可观察的 prompt 契约，没有绑定不必要的内部实现细节
- [x] CHK005 成功标准包含可自动验证的 regression coverage 目标

## Accuracy And Boundaries

- [x] CHK006 已明确“至少两条证据”是 prompt 软约束，不是运行时硬保证
- [x] CHK007 已明确空数组许可与既有 all-empty retry 可以同时成立
- [x] CHK008 已明确 tool schema、phase、Repository、worker、重试和解析行为保持不变
- [x] CHK009 已明确 feedback signals 只作为参考，不应被机械转换为记忆
- [x] CHK010 已覆盖低 phase 不应出现未激活 zone 指导的边界

## Constitution Compliance

- [x] CHK011 仅影响 business 层，未改变分层依赖方向
- [x] CHK012 无 SQLite、DuckDB、Repository、migration 或直接 SQL 变化
- [x] CHK013 无配置、secret、API、事件或前端契约变化
- [x] CHK014 已识别缺少 prompt regression tests，未把现有行为测试误报为完整覆盖
- [x] CHK015 已说明活文档无需更新的理由

## Artifact Scope

- [x] CHK016 `spec.md`、`plan.md`、`tasks.md` 已纳入迁移范围
- [x] CHK017 已说明不生成 research、data-model、contracts 和 quickstart 的理由
- [x] CHK018 未修改现有业务实现或用户未提交的代码

## Open Gaps

- [x] CHK019 Prompt 回归测试缺口已在 tasks T018-T020 中保持未完成状态，既有聚焦测试已记录结果
- [x] CHK020 缺少离线质量评测基线已如实记录，未虚构改善比例

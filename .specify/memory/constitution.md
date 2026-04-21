<!--
Sync Impact Report
Version change: template -> 1.0.0
Modified principles:
- Principle slot 1 -> I. 分层边界与事件协调
- Principle slot 2 -> II. 数据边界与持久化纪律
- Principle slot 3 -> III. 统一配置与密钥安全
- Principle slot 4 -> IV. 可验证交付
- Principle slot 5 -> V. 活文档与规格驱动交付
Added sections:
- Engineering Guardrails
- Workflow & Review
Removed sections:
- None
Templates requiring updates:
- UPDATED .specify/templates/plan-template.md
- UPDATED .specify/templates/spec-template.md
- UPDATED .specify/templates/tasks-template.md
- UPDATED docs/README.md
- UPDATED docs/PROJECT_CONSTRAINTS.md
- UPDATED agent.md
- UPDATED CLAUDE.md
- UPDATED CONTRIBUTING.md
Follow-up TODOs:
- None
-->
# Mexemplar Constitution

## Core Principles

### I. 分层边界与事件协调
Mexemplar 的实现 MUST 保持清晰的依赖方向：`UI -> business -> data/driver`。下层代码 MUST
NOT 反向依赖上层；跨模块通知 MUST 使用 `src/utils/events.py` 中定义的 `blinker`
事件；仅在同一模块内或需要同步返回值时才允许直接方法调用。事件监听器 MUST 快速返回，
不得承担长时间阻塞任务；耗时逻辑 MUST 交给后台任务、worker 或后续编排阶段。Rationale:
这条原则保证录制、编排、UI 与存储之间保持低耦合，减少线程问题和静默接线错误。

### II. 数据边界与持久化纪律
业务数据 MUST 存放在 SQLite 并经 Repository 访问；业务代码 MUST NOT 直接拼写 SQL。
录制与分析数据 MUST 存放在 DuckDB；凡读取 `network_requests` 的能力 MUST 继续经过
`sql_rewriter` 或 `FilteredDuckDBConnection` 暴露的过滤/脱敏边界，任何例外 MUST 在
plan 中显式说明。涉及 schema、序列化、迁移或回填的变更 MUST 同步给出兼容性方案。
Rationale: Mexemplar 同时承载事务型业务数据和分析型录制数据，边界失守会快速演化成隐蔽
的数据损坏、泄漏或回归。

### III. 统一配置与密钥安全
所有运行时配置 MUST 通过 `get_unified_config()` / `UnifiedConfigManager` 读写；
代码 MUST NOT 直接读取配置文件，也 MUST NOT 在模块中硬编码配置值。API Key 和其他
敏感信息 MUST 存放在 keyring 或同等级安全存储中，绝不能进入源码、示例配置或普通日志。
新增配置项 MUST 同步更新默认值、配置模板、必要的 UI 暴露和相关文档。Rationale: 配置
和凭据分散会导致热更新失效、环境漂移和安全事故。

### IV. 可验证交付
确定性逻辑、静默失败风险高的编排、数据转换与持久化代码 MUST 配备自动化测试。任何架构
接线替换 MUST 同时新增链路冒烟测试和门卫测试，以证明新路径已生效且旧路径已移除。LLM
Prompt 或非确定性行为可以依赖集成测试与运行期观测，而不是强求单元测试；但用户可见流程
仍 MUST 具备可验证的验收路径。进入合并前，相关测试、格式化和静态检查 MUST 通过，或在
plan/PR 中留下明确的例外说明。Rationale: 这个项目的高风险错误往往不是崩溃，而是“看起来
能跑、实际上接错了线”。

### V. 活文档与规格驱动交付
非琐碎功能开发 MUST 在实现前形成受版本控制的规格与计划，优先通过 Speckit 在 `specs/`
下维护 `spec.md / plan.md / tasks.md`；只有小修复或纯文案类改动才可以跳过，并且 MUST
在提交上下文中说明理由。活文档包括 `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md`、
`.specify/memory/constitution.md`、贡献/Agent 指引以及受影响的用户文档，它们 MUST 在
任务结束时与当前代码一致。临时过程材料 MUST 放在 `docs/local/`；设计决策记录 SHOULD 放在
`docs/design/`，且不作为“当前真相”。Rationale: Mexemplar 依赖长期演进的 AI 工作流，
没有规格和活文档同步就无法稳定协作、评审和回溯。

## Engineering Guardrails

- 当前主实现栈为 Python 3.11+、PyQt6、SQLite、DuckDB、Playwright、blinker 与自研
  AgentLoop；涉及这些基础设施的改动 MUST 先说明兼容性影响。
- 受 Speckit 管理的功能分支 SHOULD 使用 `NNN-short-name` 或时间戳前缀命名，并将特性
  文档放在对应的 `specs/<branch-prefix>-<short-name>/` 目录。
- 新事件 MUST 在 `src/utils/events.py` 统一定义；新配置 MUST 走统一配置管理；新增敏感
  字段 MUST 明确安全存储与脱敏策略。
- UI 代码 MUST 通过 Service、Bridge 或业务层访问下层能力，不得直接触达 Repository 或
  其他底层存储实现。
- Reviewer MUST 拒绝以下提交：向上层反向依赖、绕过过滤边界读取录制数据、硬编码密钥、
  直接读写配置文件、以及未记录例外原因的测试/文档缺口。

## Workflow & Review

1. 非琐碎功能开发 SHOULD 按 `/speckit.specify -> /speckit.clarify -> /speckit.plan -> /speckit.tasks -> /speckit.analyze -> /speckit.implement`
   的顺序推进；若跳过某一步，必须在计划、PR 或提交说明中记录原因。
2. 每份实现计划 MUST 标明受影响的层、事件、数据存储、配置/密钥、测试与文档更新点。
3. 每次评审 MUST 检查 Constitution Check、测试覆盖、文档同步、迁移/配置影响，以及是否
   出现新的反模式。
4. 合并前 SHOULD 运行与变更相关的 `uv run pytest tests/`、`uv run black ...` 与
   `uv run flake8 ...`；若某项暂时不能运行，说明中 MUST 写明原因、风险和补救计划。
5. 过程性草稿、调研记录和一次性计划 MUST 留在 `docs/local/`；只有对当前系统仍然有效的
   结论才进入活文档。

## Governance

本宪法高于 README、CONTRIBUTING、Agent 指引与 Speckit 模板中的冲突性表述。任何原则
变更都 MUST 通过显式修改本文件完成，并在同一变更中同步更新受影响的模板、活文档和流程
说明。版本号采用语义化规则：删除或重定义原则使用 MAJOR；新增原则或显著强化门禁使用
MINOR；文字澄清与非语义修订使用 PATCH。每次计划评审和合并评审都 MUST 做合规检查；
如存在例外，必须在计划或 PR 中明示，而不是默默绕过。

**Version**: 1.0.0 | **Ratified**: 2026-04-21 | **Last Amended**: 2026-04-21

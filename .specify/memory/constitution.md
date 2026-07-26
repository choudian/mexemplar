<!--
Sync Impact Report
Version change: 3.0.0 -> 3.1.0
Modified principles:
- Engineering Guardrails: registered the 033 Scheduling Center CC-005 controlled
  exception for persistent per-task unattended approval, including its scope,
  UI-only activation, tool non-exposure, and fail-closed decision ordering
Added sections:
- None
Removed sections:
- None
Templates requiring updates:
- None (existing templates remain compatible)
Follow-up TODOs:
- None
-->
# Mexemplar Constitution

## Core Principles

### I. 分层边界与事件协调
Mexemplar 的实现 MUST 保持清晰的依赖方向：`UI -> business -> execution -> data/driver`。
`execution` 层负责代码执行沙箱等运行时能力，与业务编排层同级但在 data 之上。下层代码 MUST
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
`UnifiedConfigManager` 之外的代码 MUST NOT 直接读取配置文件，也 MUST NOT 在模块中
硬编码配置值。API Key 和其他敏感信息同样 MUST 由 `UnifiedConfigManager` 管理：
`config.json` MAY 提供本地默认值，SQLite `app_settings` MAY 提供运行时覆盖；其他模块
MUST NOT 绕过管理器直接读写这两个存储。

secret 的真实值 MUST NOT 进入源码、普通日志、明文响应 DTO、UI event 或前端持久化状态；
Settings/API 只能返回存在性和遮罩值，配置示例中的 secret MUST 保持为空。普通配置日志
MUST 对已登记的敏感字段脱敏。Real Grand Tour 与普通运行时使用同一组只读配置 getter，
不得引入独立凭据解析或隐式迁移路径。

新增配置项 MUST 同步更新默认值、配置模板、必要的 UI 暴露和相关文档。Rationale: 配置
和凭据分散会导致热更新失效、环境漂移和安全事故；统一入口、遮罩输出和日志脱敏必须可测试。

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

- 当前主实现栈为 Python 3.11+（运行时 3.12）、Tauri 2 + React 18 + TypeScript/Vite、
  FastAPI sidecar、Rust stable、SQLite（SQLAlchemy / Alembic 迁移）、DuckDB、
  Playwright、blinker、sqlglot、LangChain、mitmproxy 与自研 AgentLoop；浏览器扩展使用
  JavaScript（`src/recording/browser_extension/`）。旧 PyQt UI 已退休，不得恢复正常用户可触达
  的 PyQt fallback；涉及这些基础设施的改动 MUST 先说明兼容性影响。
- 受 Speckit 管理的功能分支 SHOULD 使用 `NNN-short-name` 或时间戳前缀命名，并将特性
  文档放在对应的 `specs/<branch-prefix>-<short-name>/` 目录。
- 新事件 MUST 在 `src/utils/events.py` 统一定义；新配置 MUST 走统一配置管理；新增敏感
  字段 MUST 明确安全存储与脱敏策略。
- UI 代码 MUST 通过 Service、Bridge 或业务层访问下层能力，不得直接触达 Repository 或
  其他底层存储实现。
- Reviewer MUST 拒绝以下提交：向上层反向依赖、绕过过滤边界读取录制数据、硬编码密钥、
  在 `UnifiedConfigManager` 外直接读写配置文件或配置表、明文泄漏 secret、以及未记录
  例外原因的测试/文档缺口。
- **受控例外登记（033，CC-005）**：调度中心 per-task 无人值守免确认
  （`scheduled_tasks.unattended_auto_approve`，SQLite v30 持久化）是对「全部允许/免确认
  只允许进程会话级内存、不得写入 SQLite」规则的**唯一显式受控破例**，由用户显式拍板。
  它 MUST 满足四重限定（仅 `source='scheduled'` 会话 / 仅该 `scheduled_task_id` / 默认关闭 /
  只能用户显式 UI 操作开启）+ 工具参数三重不暴露（schema properties / handler / router
  create-update 源码均不含该字段，门卫测试 `test_scheduled_task_unattended_field_isolated`
  守）+ 独立 `UnattendedConfirmationManager`（绝不读写进程级 `_auto_approve_enabled`）+
  D7 立即拒（scheduled 来源与 per-task 授权判定 MUST 先于进程级「全部允许」；
  未授权高危动作立即按拒绝处理，不空等超时且不得被全局开关越权，FR-023）。爆炸半径焊死
  在「仅该 scheduled 会话的高危动作」，列表层一眼可见、详情页可显式开启或回收。详见
  `docs/PROJECT_CONSTRAINTS.md` CC-005 与 `specs/033-scheduling-center/`。
- **受控例外登记（workspace 外写走确认链，2026-07-26）**：workspace 外 `write_file` /
  `edit_file` / `apply_patch`（含 delete 子操作）默认走 `_confirm_or_reject` 确认链——用户
  开启进程会话级「全部允许」（`_auto_approve_enabled`）则短路放行并记 `auth_confirmation_decision`
  审计（`decision=auto_approved, source=auto_scope`），未开启则逐次弹确认（确认后本会话同文件
  不再问）。它 MUST 满足：(1) 只对 `write/edit/delete/patch` 操作生效，`execute` 的 cwd 与
  shell host 内联 flag（`bash -c` / `powershell -Command` / `cmd /c`）/内联代码/`..` 穿越硬门卫，以及 OS 系统路径（`C:\Windows`、`/etc` 等）
  **继续不受覆盖、始终硬拒**；其他 shell 元字符经 shell 模式执行但不受"全部允许"短路（force_interactive）；allowlist 内开发命令可短路；(2) `_self_improvement_mutation_denial`（builtin_permissions
  inside-workspace 守卫）**正交不动**；(3) 本会话确认缓存只在进程内存（重启 / 新会话 reset /
  停止清空），不持久化；(4) proposal executor 派发源头守卫
  `_assert_proposal_executor_workspace_or_raise` 仍 fail-closed，与 allow_all 状态无关。
  详见 `docs/PROJECT_CONSTRAINTS.md` Agent Built-in Tool Boundaries 与
  `specs/015-agent-builtin-tools-upgrade/`。

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

**Version**: 3.1.0 | **Ratified**: 2026-04-21 | **Last Amended**: 2026-07-19

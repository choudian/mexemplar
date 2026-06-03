# Implementation Plan: 子代理可唤回机制（Resumable / Re-dispatchable Subagent）

**Branch**: `013-subagent-resumable` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/013-subagent-resumable/spec.md`

## Summary

临时子代理在被迫中断时不再丢弃已完成工作：撞迭代上限或 LLM 调用经重试仍最终失败时，会话转入 `suspended` 并完整保留工作历史，委派结果以"暂停（可唤回）+ 子代理标识符 + 可区分暂停原因"的句柄返回给主代理。主代理可在不消耗额外模型调用的前提下查看子代理工作概览（轮数、工具调用次数、最后产出、状态），据此判断该续跑还是新开；可对任意属于自己的子代理（含被迫暂停的与已正常完成的）唤回续跑并附可选追加指令；唤回基于持久化会话历史恢复，跨进程重启仍可用；归属校验拒绝访问非己出会话。

技术路径：在 `AgentConfig` 增加 `resumable_on_failure` 开关与新结果类型 `ResultType.PAUSED`；`AgentLoop` 在"迭代上限"与"LLM 调用最终失败"两条终止路径上，当该开关开启时置会话 `suspended` 并返回 `PAUSED`（默认 Agent 行为零变化）。`AgentOrchestrator` 在委派结果中统一回传 `subagent_id`、对 `PAUSED` 返回可唤回句柄并记一条内部 `assistant_delegation_paused` workflow transition；新增 `_continue_subagent`（从持久化历史恢复、归属校验、以主代理当前工具池重建、支持重复唤回）与 `_inspect_subagent`（纯机械只读统计，零模型调用）两条编排路径，并通过 `continue_subagent` / `inspect_subagent` 两个新工具暴露给主代理；Assistant system prompt 增加"子代理暂停处理"引导段。复用既有 session / message / workflow_transition 持久化，无新表、无迁移、无新增对外配置键。

## Technical Context

**Language/Version**: Python 3.12 runtime target（项目兼容 `>=3.11`）；前端/Tauri/Rust 不涉及
**Primary Dependencies**: 自研 `AgentLoop`、`AgentOrchestrator`、`ContextManager`、LangChain LLM 客户端、blinker；无新增依赖
**Storage**: SQLite 既有 `sessions` / `messages` / `workflow_transitions`（经 `SessionRepository` / `MessageRepository` / `WorkflowTransitionRepository`）；无新表、无迁移。DuckDB 无影响
**Testing**: pytest（`tests/business/agents/`、`tests/integration/`）；行为契约测试 + 既有 agent/orchestrator 回归
**Target Platform**: Windows 桌面应用 Python sidecar 业务层（纯后端 business 层变更）
**Project Type**: Desktop app 后端业务层（Agent 编排）
**Performance Goals**: `inspect_subagent` MUST 不触发任何模型调用（纯 DB 读取 + 内存聚合）；唤回不要求重述任务即可从断点续跑
**Constraints**: 不物理删除/改写会话历史（唤回是追加恢复）；100% 调度不变（唤回的仍是子代理，主代理不直接执行）；非临时子代理的中断处理零回归；归属校验拒绝并不泄露非己出会话内容；账单/网络类失败需等外部恢复，不可靠压缩绕过
**Scale/Scope**: 单用户单进程；受影响 Agent 为 Assistant（主代理）与 Ephemeral Subagent；3 个工具（新增 2、修改 1 返回契约）；4 个源文件 + 1 个测试文件

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门卫问题 | 证据 |
|------|----------|------|
| **I. 分层边界与事件协调** | 是否保持 `UI -> business -> execution -> data/driver`，跨模块通知是否经事件边界？ | **通过**。改动全部落在 business 层（`agents/` + `orchestration/agent/`），不触达 UI/desktop_api/execution。唤回/查看是主代理工具 → orchestrator 编排路径的同模块方法调用，不需要跨模块事件；新增的 `assistant_delegation_paused` 是后端**内部 workflow transition**（沿用既有 `record_transition`），非面向前端的公开 UI 事件，本期不在 `ui_events.py` 注册。 |
| **II. 数据边界与持久化纪律** | SQLite/DuckDB 与 Repository 边界是否明确？ | **通过**。唤回/查看经 `MessageRepository.get_context` / `get_latest_assistant_text` 与 `SessionRepository`（via `AgentSessionStore`）读取，业务层不直接写 SQL。无 schema 变更、无迁移、无序列化/回填。DuckDB 无影响。 |
| **III. 统一配置与密钥安全** | 新配置是否走统一配置，密钥是否安全？ | **通过 / N/A**。无新增对外配置键；迭代上限是 `AgentConfig` 内部字段（临时子代理初始 `max_iterations` 由 20 调为 50、续跑 `extra_iterations` 默认 20，属代码内默认值而非配置）。无密钥、无 keyring 改动。 |
| **IV. 可验证交付** | 确定性逻辑与静默失败路径是否有覆盖？ | **通过**。`tests/business/agents/test_subagent_resumable.py` 覆盖：两路 PAUSED 终止语义、默认 Agent 不回归（MAX_ITERATIONS_REACHED / ERROR）、委派回传 `subagent_id`、PAUSED 句柄、续跑完成/再暂停/归属拒绝/未知 id、inspect 概览零模型调用、prompt 引导段存在。回归层跑 `test_agent_loop_retry` / `test_agent_loop_multi_tool_calls` / `test_agent_orchestrator_architecture` / `test_assistant_dispatch` 证明 FR-011/SC-006。 |
| **V. 活文档与规格驱动交付** | 活文档与模块指引是否识别？ | **通过**。新增工具与暂停语义需在 `src/AGENTS.md`（及 CLAUDE/GEMINI 镜像）的「Agent 与工具约束」补一句临时子代理可唤回与 100% 调度不变；`docs/ARCHITECTURE.md` 视情况补 Agent 编排小节。spec/plan/tasks 三件套在本目录维护。 |

**Post-design re-check**: 通过。Phase 1 设计未引入新存储、新公开事件或新配置；归属校验、零模型调用 inspect、可重复唤回、默认 Agent 零回归均落到具体测试断言；未引入任何 constitution 例外（无需 Complexity Tracking）。research.md R3 标记的保真度缺口（LLM 最终失败被无差别标注为"账单或网络"）已收敛：`_is_recoverable_llm_failure` 按异常类型/消息区分可恢复（配额/网络）与不可恢复失败，仅前者转 PAUSED，并补契约测试。

## Project Structure

### Documentation (this feature)

```text
specs/013-subagent-resumable/
├── plan.md              # 本文件（/speckit.plan 输出）
├── spec.md              # 已存在（/speckit.specify 输出）
├── research.md          # Phase 0 输出：关键设计决策与未决保真度问题
├── data-model.md        # Phase 1 输出：实体（复用既有）+ 工具返回 DTO 形状
├── quickstart.md        # Phase 1 输出：验证命令与手动恢复演练
├── contracts/
│   └── subagent-tools.md # Phase 1 输出：3 个工具的输入/输出契约
├── checklists/
│   └── requirements.md  # 已存在（spec 质量校验）
└── tasks.md             # Phase 2 输出（/speckit.tasks 生成，非本命令）
```

### Source Code (repository root)

```text
src/business/agents/
├── config.py                     # +ResultType.PAUSED, +AgentConfig.resumable_on_failure
├── agent_loop.py                 # 迭代上限/LLM 调用失败两路 → suspended + PAUSED（仅 resumable_on_failure）
├── prompts/
│   └── assistant_prompt.py       # +「子代理暂停（可唤回）时的处理」引导段（FR-010）
└── tools/
    └── assistant_tools.py        # +continue_subagent / +inspect_subagent schema & handler 工厂

src/business/orchestration/agent/
└── orchestrator.py               # 委派回传 subagent_id；PAUSED 句柄 + transition；
                                  # _resolve_subagent_session 归属校验；
                                  # _continue_subagent 续跑（持久化恢复/重复唤回）；
                                  # _inspect_subagent 零模型调用概览；
                                  # 注册两个新工具；ephemeral_config max_iterations=50 + resumable_on_failure

tests/business/agents/
└── test_subagent_resumable.py    # 行为契约测试（13 例）
```

**Structure Decision**: 纯 business 层增量。终止语义改在通用 `AgentLoop` 上、以 `AgentConfig` 开关门控（默认关闭，保证非临时 Agent 零回归）；编排/工具/归属校验集中在 `AgentOrchestrator`；持久化恢复完全复用既有 session/message 存储，因此不新增数据层结构。

## Complexity Tracking

> 无 Constitution 违例，无需填写。

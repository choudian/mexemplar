# Research: 外部 Coding Session

## Decisions

### R1. 独立业务模块承接外部 coding session

**Decision**: 新建 `src/business/external_coding/`，由 `ExternalCodingSessionService` 统一处理 session 生命周期、artifact、quota、attempt、merge 分析和事件。

**Rationale**: 该能力跨 agent tools、task owner、CLI 进程、SQLite、git worktree 和 UI snapshot。如果放入 task collaboration，会把任务调度和外部执行体协议耦合；如果放入 execution，会让运行时层反向理解业务状态。独立 business 模块最符合现有分层。

**Alternatives considered**:
- 直接在 `assistant_tools.py` 内实现：实现快，但会绕过 Repository/Service 边界，难测试。
- 扩展 self-improvement proposal bridge：复用 worktree 思路，但该桥有源码爆炸半径和提案审批语义，不适合用户普通任务。

### R2. SQLite v27 持久化核心状态，artifact 保留 Markdown 和有界日志

**Decision**: SQLite 保存 session/attempt/quota/merge/rollback 审计事实；`data/coding_sessions/<id>/` 保存 `HANDOFF.md`、`PLAN.md`、`RESULT.md`、`logs/*.log` 和简短 preview metadata。

**Rationale**: 状态机和恢复必须可靠查询；Markdown 产物更适合用户和外部 agent 阅读。原始日志可能很大且可能含敏感信息，因此只保存有界 tail/文件引用，不进入 UI event。

**Alternatives considered**:
- 全部放 SQLite blob：审计查询方便但不利于外部 CLI 写 artifact，也扩大 DB 体积。
- 全部放文件：恢复和 UI snapshot 需要扫描目录，容易出现状态漂移。

### R3. Plan-before-code 用协议状态而非提示词自觉保证

**Decision**: `planning` attempt 启动前记录 baseline；`PLAN.md` ready 后检查 worktree diff。如果 plan phase 出现写入，session 转入 `interrupted` 或 `protocol_violation` 风险标记，等待 agent 裁定。

**Rationale**: 外部 CLI 也是 agent，不能只靠 prompt 保证只读。git baseline/diff 是确定性证据。

**Alternatives considered**:
- 使用 Claude/Codex 自带 plan mode 作为唯一保证：不同工具语义不一致，且无法覆盖所有写入路径。
- 为 V1 禁用 worktree 写权限：会让外部 CLI 的探索能力和后续 resume 复杂化。

### R4. Tool auto-selection 使用归一化 QuotaSignal，不暴露凭证

**Decision**: `QuotaProbe` 输出 `available | low | exhausted | unknown`、source、confidence、checkedAt/resetAt；不持久化 raw credential、raw endpoint response 或账户明文。

**Rationale**: 用户允许读取本机凭证/状态源，但项目 constitution 要求 secret 不进入普通日志/DTO/UI。归一化结果足以做路由。

**Alternatives considered**:
- 完全不读 quota：会频繁派到已耗尽工具。
- 保存完整 usage response 便于排错：违反 secret/隐私边界。

### R5. Merge 权限集中在 Exemplar

**Decision**: 外部工具可以在 coding worktree branch 内提交，但不能 merge/push/reset/clean 目标分支。Exemplar 在目标工作区执行 merge 前分析并记录 audit。

**Rationale**: 用户希望自动推进后续任务，但需要可回滚审计点。把 merge 放在 Exemplar 可统一处理 dirty/conflict 和 user-intent rollback。

**Alternatives considered**:
- 让 Claude/Codex 自行 merge：快，但审计和冲突风险不可控。
- 永远手动 merge：安全但不满足用户自动连续派工目标。

### R6. UI 通过 task detail 显示摘要，详细内容通过 API 拉取

**Decision**: Task snapshot 附加轻量 `externalCodingSessions` 摘要；TaskNodeCard 展示 tool/status/phase/worktree/branch/artifact preview/actions。完整 artifact/log tail 通过 external coding API 获取。

**Rationale**: 当前 task graph/detail 是用户观察执行链路的主入口。摘要进入 snapshot 可在 event resync 后恢复；大文本不进 snapshot。

**Alternatives considered**:
- 新建独立主屏：发现成本高，和任务上下文脱节。
- 只在 activity timeline 追加文本：不能做 action，也不利于重启恢复。

## Open Technical Risks

- Claude Code/Codex CLI 版本和参数会变化；adapter 必须把 CLI command profile 配置化，并把 unsupported highest effort 分类为 interruption，而不是静默降级。
- Interactive supervised launch 在无可见终端时只能算受控弱路径；V1 不依赖屏幕解析判断完成。
- Quota endpoint 来源可能不稳定；`unknown` 必须是可用状态而非 hard failure。

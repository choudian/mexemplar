# 开发总协调者与编码 Agent 工具体系整合 TODO

> 状态：可行性研究 TODO。
> 关系：本文建立在 `assistant_agent_redesign_draft.md` 和
> `assistant_brain_implementation_design.md` 的主助理大脑与多 Agent 调度方向之上。
> 目的：先确认这个方向能不能做、值不值得做；本文不定义最终实现方案。

## 1. 想验证的核心场景

用户只和一个“开发总协调者”对话。总协调者负责理解目标、确认需求、维护任务板、拆分工作、
调度下游编码 Agent 或编码工具，并在过程中处理不确定性。

下游可以是不同来源的编码能力：

- 本项目内已有 AgentLoop 子 Agent
- Codex / Claude Code / Gemini / Cursor 等外部编码工具
- OpenAI API 驱动的本地 Agent
- 本地脚本、测试 runner、review runner
- 未来可能接入的其它套餐或供应商能力

目标不是把所有 Agent 拉进同一个聊天室，而是让它们围绕同一个开发目标产出可合并、可验证、
可追责的结果。

## 2. 核心产品判断

总协调者不应是消息转发器，而应拥有默认技术拍板权。

默认分工：

| 决策类型 | 默认决策者 |
|---|---|
| 产品目标、需求取舍、用户真实意图 | 用户 |
| 不可逆动作、数据删除、发布上线、明显费用或隐私风险 | 用户 |
| 本地实现细节、命名、拆文件、测试补法 | 子 Agent 或总协调者 |
| 技术路径、任务拆分、结果仲裁、重试策略 | 总协调者 |
| 子 Agent 之间输出冲突 | 总协调者 |

关键原则：如果问题能通过项目约束、历史偏好、现有代码模式和低风险默认方案解决，就不打扰用户。
只有当错误选择代价高、不可逆、或涉及真实产品意图时，才升级给用户。

## 3. 任务板不是一次性计划

总协调者可以先生成任务板，但任务板必须允许在执行过程中被修正。

原因：

- 用户前期通常只能表达目标，无法预先说清所有技术细节。
- 很多真正的问题是在读代码、试跑、拆任务之后才暴露。
- 如果总协调者一次性把任务分发下去直接开工，容易造成返工和 token 浪费。

建议研究“先预检，再开工”的派发模式。

```text
draft -> preflight -> clarifying -> ready -> doing -> blocked -> review -> done
```

每个子 Agent 收到任务后，第一步只做 readiness check，不直接改代码。

## 4. 子 Agent Preflight 机制

子 Agent 做任务前先返回 `ReadinessReport`：

```text
can_start
understood_goal
acceptance_criteria_seen
missing_info
assumptions
decisions_needed
recommended_default
risk_if_default_is_wrong
suggested_task_rewrite
estimated_write_scope
```

总协调者收到报告后：

1. 自己能回答的问题，直接更新任务板。
2. 可以安全默认的问题，记录假设后继续。
3. 多个子 Agent 问到同类问题时合并处理。
4. 真需要用户拍板的问题，再翻译成用户能回答的问题。

子 Agent 不直接问用户，只提交结构化 `ClarificationRequest`：

```text
question
why_needed
options
recommended_option
default_if_no_answer
who_can_decide: coordinator | user
blocking
risk_if_wrong
```

## 5. 总协调者的上下文与账本

需要研究是否建立一个专门的开发任务账本，而不是只依赖聊天历史。

候选概念：

```text
DevMission
  goal
  acceptance_criteria
  constraints
  repo_context
  decision_policy
  budget_policy
  work_items
  agent_runs
  artifacts
  final_verification
```

配套账本：

- `Task Board`：任务、状态、依赖、负责人、当前阻塞。
- `Decision Log`：总协调者或用户拍过什么板，为什么。
- `Assumption Ledger`：尚未问用户但先按默认推进的假设。
- `Artifact Board`：patch、文件列表、测试结果、review 结论、截图等产物引用。
- `Agent Performance Notes`：不同编码 Agent 的擅长领域、常见问题、历史表现。

研究重点：这些信息哪些需要持久化，哪些只存在于当前 DevMission。

## 6. 编码工具 Provider Registry

不要把某个编码工具写死进调度逻辑。需要研究统一的 provider 描述：

```text
name
entrypoint: cli | api | local_agent
strengths
can_edit_files
can_run_commands
supports_worktree
context_limit
cost_tier
quota_state
privacy_level
preferred_task_size
required_permissions
```

总协调者根据任务性质选择 provider，而不是让用户手动指定每一步用哪个工具。

## 7. 上下文传递原则

多 Agent 协作时不应共享完整 message history。

优先共享：

- 任务目标
- 验收标准
- 相关文件引用
- 设计约束摘要
- 已拍板决策
- 假设账本
- 前序 Agent 产出的 artifact

需要研究 `context_refs` / artifact refs 的最小协议，避免在 Agent 之间复制大量聊天内容。

## 8. 工作隔离与合并

需要研究是否默认使用 worktree 或独立 write scope。

候选规则：

- 只读 preflight 不创建 worktree。
- 真正写代码时，复杂任务优先独立 worktree。
- 多个子 Agent 并行时必须声明 write scope，避免写同一批文件。
- 子 Agent 交付 patch artifact，总协调者负责最终合并与验证。

子 Agent 交付结果建议结构化：

```text
status
changed_files
patch_summary
tests_run
test_results
open_risks
handoff_notes
needs_review
```

## 9. 防失控机制

可行性研究必须覆盖以下安全阈值：

- 最大 delegate 深度
- 单个 DevMission 最大子 Agent 数
- 单个任务最大重试次数
- token / 费用预算
- wall time 超时
- 并发上限
- 高危命令和文件操作确认
- 外部 provider 能否访问隐私代码或 secret

原则：子 Agent 可以上报问题，但不能无限递归创建新任务。

## 10. 与现有大脑设计的关系

现有大脑系统可为该方向提供三类长期能力：

1. 记住用户开发偏好：例如偏好最小切片、讨厌过度抽象、前端风格要求。
2. 记住项目工程惯性：例如分层边界、测试门卫、历史失败。
3. 记住 Agent 表现：不同 provider 的成功率、常见缺陷、适合任务类型。

需要研究哪些 DevMission 结果应沉淀进热区、持久区、失败区或归档区。

## 11. 可行性研究 TODO

### A. 现状摸底

- [ ] 梳理现有 `AgentLoop`、`AgentOrchestrator`、`AssistantTaskWorker` 是否能承载 DevMission。
- [ ] 梳理现有 assistant 工具调用、动态工具、hook、高危确认能否复用于子 Agent。
- [ ] 梳理 session / message 存储是否适合记录 ephemeral 子 Agent 运行。
- [ ] 梳理当前代码库是否已有任务、artifact、patch、review 相关模型可复用。

### B. Preflight Spike

- [ ] 做一个只读 preflight 原型：总协调者派任务，子 Agent 只返回 `ReadinessReport`。
- [ ] 验证总协调者是否能消化大部分问题，而不是直接问用户。
- [ ] 验证 `ClarificationRequest` 是否能减少无效追问。
- [ ] 评估 preflight 本身的 token 成本是否值得。

### C. Decision Policy Spike

- [ ] 定义第一版决策分类：用户决策、总协调者决策、子 Agent 可自行决策。
- [ ] 收集 20 个真实开发问题样例，测试分类是否稳定。
- [ ] 验证总协调者能否把技术问题翻译成用户能回答的产品问题。
- [ ] 明确哪些场景必须 fail-closed 或强制问用户。

### D. Provider Registry Spike

- [ ] 定义最小 `AgentProvider` 描述。
- [ ] 接一个本地 AgentLoop provider 作为基线。
- [ ] 研究外部 CLI 型编码工具是否能统一成 provider。
- [ ] 研究不同套餐的额度、费用、隐私边界如何进入调度策略。

### E. Task Board / Run Ledger Spike

- [ ] 定义最小 `DevMission`、`WorkItem`、`AgentRun`、`Artifact` 模型。
- [ ] 验证任务状态流是否能表达 preflight、clarifying、doing、blocked、review、done。
- [ ] 验证 Decision Log 和 Assumption Ledger 能否减少重复追问。
- [ ] 明确哪些字段必须入 SQLite，哪些只需要运行期内存。

### F. Worktree / Patch Spike

- [ ] 验证子 Agent 在独立 worktree 中工作是否可行。
- [ ] 验证总协调者合并 patch 的冲突处理流程。
- [ ] 验证并行任务 write scope 声明是否足够避免互相覆盖。
- [ ] 验证最终测试由总协调者统一执行是否合理。

### G. 用户体验 Spike

- [ ] 设计总协调者如何展示任务板，而不是暴露所有子 Agent 噪声。
- [ ] 设计真正需要用户拍板的问题格式。
- [ ] 设计用户不知道怎么选时的默认推进方式。
- [ ] 设计任务执行中发现问题后的重新规划体验。

## 12. 候选 MVP

最小可验证版本可以只做：

1. 用户和总协调者对话形成一个 DevMission。
2. 总协调者拆 1 到 3 个 WorkItem。
3. 每个 WorkItem 先跑 preflight。
4. 总协调者消化 preflight 问题，只有必要时问用户。
5. 只接一个本地子 Agent provider。
6. 子 Agent 只允许单线程执行一个任务。
7. 结果以结构化 `AgentRunResult` 回到总协调者。
8. 总协调者做最终总结和测试建议。

暂不做：

- 多外部套餐自动路由
- 大规模并行
- 自动合并复杂冲突
- 长期 Agent 表现评分
- UI 完整任务板

## 13. 主要风险

| 风险 | 研究方向 |
|---|---|
| Preflight 变成额外 token 消耗 | 对比直接执行与先预检的返工率 |
| 总协调者拍板错误 | Decision Log + 可回滚默认策略 + 失败区沉淀 |
| 子 Agent 过度提问 | ClarificationRequest schema 加 `default_if_no_answer` 和风险分级 |
| 外部工具权限过大 | Provider privacy level + tool whitelist + existing hook |
| 多 Agent 文件冲突 | worktree / write scope / patch artifact |
| 用户被技术问题淹没 | 总协调者只升级产品/风险问题 |
| 账本过重 | 先做运行期模型，再决定持久化范围 |

## 14. 可行性研究完成标准

完成研究时至少回答：

- 这个方向是否能在现有架构里增量接入，而不破坏 PM / programmer / trial 流水线？
- Preflight 是否实际减少返工和无效 token？
- 总协调者能否稳定区分“自己拍板”和“必须问用户”？
- 外部编码工具是否能抽象成 provider，而不是特殊集成？
- 是否需要 worktree 作为第一版强约束？
- DevMission / Task Board / Ledger 的最小持久化范围是什么？
- 第一版 MVP 的边界和验收路径是什么？


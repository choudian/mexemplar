# Phase 0 调研：外部 Coding 可靠性修复

**Date**: 2026-07-21
**Status**: 完成，无遗留 NEEDS CLARIFICATION

本特性的技术未知在规格撰写前已通过本机实测消解。以下记录调研方法、结论与被否决的备选方案，
以便后续复现与回溯。

---

## 调研 1：两个外部 CLI 对 `@文件` 引用的真实行为

### 方法

不依赖文档描述，直接拦截两个 CLI 实际发出的模型请求：

1. 起一个本地 HTTP 服务监听回环端口，接收并落盘请求体后返回 400
2. 通过 `ANTHROPIC_BASE_URL` 将 Claude Code 指向该服务，以假 API key 触发一次调用
3. codex 侧直接以只读沙箱执行一次最小任务，观察其真实会话记录
4. 提示词文件内容为一句可验证的指令，便于判断内容是否真正抵达

### 结论

| CLI | user 消息内容 | 文件内容是否抵达 | 机制 |
|---|---|---|---|
| Claude Code | 字面路径 `@C:\...\PROMPT.md` | **是** | CLI 抢先调用 Read 工具，将文件内容作为一条 system 消息注入上下文（自动预取） |
| Codex | 字面路径 | **否** | 无任何预取；本次是 agent 自行决定调用 shell 读取文件才拿到内容 |

即 `@` 语法只对 Claude Code 成立。`cli_adapters.py` 对两个 CLI 使用同一写法，
意图是"CLI 会展开成内容"，该意图仅在一侧兑现。

### 附带发现

对 Claude Code 加 `--bare` 后，那条 Read 注入消失，退化为只收到裸路径。
`--bare` 的说明中包含"skip background prefetches"——即 `@` 的有效性依赖预取机制。
若后续为提高确定性给 Claude Code 加上 `--bare`，`@` 将**静默失效**。
此耦合 MUST 在代码中留注释（对应 FR-009）。

---

## 调研 2：CLI 参数合法性核对

### 方法

对本机已安装的两个 CLI 逐项核对 `--help` 输出，确认 `cli_adapters.py` 构造的每个参数在当前版本存在且取值合法。

### 初次 `--help` 核对结论

静态核对确认参数名称在当时安装版本中存在：

- Claude Code：`--effort`（合法值 `low, medium, high, xhigh, max`，项目默认 `max` 有效）、
  `--safe-mode`、`--permission-mode`（合法值含 `auto`）、`--disallowedTools`、
  `--output-format stream-json`、`--add-dir`
- Codex：`exec` 子命令、`exec resume`、`-c/--config`、`-s/--sandbox`、
  `--ignore-user-config`、`--json`（`exec resume` 亦支持）、`--add-dir`

该结论只说明“单个参数存在”，不能证明组合后的生产命令可运行。T015 真实链验证推翻了
“无需修正”的初始判断，证明项目 Known Issues 中的参数/启动协议漂移已经实际发生。

### T015 / T020 生产链补记（最终契约）

真实运行后必须保留以下四项修正：

1. Claude headless 的 `--output-format stream-json` 在当前版本必须同时带 `--verbose`
2. Windows 默认命令名必须先经 PATH/PATHEXT 解析 `.cmd` / `.exe`，但仍以 argv、
   `shell=False` 启动
3. Codex `exec resume` 的 sandbox / add-dir / output 等父级参数必须置于 `resume` 子命令之前
4. Codex headless 必须使用 `-o` final-output 路径确定性写入 `PLAN.md` / `RESULT.md`

T020 使用默认命令名 `codex` 复验上述契约后进入 `plan_ready`。后续维护既要核对 `--help`，
也必须跑一次真实命令构造/启动链；不得再用“参数存在”推导“组合协议可运行”。

---

## 决策 1：codex 任务书的送达方式

**Decision**: 将 codex 分支的提示词参数由 `@{prompt_path}` 改为带动词的明确指示
（`Follow the instructions in this file: <path>`）。

**Rationale**: 用户在权衡后选择最轻方案。改动限于一行字符串构造，风险极低，
且把"靠 agent 猜"变成"明确告知去读"，消除了意图与实现不一致的问题。

**Alternatives considered**:

- **走标准输入直接投喂内容**（被否决，非永久）：`codex exec` 明确支持从 stdin 读取指令
  （"instructions are read from stdin"），可彻底消除对 agent 主动读取的依赖；相较显式文件
  读取指示，它改善的是内容送达确定性，不能据此承诺减少模型工具调用轮次。否决理由是改动面
  扩大到 `external_coding_process.py` 的进程启动
  （headless 当前 `stdin=DEVNULL`，见第 125 行），本次选择先以最小改动关闭风险。
  **该方案保留待用**：若 codex 侧出现实际的任务书未抵达事故，即升级至此方案。
- **两个 CLI 统一走 stdin**（被否决）：Claude Code 侧实测有效，改动只会引入回归风险，
  无收益。

---

## 决策 2：目标仓库如何传递到执行专员

**Decision**: 不建项目注册表。将目标仓库位置改为工具必填参数，缺失即拒绝。

**Rationale**: 调研发现大脑记忆只注入主助理
（`assistant_prompt_builder.py` 按 `AgentType.ASSISTANT` 构建 brain context），
**执行专员看不到这些记忆**。因此"把项目路径记在记忆里"无法直达调用点，
仍需主助理在委派时写入任务描述，形成三层模型软约束串联，末端是硬编码的 `Path.cwd()` 兜底。

关键判断：模型侧无论怎样改进都无法消除末端那个静默默认值——那由代码决定。
因此本特性只需提供一条硬保证（说不清就拒绝），
"路径怎么被模型知道"交由既有记忆与委派上下文机制解决，不需要新增存储。

**Alternatives considered**:

- **建项目注册表（表 + 设置 UI + `projectId` 参数）**（被否决，非永久）：更省心，
  用户只需说项目名。否决理由是当前只开发单个项目，新增一张表和一块设置 UI
  的收益尚未兑现，属过早投入。**待用户开始并行开发多个项目、嫌手报路径烦时再加**。
- **禁止以 Exemplar 自身为目标**（被否决）：用外部 coding 开发 Exemplar 本身是正当用途，
  且极可能是用户的第一个真实场景。要消除的是"静默滑入"，不是"指向自身"本身。

---

## 决策 3：隔离 worktree 的落盘基准

**Decision**: 配置 `external_coding.worktree_root` 为相对路径时，
以目标仓库为基准展开；为绝对路径时原样使用。

**Rationale**: 该配置默认值 `.worktrees/coding` 是相对路径，当前经 `.resolve()`
相对进程 cwd 展开。即使目标仓库是外部项目，worktree 仍会建在 Exemplar 目录下——
这是"默认落在 Exemplar 身上"的另一面。只修必填而不修落盘基准，
会出现"路径填对了、产物仍堆在 Exemplar 里"的割裂状态。

两处同源，一并修复方能闭合。各项目的 worktree 落在各自仓库下后，`.gitignore` 也由各项目自管。

**Alternatives considered**:

- **只做必填、落盘位置留待后续**（被否决）：会留下上述割裂状态，
  且第二次改动仍要回到同一函数，不如一次做完。
- **新增独立配置键指定落盘位置**（被否决）：违反"零新增配置键"约束，
  且既有键的语义本就该以目标仓库为准，属修正而非扩展。

---

## 决策 4：历史数据兼容

**Decision**: 目标仓库/worktree 落盘语义变更无需历史 session/worktree 迁移方案；v33 attempt
schema 演进仍按正式幂等迁移处理。

**Rationale**: 实测当时 `external_coding_sessions` 与 `external_coding_attempts` 两表均为 0 行，
不存在按旧 worktree 规则落盘的历史资源需要兼容。该结论只适用于目标仓库/落盘行为，不排除
后续可靠性修复为 attempt 表增加字段、索引与写入 guard。

**Alternatives considered**:

- **为历史 session 保留旧落盘规则**（被否决）：无历史数据，纯属想象中的兼容负担。

---

## 决策 5：参数契约的变更方式

**Decision**: 直接将 `targetWorktreePath` 移入 `required`，不做过渡期或双写兼容。

**Rationale**: 项目当前为单用户、未发布状态，无外部脚本、第三方集成或历史调用方
依赖既有参数契约。填参约束写入工具 schema description（项目既有惯例：
填参约束进工具说明，不进主助理系统提示词）。

**Alternatives considered**:

- **保留选填一段时间并告警**（被否决）：告警对 LLM 调用方无约束力，
  风险窗口继续敞开，与本特性目的相悖。

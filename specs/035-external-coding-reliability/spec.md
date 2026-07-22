# Feature Specification: 外部 Coding 可靠性修复

**Feature Branch**: `035-external-coding-reliability`
**Created**: 2026-07-21
**Status**: In Review
**Input**: User description: "外部 Coding 可靠性修复：codex 任务书送达 + 目标仓库路径必填"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 干活的仓库不会被搞错 (Priority: P1)

用户让办公助理"在某个项目上改点东西"。助理把活派给专员，专员启动外部 coding session。
整条链路上，"要改哪个仓库"这件事必须是明确的：说得清就干，说不清就停下来问，
绝不能因为没人说清楚，就默认在 Exemplar 自己身上动手。

**Why this priority**: 这是唯一会造成实际损失的缺陷。当前缺省行为是把改动落到 Exemplar
自己的仓库，且没有任何提示。用户接下来正要把这套工具用于日常开发，风险敞口正好在这段
时间打开。其余问题最多让人多点几下鼠标，只有这一条会改错东西。

**Independent Test**: 单独实现即可交付价值——发起一次不指明目标仓库的 coding session，
确认被拒绝且系统中零残留；再发起一次指明外部仓库的，确认 worktree/分支按配置落在
目标仓库侧，artifact 只落在既有配置根。
不依赖 User Story 2。

**Acceptance Scenarios**:

1. **Given** 启动请求中没有指明目标仓库位置，**When** 执行体尝试启动外部 coding session，
   **Then** 请求被拒绝并说明"缺少目标仓库"，且不创建工作区、不创建分支、不留下会话记录
2. **Given** 指明的位置不是一个可用的代码仓库，**When** 启动，**Then** 拒绝并给出用户
   能据此行动的说明，不暴露原始异常文本
3. **Given** 指明了一个 Exemplar 之外的合法仓库且使用默认相对 worktree 根，**When** 启动成功，
   **Then** 隔离工作区与分支全部落在该仓库侧，Exemplar 不新增 worktree/分支；session
   artifact 仍按既有 artifact 根配置存放
4. **Given** 用户确实想改 Exemplar 本身，并明确指明了它的位置，**When** 启动，
   **Then** 正常放行——本特性禁止的是"没人说要改它却滑进去改了"，不是禁止改它

---

### User Story 2 - 换哪个外部工具，结果一样可靠 (Priority: P2)

系统会按配额自动在两个外部编码工具之间选择。不论这次选中了哪一个，交给它的任务书都必须
真正送到它手上，而不是只给一个存放位置、指望它自己想起来去取。

**Why this priority**: 不会改错仓库，但会让两条执行路径的可靠性不一致，而用户感知不到
本次落在哪条路上。属于"结果可能不对"而非"会造成损失"，故排在 P1 之后。

**Independent Test**: 单独实现即可验证——分别构造两个工具的启动指令，确认都含有明确的
任务书获取指示。不依赖 User Story 1。

**Acceptance Scenarios**:

1. **Given** 本次选中的是 codex，**When** 构造启动指令，**Then** 指令中包含明确的
   "读取该文件"指示，而不是仅有一个孤立的文件位置
2. **Given** 本次选中的是 Claude Code，**When** 构造启动指令，**Then** 保持现有写法不变
   （已实测确认其自动读取机制有效，改动反而会引入风险）
3. **Given** 任一工具、任一阶段（方案阶段 / 实现阶段 / 续跑），**When** 构造启动指令，
   **Then** 任务书获取指示始终存在
4. **Given** Windows 上配置的是不带扩展名的 CLI 命令，**When** 启动 headless session，
   **Then** 系统通过 PATH/PATHEXT 解析真实可执行入口且不启用 shell
5. **Given** Codex headless plan / implement / resume，**When** 外部进程正常结束，
   **Then** 当前阶段的最终回复由 CLI 确定性写入 `PLAN.md` / `RESULT.md`，不依赖模型取得
   artifact 目录的写权限

---

### Edge Cases

- 指明的位置存在、也是仓库，但没有任何提交（HEAD 无法解析）→ 按"位置无效"拒绝并说明
- 指明的位置本身就是另一个隔离工作区，而非主仓库 → 允许，以该位置为基准展开
- 工作区存放位置被配置成了绝对路径 → 保持该绝对路径，不受目标仓库影响
- 目标仓库与 Exemplar 不在同一磁盘分区 → 工作区仍落在目标仓库下
- 拒绝发生在创建工作区之后、写入会话记录之前 → 必须回收已创建的工作区，不留孤儿
- artifact 根为相对路径 → 在 sidecar 工作目录展开为绝对路径后持久化，外部 CLI 切换到
  coding worktree cwd 后仍能读取任务书
- Git / 文件系统拒绝补偿删除 → 返回明确的 cleanup-incomplete 与 session 标识，
  不得静默宣称零残留
- 运行中进程的状态观测临时失败 → 保持 running、禁止续跑；不得把“看不见”当成“已停止”
- sidecar 重启后只剩数据库 attempt、状态文件缺失或残缺 → 以持久化的 PID + 创建时间验证
  进程身份；无法验证时保持 running/fail-closed，不得因重启丢失 ownership
- v32 的 running attempt 升级到 v33、但没有创建时间 → 回填未确认 ownership；状态文件中的
  创建时间不得反向补成 durable identity，也不得据此接受 terminal 或开放 resume
- 两次并发 refresh 先后拿到 terminal 与 stale running → 只有首个 running→terminal CAS 生效，
  迟到观测不得把 attempt 复活或清掉 `finished_at`
- monitor 已确认进程退出、但首次 terminal marker 写入失败 → 后续 poll 可重放安全终态并释放
  registry；reader 即使阻塞在满队列也能被取消回收
- reservation 创建后与真正 spawn 前并发发生 abandon / refresh 关单 → 只有
  `status=running AND launch_started=false` 的 CAS 能取得启动权；CAS 失败不得启动 CLI
- adapter object 构造失败 → reservation 必须仍处于 pre-spawn 并可原子关单；不得先标记
  `launch_started=true` 再调用可能抛错的 factory
- stdout/stderr reader 抛出读取异常 → 必须作为 monitor 故障进入整棵进程树的守护终止，
  不得伪装成普通 EOF 后写假终态；即使进程已退出，也必须等 reader 的 EOF/失败 sentinel
- 首次 session 写入结果未知且回读也失败 → 已创建资源为恢复保留，安全错误必须携带预生成的
  coding session 标识；目标分支探测的 Git 运行故障必须与路径冲突区分，未知代码异常不得降级
- 已跨过 spawn 边界但 PID 尚未写入时出现通用 update / 原始 SQL → `launch_started` 仍只能
  保持 true，不能回退为可安全关单的 pre-spawn 状态

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 启动外部 coding session MUST 要求明确的目标仓库位置；未提供时 MUST 拒绝，
  MUST NOT 回退到任何隐含默认值
- **FR-002**: 因缺少或无效目标位置而拒绝时，MUST NOT 产生任何副作用——不创建工作区、
  不创建分支、不写入会话记录；若失败发生在部分创建之后，MUST 回收已创建的产物
- **FR-003**: 目标位置无效时 MUST 返回用户可据此行动的说明；HEAD/目标分支探测中的预期
  Git 命令失败与 Git 进程启动/超时故障 MUST 分别分类成安全、可行动错误，MUST NOT 伪装成
  路径冲突或回显 OS 异常；未知程序异常 MUST 继续显式失败。所有用户错误 MUST NOT 将底层
  异常文本、堆栈或内部路径原样透出
- **FR-004**: 隔离工作区的存放位置为相对配置时，MUST 以目标仓库为基准展开；
  为绝对配置时 MUST 原样使用
- **FR-005**: 系统 MUST NOT 禁止以 Exemplar 自身为目标仓库——只要位置被显式指明
- **FR-006**: 交给 codex 的启动指令 MUST 包含明确的任务书获取指示
- **FR-007**: 交给 Claude Code 的启动指令 MUST 保持现有引用写法不变
- **FR-008**: 目标仓库位置的填写约束 MUST 表达在工具本身的参数说明中，
  MUST NOT 依赖主助理提示词承载
- **FR-009**: Claude Code 的自动读取机制依赖其预取行为，该依赖 MUST 在代码中留下说明，
  避免后续变更静默使其失效
- **FR-010**: Windows 上的外部 CLI 命令名 MUST 经 PATH/PATHEXT 解析后直接启动，
  MUST NOT 为兼容 `.cmd`/`.exe` shim 而启用 shell
- **FR-011**: headless CLI 命令 MUST 符合当前本机版本的参数语法；Codex resume 的父级
  sandbox/add-dir/output 参数 MUST 位于 `resume` 子命令之前，Claude `stream-json` MUST
  携带该版本要求的 verbosity 参数
- **FR-012**: Codex headless 的阶段 artifact MUST 通过 CLI 的 final-output 文件参数落盘，
  并保持 prompt/路径在命令摘要中脱敏
- **FR-013**: artifact 根无论配置为相对还是绝对路径，MUST 在 session 创建入口规范化为
  绝对路径；handoff / plan / result / prompt 的持久路径 MUST 均为绝对路径
- **FR-014**: artifact 创建、handoff 写入、worktree/分支创建与 session 首次持久化 MUST
  位于同一补偿边界；删除命令 MUST 检查结果并验证资源确实消失。若补偿自身失败，MUST
  返回安全的 cleanup-incomplete 与 session 标识，MUST NOT 伪装成清理成功。首次写入抛错且
  回读也无法确认提交结果时，MUST 保留已创建资源供恢复，并在安全错误中返回预生成的 session
  标识；安全日志 MUST 用该标识关联 create/lookup 两次异常类型，但不得记录异常正文或资源路径
- **FR-015**: 外部进程启动前 MUST 先持久化 attempt reservation；进程启动后状态落库失败时
  MUST 有界停止并确认退出，无法停止时 MUST 保持可管理的 running attempt 与 PID
- **FR-016**: `Popen` 成功后的状态文件或 monitor 初始化失败时，MUST 停止并确认进程树退出；
  无法停止时 MUST 保留 PID 管理权，不得遗留无主进程
- **FR-017**: 对运行中进程的 `poll` 观测失败 MUST 保持 running 并允许后续重试，
  MUST NOT 转成 interrupted 或允许并发 resume
- **FR-018**: 进程停止 MUST 返回“确认已停止 / 确认先前退出 / 无法确认”三态结果；
  timeout、危险命令、用户 stop 或启动补偿只有在进程树退出得到确认时才能写终态并释放
  registry。无法确认时 MUST 持久化 terminationUnconfirmed、保持 running 并禁止 resume，
  MUST NOT 用普通 poll 终态替代退出证明
- **FR-019**: attempt 的 failed/interrupted 终态与关联 session 投影 MUST 由 Repository
  在同一事务中提交或回滚。无法停止的进程若 PID ownership 补写
  也失败，启动调用 MUST 显式失败，MUST NOT 只记日志后返回 created/resumed。用户 abandon、
  plan 协议违规等显式 stop 路径也 MUST 将 attempt 终态与 session 终态放在同一事务；
  提交失败后两行 MUST 仍可重试，MUST NOT 留下“session 已终结、attempt 仍 running”的裂缝
- **FR-020**: command summary 在启动成功及所有启动异常分支均 MUST 遮蔽绝对 executable、
  prompt 和 artifact 路径；session 首次写入后的 plan/result artifact 路径 MUST 不可变
- **FR-021**: running attempt MUST 在 SQLite 中持久化 PID、进程创建时间和未确认终止标记；
  任何确定终态才可清除该标记。sidecar 重启后 MUST 用 PID + 创建时间验证身份；状态文件
  缺失、父进程已退出或身份冲突时 MUST 保持 running 并禁止 resume，MUST NOT 仅凭 PID
  终止可能被复用的进程。terminal 状态文件 MUST 与 durable PID + 创建时间一致才可投影；
  durable 创建时间缺失时，MUST NOT 从状态文件反向补齐或在下一次 poll 将其升级为可信身份；
  进程内 registry MUST 按完整身份与状态路径查找并以对象 CAS 删除，旧 monitor 不得覆盖或
  删除 PID 复用后的新 owner。注册碰撞后的补偿终止若也失败，旧、新 owner MUST 以各自
  完整身份和状态路径并存，且任一 owner 的 poll/stop/清理 MUST NOT 影响另一 owner
- **FR-022**: headless 与 interactive monitor MUST 由同一顶层守护边界执行；reader 启动、
  有界日志写入、running/final 状态写入等任意未预期异常 MUST 触发有界终止。终止或状态
  持久化无法确认时 MUST 保留 registry 与 durable running ownership，MUST NOT 静默退出线程。
  输出 reader 的 queue put MUST 可取消，monitor 提前退出后不得永久阻塞后台线程；已确认
  进程退出但首次 terminal 写入失败时，后续 poll MUST 可重放安全终态并释放 registry owner
- **FR-023**: 每个 coding session MUST 至多存在一个 running attempt，并由数据库唯一约束
  兜底；reservation MUST 持久化尚未跨越 spawn 边界的内部事实，并在调用 adapter 前翻转。
  未启动 reservation 的首次关单失败 MUST 可在 refresh/resume 安全恢复；已经跨越边界但
  ownership 不完整时 MUST 继续 fail-closed。terminal attempt MUST NOT 保留未确认终止标记。
  v33 升级 MUST 将所有既有 running attempt 回填为未确认 ownership，既有 terminal attempt
  保持已清除；两类旧行均标记为已跨越 spawn 边界
- **FR-024**: 所有从 running attempt 投影 poll/stop 观测的写入 MUST 以预期状态做条件 CAS；
  terminal 状态 MUST 单向且 `finished_at` 不可被迟到 running 观测清除。CAS 冲突 MUST 读取并
  返回权威当前行或安全重试，不得复活终态、覆盖并发结果或产生 running + finished_at 的
  矛盾组合；Repository 投影字段中的拼写错误/未知字段 MUST 显式拒绝
- **FR-025**: reservation 跨越 spawn 边界 MUST 使用单条条件更新取得启动权，条件至少包含
  `attempt_id + status=running + launch_started=false`；并发关单已获胜或 CAS 未命中时 MUST 在
  调用 adapter start / `Popen` 前中止，MUST NOT 启动失去 durable owner 的 CLI。adapter object
  construction MUST 在 CAS 前完成并按 pre-spawn 失败关单；`launch_started` 是单向事实，只能由
  专用 CAS 从 false 置 true，Repository 通用更新与 SQLite UPDATE guard MUST 拒绝 true→false
- **FR-026**: stdout/stderr reader 的读取异常 MUST 以独立故障信号传给 monitor，MUST NOT 与
  正常 EOF 混淆；进程已退出且队列瞬时为空时仍 MUST 等待 reader 的 EOF/失败 sentinel，不得
  自行判定 stream 完成。等待进程退出超时后的补偿 MUST 使用整棵进程树终止与确认契约，不能
  只 kill 父进程后写 terminal。无法确认时继续保留 running ownership
- **FR-027**: domain value MUST 拒绝其可见的 status/`termination_unconfirmed` 与 PID/创建时间
  矛盾；Repository 与 SQLite guards MUST 额外拒绝 `launch_started=false` 时存在 PID/创建时间，
  并保证创建时间非空时 PID 非空。running 必须 `termination_unconfirmed=true`，terminal 必须
  为 false。更新 API MUST NOT 静默纠正调用方显式提交的矛盾状态；不得把 domain 未携带的
  `launch_started` 描述成 domain 构造器保证

### Constraints & Compatibility

- **CC-001**: MUST NOT 改动外部 coding 的授权链——固定专员、已配置能力组合、
  正式任务、组合已发布这四重限定保持原样
- **CC-002**: MUST NOT 改动方案/实现两阶段协议与产物要求
- **CC-003**: MUST NOT 新增数据表、配置项、密钥或公开 UI 事件
- **CC-004**: MUST NOT 引入静默降级——任何无法确定目标仓库的情况一律 fail-closed
- **CC-005**: 现有外部 coding 相关自动化测试 MUST 全部保持通过

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [ ] **UI** (`frontend/src/`, `src-tauri/`)
- [ ] **Desktop API Bridge** (`src/desktop_api/`)
- [x] **Business** (`src/business/`) — 外部 coding session 启动编排、CLI 指令构造、
      工具参数契约
- [x] **Execution** (`src/execution/`) — 无 shell PATH/PATHEXT 解析、命令摘要脱敏与 spawn 后初始化补偿
- [x] **Data** (`src/data/`) — session 首次持久化携带必填 plan/result 路径；SQLite v33 为
      `external_coding_attempts` 增加三个内部恢复字段、单活 partial unique index 与 ownership
      跨字段写入 guard
- [ ] **Recording** (`src/recording/`)
- [ ] **Utils** (`src/utils/`)

### Agent Impact

- 受影响 Agent：仅持有"外部 Coding"能力组合的固定执行专员
- 工具变更：`start_external_coding_session` 的目标仓库参数由选填改为必填，参数说明改写；
  headless CLI 命令补齐当前版本兼容参数与确定性 artifact 输出
- 系统提示词变更：无——填参约束表达在工具参数说明中
- 调度分发变更：无

### Data Store Impact

- **SQLite**：不新增表。v33 为 `external_coding_attempts` 增加 nullable
  `process_create_time`、默认 false 的 `termination_unconfirmed` 与默认 false 的
  `launch_started`，并增加每 session 至多一个 running attempt 的 partial unique index；
  既有 running 行安全回填为 `NULL/true/true`，既有 terminal 行为 `NULL/false/true`。
  ORM check constraints 与 v33 insert/update triggers 拒绝 running/terminal ownership、pre-spawn
  identity 和 PID/创建时间的矛盾组合。字段只用于内部恢复，不进入公开 DTO/UI event
- **DuckDB**：无
- **Config**：无新增键。既有工作区根配置的解释方式改变（相对路径的基准从进程当前目录
  改为目标仓库），键名与默认值不变
- **Secrets**：无

### Event Impact

- 新增事件：无
- 事件载荷变更：无
- 新增监听：无

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 未指明目标仓库的启动尝试 100% 被拒绝，且系统中零残留（无工作区、
  无分支、无会话记录）
- **SC-002**: 指明外部仓库且 worktree 根为默认相对配置时，本次会话的工作区与分支均位于
  该仓库侧，Exemplar 新增 worktree/分支数为 0；绝对 worktree 根与 artifact 根分别服从
  其既有配置，不纳入“目标仓库侧”计数
- **SC-003**: 两个外部工具的启动指令中，任务书获取指示的存在率为 100%，
  覆盖方案阶段、实现阶段与续跑三种情形
- **SC-004**: 目标位置无效的各类情形（不存在 / 非仓库 / 无提交），
  返回的说明均可让用户判断出下一步该做什么，且不含底层异常文本
- **SC-005**: 现有外部 coding 相关自动化测试全部通过，数量不减少
- **SC-006**: 使用 Windows 默认命令名 `codex` 的真实生产路径验证能在外部临时仓库进入
  `plan_ready`，生成含精确任务目标的有效 `PLAN.md`，且命令摘要不暴露 artifact 路径
- **SC-007**: 相对 artifact 根、handoff/mkdir 部分失败、Git 删除非零、spawn 后初始化失败、
  attempt 落库失败及 poll 异常均有故障注入测试；任何路径均不产生无主进程或假终态
- **SC-008**: monitor 初始化后终止未确认、monitor 运行期终止未确认、三类 CLI 启动异常、
  session 投影提交失败及 PID ownership 补写失败均有故障注入测试；无法确认的进程在进程内
  与重启后状态文件中均保持 running，且不会开放重复 resume
- **SC-009**: 状态文件初写与 termination marker 双双失败时，attempt 仍持久化 PID、创建时间
  与未确认标记；清空进程内 registry 模拟重启后，匹配身份可再次 stop，父进程消失或身份
  不匹配则保持 fail-closed。monitor 顶层异常不会留下无主运行进程
- **SC-010**: PID 复用碰撞、旧 monitor 迟到删除、terminal PID/创建时间冲突、session/attempt
  原子提交失败、重复 running attempt 及 pre-spawn reservation 关单失败均有故障注入测试；
  任一情形都不会误终止新 owner、产生双活 CLI 或留下不可恢复的未启动 reservation
- **SC-011**: v32 running/terminal 迁移、durable 创建时间缺失的连续两次 refresh、显式 stop
  原子提交失败、terminal 后迟到 running CAS、monitor terminal 重放、满队列 reader 取消及
  PID 碰撞后补偿终止失败均有确定性测试；扩大范围回归不少于 `194 passed`，且这些场景中
  不出现身份洗白、终态复活、跨表裂缝、后台 reader 泄漏或 owner 串扰
- **SC-012**: reservation→launch 并发关单、reader 读取异常、首次 session 持久化结果未知、
  分支探测故障分类及四类 attempt 跨字段非法组合均有确定性故障注入测试；这些场景中 CLI
  启动次数、进程树终止结果、恢复 session 标识和数据库约束结果均可直接断言
- **SC-013**: 进程先退出后 reader 延迟失败、adapter factory 构造失败、Git OS/HEAD 探测故障、
  `launch_started` Repository 回退与 SQLite 原始 UPDATE 均有确定性测试；任一场景都不产生
  假成功、无 PID 的已启动 reservation、路径泄漏或 spawn 边界倒退

## Assumptions

- 目标仓库由派活方在委派信息中交代给执行专员。系统不承诺模型一定会正确交代——
  本特性提供的硬保证仅限"交代不清时拒绝执行"，而非"一定交代得清"
- 项目当前为单用户、未发布状态，无外部脚本或第三方消费者依赖既有参数契约，
  故参数由选填改必填可直接生效，不需要过渡期或双写兼容
- 大脑记忆只注入主助理、不进入执行专员上下文，这一既有设计保持不变；
  本特性不通过记忆机制解决目标仓库传递问题
- 外部编码工具的命令行参数由各自版本决定，本特性不锁定其版本；
  参数漂移仍按既有约定处理
- 隔离工作区、方案/实现两阶段协议、合并前冲突分析等既有能力保持不变

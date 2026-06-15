# Feature Specification: 子进程事件推送(Process Event Push)

**Feature Branch**: `022-process-event-push`
**Created**: 2026-06-15
**Status**: Draft
**Input**: User description: "基于 docs/superpowers/specs/2026-06-15-process-event-push-design.md 的已定稿设计,为 subagent / specialist 提供一种'等事件、有进展叫我'的低延迟进程订阅能力,不再循环 poll。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - subagent 阻塞等到状态边界即返回 (Priority: P1)

subagent 起一个会跑数十秒的命令后,不再循环 poll,而是发起一次"等事件"调用,并指定最长等待时间;一旦进程从运行态切换到 completed / failed / terminated,subagent 在毫秒级被唤醒并拿到当前状态与 exit code,可以立刻决定下一步;若到达超时仍未结束,得到一个空事件 + 当前状态的"无事发生"答案,继续按自己的节奏决定要不要再等。

**Why this priority**: 这是整个 feature 的核心动机——把"轮询直到进程结束"换成"在状态边界上被唤醒"。没有它,subagent 仍然要靠 process_wait + process_poll 组合;有了它,LLM token 与时延都显著下降,失败感知从"下一次 poll 才发现"变成"事件触发时就发现"。

**Independent Test**: 不依赖另两个事件类型即可独立验证——真起一个 sleep 短时后失败的子进程,subagent 调一次 wait_for_process_event 并指定足够大的超时,验证收到 state_changed: failed + exit code,且唤醒时刻接近进程结束时刻而非超时上限。

**Acceptance Scenarios**:

1. **Given** subagent 起了一个 5 秒后正常退出的子进程, **When** subagent 调 wait_for_process_event(processId, timeoutMs=10000), **Then** 调用在子进程退出后立即返回,事件列表包含一条 state_changed,状态为 completed,exitCode = 0
2. **Given** subagent 起了一个 5 秒后退出码为 1 的子进程, **When** subagent 调 wait_for_process_event(processId, timeoutMs=10000), **Then** 调用在子进程退出后立即返回,事件列表包含一条 state_changed,状态为 failed,exitCode = 1
3. **Given** subagent 起了一个会跑 60 秒的子进程, **When** subagent 调 wait_for_process_event(processId, timeoutMs=2000), **Then** 调用在大约 2 秒后返回,事件列表为空,当前状态为 running,exit code 为空,调用方据此决定是否再等

---

### User Story 2 - subagent 在累积输出过阈值时被唤醒去读日志 (Priority: P2)

subagent 起的命令分批吐日志,subagent 想"有新内容可读"就立即去读 process_logs,而不是等到进程退出。系统按累积字符阈值粗粒度通告:每写入约 4096 字符发一个 log_chunked 信号(不带原文),subagent 收到信号后用 process_logs 拉对应区间。这样既避开"一行一通告"的噪声,也不会让 subagent 一直被原文淹没。

**Why this priority**: 阶段性日志可读对长任务很有价值(看到第 3 步已开始、看到第 5 步开始报警告),但 subagent 不应该把行级 stdout 塞进自己的上下文窗口。把"有新内容可读"做成信号 + 让 subagent 决定读多少,是 token 友好的折中。P2 是因为没有它,P1 仍能交付核心价值。

**Independent Test**: 不依赖 stalled,起一个会快速吐 10000 字符的子进程,subagent 调一次 wait_for_process_event,验证返回事件列表含至少一条 log_chunked,deltaChars / totalChars 与实际累积字符数大致吻合,且后续再次累积过阈值时还能再触发。

**Acceptance Scenarios**:

1. **Given** subagent 起了一个会写出 ~8000 字符且持续运行的子进程, **When** subagent 调 wait_for_process_event(processId, timeoutMs=10000), **Then** 调用在累积写入达到阈值后立即返回,事件列表至少包含一条 log_chunked,字段含 totalChars 与 deltaChars,deltaChars 与该次阈值大致一致
2. **Given** 同一进程在 log_chunked 事件被读取后继续输出又一批同样多的字符, **When** subagent 用新游标再次调 wait_for_process_event, **Then** 可以再次拿到一条新的 log_chunked,且阈值基线已经在前一次通告后复位

---

### User Story 3 - subagent 在 stalled 时被唤醒去判断是否还该等 (Priority: P3)

subagent 起的命令长时间不输出(卡在等用户输入、远端无响应等),subagent 需要在静默到阈值后被通知一次,得到"已经空闲了 XX 毫秒"的信号,而不是被无限期挂起。stalled 只在静默期内通告一次,直到再次出现输出后才会重新计时——不会刷屏,但也不至于完全静音。

**Why this priority**: 这是"防傻等"的辅助信号,而不是核心交付。没有它 subagent 可以靠 timeoutMs 周期性醒来自己判断;有它则少一次冗余调用,语义也更明确。P3 是它在多数场景下不是关键路径。

**Independent Test**: 起一个长 sleep + 不写日志的子进程,subagent 调 wait_for_process_event 等到超过 stalled 阈值,验证收到一条 stalled 事件 + idleMs;紧接着不写新输出再调一次同样长的等待,验证不再重复发 stalled。

**Acceptance Scenarios**:

1. **Given** subagent 起了一个长时间不输出也不退出的子进程, **When** subagent 调 wait_for_process_event(processId, timeoutMs=15000) 且等待时间超过 stalled 阈值, **Then** 调用返回时事件列表至少包含一条 stalled,idleMs ≥ 配置阈值
2. **Given** 同一进程在收到一次 stalled 后仍不写新输出, **When** subagent 用新游标再次调 wait_for_process_event, **Then** 不再收到第二条 stalled——直到有新输出出现并再次静默到阈值
3. **Given** 同一进程收到一次 stalled 后又开始写入并再次静默, **When** subagent 用新游标再次调 wait_for_process_event 且等待时间超过 stalled 阈值, **Then** 收到一条新的 stalled,idleMs 从最近一次输出开始重新计算

---

### Edge Cases

- subagent A 试图等 subagent B 起的进程: 跨会话归属校验拒绝,返回 permission_denied;不通告任何事件,也不暴露该进程的存在
- subagent 传入的 processId 不存在(从未创建 / 已被清理): 返回 process_missing 错误码,与既有 process_poll / process_wait 一致
- subagent 传入的 sinceCursor 早于当前事件 deque 最旧 sequence(被环形 buffer 覆盖): 返回 cursorTooOld 标志 + 当前状态,subagent 改走 process_poll + process_logs 兜底,不阻塞、不抛错
- 进程在 wait_for_process_event 调用前就已退出: 立刻返回(条件 1 命中——deque 中有未消费 state_changed),无超时等待
- 多个 log_chunked 在等待期间累积: 一次调用返回多条事件,按 sequence 升序;游标推到最新一条
- 子进程仅在 stdout 或 stderr 单边吐输出: stalled 与 log_chunked 都按累计输出统一判断,不区分流向
- 调用方传入 timeoutMs 小于下限或大于上限: 钳位到合法区间,沿用既有 process_wait 边界,不报错
- ProcessManager 内部异常(罕见): 工具层返回 error_json,不污染其它工具调用,不触发跨工具级联失败
- sidecar 进程重启后再次唤起: 旧 processId 已失效(事件不持久化),subagent 收到 process_missing 与既有进程工具一致;无残留事件穿越进程边界

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供一个新的进程事件订阅工具(命名 `wait_for_process_event`),供 subagent / specialist 调用;输入参数为 `processId`、可选的 `sinceCursor`(整数游标)和可选的 `timeoutMs`(毫秒)
- **FR-002**: 系统 MUST 仅允许"起该进程的那个会话"订阅其事件,跨会话调用 MUST 返回 permission_denied,且不暴露目标进程是否存在
- **FR-003**: 系统 MUST 在每个进程上维护一个有界事件队列、一个 per-process 单调递增的事件 sequence、一个用于阻塞唤醒的条件变量;事件 sequence 仅在当前进程生命周期内单调,跨进程不可比
- **FR-004**: 系统 MUST 支持三类事件,且 MUST 不在事件中携带原文 payload:
  - `state_changed`:状态从 running 转到 completed / failed / terminated 时一次,payload 含 `status` 与 `exitCode`
  - `stalled`:running 状态下静默时长超过配置阈值时一次,payload 含 `idleMs`;通告后 MUST 不重复,直到出现新输出后再次静默达阈值
  - `log_chunked`:累积输出字符数自上次通告起增加超过配置阈值时一次,payload 含 `totalChars` 与 `deltaChars`;触发后阈值基线 MUST 复位
- **FR-005**: `wait_for_process_event` MUST 在 deque 中存在大于 `sinceCursor` 的事件时立即返回该次及之后所有未消费事件,按 sequence 升序;首次调用未传 sinceCursor 等价于从 0 开始
- **FR-006**: `wait_for_process_event` MUST 在没有新事件时阻塞等待,直到出现新事件被唤醒或达到 `timeoutMs` 超时;超时 MUST 返回空事件列表 + 当前进程状态,且 MUST NOT 视为错误
- **FR-007**: `wait_for_process_event` MUST 返回当前进程的 `status` 与 `exitCode`,以及调用方下一次需传入的 `cursor`(单调推进)
- **FR-008**: 当 `sinceCursor` 早于当前事件队列中最旧 sequence(被环形 buffer 覆盖)时,`wait_for_process_event` MUST 返回 `cursorTooOld=true` + 当前状态,subagent 据此走 process_poll + process_logs 兜底
- **FR-009**: 系统 MUST 让 `stalled` 与 `log_chunked` 阈值、事件队列容量可通过配置调节;配置项 MUST 走 UnifiedConfigManager,不允许业务代码硬编码,不暴露在 Settings UI
- **FR-010**: 系统 MUST 保持既有进程工具 `process_poll` / `process_logs` / `process_wait` 行为与签名完全不变;`wait_for_process_event` 与它们并存,不替代任何一个
- **FR-011**: 事件 MUST NOT 进入 UI Event Registry,也 MUST NOT 出现在公开 SSE / 事件流;前端不直接订阅或感知这些事件,主助理也不直接订阅
- **FR-012**: 事件 MUST NOT 跨 sidecar 进程生命周期持久化;sidecar 重启后,旧 processId 与对应事件队列一并失效
- **FR-013**: `wait_for_process_event` MUST NOT 被声明为 `is_concurrency_safe`,与既有进程工具的并发约束保持一致
- **FR-014**: `wait_for_process_event` MUST 在静默期内"懒"判定 stalled——只在被调用时检查"距上次输出是否过阈值且尚未通告",而不是后台线程定时扫描
- **FR-015**: 进程事件累积过事件队列容量时,旧事件 MUST 被环形覆盖;系统 MUST NOT 通过抛错或丢弃新事件来表达"队列满"

### Key Entities *(include if feature involves data)*

- **ProcessEvent**:一条派生信号,字段含 `sequence`(per-process 单调)、`type`(state_changed / stalled / log_chunked)与小数量 type 相关 payload 字段;事件不含日志原文
- **ProcessEventCursor**:调用方在连续 `wait_for_process_event` 调用之间携带的整数游标,语义是"我已消费到 ≤ cursor 的所有事件,下次只给我更大的";游标仅在单个 processId 上下文中有效
- **ProcessRecord(扩展)**:既有进程记录上增加事件 deque、事件 sequence、用于阻塞唤醒的条件变量、最近输出时间、阈值复位基线与 stalled 上次通告基线;这些字段是 ProcessRecord 的内部状态,不直接对外可见

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: 既有 `process_poll` / `process_logs` / `process_wait` 工具的入参、出参与行为 MUST 不变;不允许借本 feature "顺手"重构它们
- **CC-002**: 100% 调度约束 MUST 保留——主助理不订阅子进程事件,工具仅暴露给 subagent / specialist 视图;主助理对子进程的可见度仍走既有 014 子任务活动事件链路
- **CC-003**: secret / 日志原文 MUST NOT 出现在事件 payload;事件粒度停在"信号 + 计数 + 状态",原文读取仍走 `process_logs`
- **CC-004**: 进程归属判定 MUST 复用既有 `_process_for_current_session` 校验,不允许新增分支或绕过路径
- **CC-005**: 配置项 MUST 仅来自 UnifiedConfigManager(`agent_tools.process.*` 命名空间),不引入新配置文件、不写入新表
- **CC-006**: 事件机制 MUST 不增加跨进程 / 持久化 / 通用事件总线等基础设施;若未来出现第二类事件源,再做增量提取,本 feature 不预留

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **Business** (`src/business/`) — Agent 工具层新增 `wait_for_process_event` 工具(预期落在既有 `command_tools.py` 同模块)
- [x] **Execution** (`src/execution/`) — `ProcessManager` 增加事件 deque、sequence、condition、新方法 `wait_for_event`,以及输出回调里的累积字符与最近输出时间维护
- [x] **Data** (`src/data/`) — `agent_tools.process.*` 三个新配置键,通过 `UnifiedConfigManager` 读写;默认值随代码下发,不需要新建表

未触及:UI、Desktop API Bridge、Recording、Utils。

### Agent Impact *(if touching Agent system)*

- 受影响的 Agent: subagent(临时)与 specialist(固定),两者通过 AgentConfig 默认能装备进程工具集合;主助理(Assistant)显式不暴露
- 新工具:`wait_for_process_event`;不修改既有进程工具 handler
- 系统 prompt 变化:可在 subagent / specialist 工具目录里追加该工具的描述,引导"长任务等事件而非循环 poll";主助理的 prompt 不变
- 调度变化:无;100% 调度模型不动

### Data Store Impact *(if touching data layer)*

- **SQLite**:无新表 / 无 migration
- **DuckDB**:不涉及
- **Config** (`src/data/unified_config.py`):新增三个键,均带默认值与上下限钳位
  - `agent_tools.process.event_buffer_size`(默认 64,上限 512)
  - `agent_tools.process.stalled_threshold_ms`(默认 10000,上限 600000)
  - `agent_tools.process.chunk_threshold_chars`(默认 4096,上限 65536)
- **Secrets**:不涉及

### Event Impact *(if adding/changing events)*

- 不在 `src/utils/events.py` 中新增 blinker 事件;事件仅活在 ProcessManager 内存中
- 不在 `src/desktop_api/ui_events.py` 中注册任何新 UI 事件
- 无新增前端事件 listener

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: subagent 用 `wait_for_process_event` 跟踪一个 30 秒后退出的进程时,从"进程实际退出"到"subagent 收到 state_changed 并返回"的延迟 MUST ≤ 200 ms(本机 idle 环境)
- **SC-002**: 同一场景下,subagent 完成"等到进程退出并拿到 exit code"过程中触发的 LLM 调用次数 MUST ≤ 既有 process_wait + 一次 process_poll 组合的次数,且不引入额外回合
- **SC-003**: subagent 起一个会产生 ~16 KB 输出的进程,在累积输出过阈值时获得至少一条 log_chunked 事件;事件中的 `totalChars` MUST 与同期 `process_logs` 看到的实际累计字符差异 ≤ 阈值大小,无原文进入 subagent 上下文
- **SC-004**: 进程长时间静默(超过 stalled 阈值)时,subagent 每次"静默到阈值"周期内 MUST 仅收到一条 stalled 事件;在该周期内不论 wait 调用多少次都不会重复
- **SC-005**: `wait_for_process_event` 在跨会话调用、processId 不存在、cursor 已被覆盖三种异常路径上 MUST 返回各自既定语义(permission_denied / process_missing / cursorTooOld=true),且不污染其它工具或 ProcessManager 状态
- **SC-006**: 既有 `process_poll` / `process_logs` / `process_wait` 单元测试与契约测试在引入本 feature 后 MUST 全部保持通过,无任何行为/签名回归

## Assumptions

- 假设 subagent 与 specialist 在其 AgentConfig 默认能装备 `wait_for_process_event`,并默认与既有 process_* 工具同一权限边界
- 假设事件队列容量 64、stalled 阈值 10 秒、chunk 阈值 4096 字符在当前 PM / Programmer / Trial 之外的常规调度场景下足够;若个别场景需要,通过 UnifiedConfigManager 调节
- 假设 ProcessManager 既有 stdout/stderr 收集线程能稳定接收回调(用于更新最近输出时间与累积字符)——这是当前实现已有的能力,不需要新增 IO 路径
- 假设事件仅在 sidecar 进程生命周期内活;持久化、跨进程恢复、跨用户重放都不在范围内
- 假设主助理(Assistant)对子进程状态的可见性继续走既有 014 子任务活动事件;本 feature 不为它增加任何新通道

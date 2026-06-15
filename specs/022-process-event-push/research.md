# Phase 0 Research: Process Event Push

> 本 feature 的所有技术决策均已在 `docs/superpowers/specs/2026-06-15-process-event-push-design.md` 完成脑暴定稿;本研究文档把这些决策与 spec 中的契约对齐,并补两条 clarify 阶段新增决策的依据。无 NEEDS CLARIFICATION 遗留。

## R-001 事件通道形态:per-process deque + Condition,不抽通用 bus

- **Decision**: 直接在 `ProcessRecord` 上挂 `events: deque[ProcessEvent]`(默认 maxlen=64)、`event_sequence: int`、`event_condition: threading.Condition`;`ProcessManager._emit_event_locked` 集中 append + notify_all;`wait_for_event` 在同一个 condition 上等。
- **Rationale**:
  - `ProcessManager` 已经有 record dict + `_lock`(`threading.RLock`),deque + condition 是直接延伸,代码量 < 50 行。
  - 通用事件总线意味着多消费者、跨进程订阅、event type registry 等基础设施——当前只有一个消费者(起进程的那个 subagent / specialist),没有第二个事件源,YAGNI(spec CC-006)。
  - condition 与 RLock 配合阻塞唤醒,无需 polling loop,事件触达延迟天然贴近 SC-001 的 200 ms 上限。
- **Alternatives considered**:
  - `asyncio.Event` + 协程订阅:`ProcessManager` 和 `command_tools.py` 都是同步代码(handler 同步返回 JSON 字符串),引入 asyncio 会污染既有协议且无收益。
  - `blinker` signal:跨模块广播语义不符——这里是"同会话一对一"订阅,广播反而要在订阅侧加额外的会话/processId 过滤逻辑。
  - 通用 `event_bus.py` 模块:违反 YAGNI 决策,且与 spec CC-006 / FR-011 直接冲突。

## R-002 事件类型与产生时机

- **Decision**: 三类事件 `state_changed` / `stalled` / `log_chunked`,均不带原文 payload。
  - `state_changed`:在 `_refresh_locked` 把 status 从 `running` 改成 `completed` / `failed` 时 emit。`terminated` 路径由 `terminate` / `cleanup` 显式分支 emit(`_refresh_locked` 对 `terminated` 是 early-return)。`closed` 不发(closed 是调用方主动关闭句柄,不是状态边界)。
  - `log_chunked`:在 `_start_reader` 的 reader 线程内 append chunk 时累加 `total_output_chars`,达到阈值时 emit + 重置基线(`last_chunk_announce`)。基线计算用绝对累计字符 - 上次通告值,而不是 chunk-by-chunk 攒,这样跨多次小 chunk 也能正确合并通告一次。
  - `stalled`:**完全懒判定**——只在 `wait_for_event` 被调用时检查 `now - last_output_at >= threshold and last_stalled_announce_output_at != last_output_at`,若成立 append 一个 stalled 事件到 deque(此时仍持 lock)再返回。后台 reader 线程不参与 stalled 判定,避免新增定时器线程。
- **Rationale**:
  - `_refresh_locked` 已经是状态机的唯一收敛点(被 start / poll / wait / stop / cleanup 反复调用),嵌入 emit 不破坏既有控制流,且 lock 已持。
  - `_start_reader` 内部的 reader 线程已持 lock 才 append chunks,在同一段 lock 区内累加字符与判定 chunk 阈值不需要新锁。
  - stalled 用懒判定可以省一个后台定时器线程,延迟最坏等于"下次 wait 触发时间",对 LLM 工作节奏(每 30 秒一次 wait)是完全够用的;同时 SC-004 "在一个静默周期内 wait 多少次都只收一条" 由 `last_stalled_announce_output_at` 自然保证。
- **Alternatives considered**:
  - stalled 用后台 `threading.Timer`:多一个线程要管 cleanup;timer 在 lock 抖动时也容易遗漏唤醒。
  - 在 `_start_reader` 内按行 emit `log_chunked`:8000 字符 ÷ 80 字符/行 = 100 条事件,deque 直接被自己刷爆;且 SC-003 已经明确"按累积字符阈值粗粒度通告",与设计文档一致。

## R-003 cursor 续约语义(clarify Q1)

- **Decision**: `wait_for_event` 返回包永远含 `cursor` 字段,即使 `cursorTooOld=true`;cursor 取自队列里最新事件的 sequence,空队列时取 `event_sequence`(per-process 单调计数器的当前值)。subagent 直接用这个 cursor 作为下一次 `sinceCursor`。
- **Rationale**:
  - cursor 单调推进、subagent 无须切换路径,与 FR-007(返回包含 cursor)语义一致。
  - 空队列时 fallback 到 `event_sequence` 等价于"未来分配的下一条 sequence 之前的所有事件你都不要"——语义即"没有任何更新的事件",新事件来时一定大于此 cursor,可被正确返回。
- **Alternatives considered**:
  - cursorTooOld 时不返回 cursor、强制 subagent 用 process_poll + process_logs 兜底:契约多一条分支,prompt 要解释,LLM 容易选错路径。
  - cursorTooOld 时返回 `cursor=0`:队列被填满时立刻会再次 cursorTooOld,潜在死循环。

## R-004 纯静默场景的 stalled 语义(clarify Q2)

- **Decision**: `ProcessRecord` 创建时 `last_output_at = started_at`(即进程启动时刻);"从未产生过输出 + 静默达阈值"与"产生过输出后又静默达阈值"走完全相同的懒判定路径,各发一条 stalled。
- **Rationale**:
  - 与 FR-014 / R-002 的懒判定口径一致,无分支。
  - 对纯 sleep / 等待外部的子进程(ping、wait-for-network)更友好——subagent 也能被通告"它一直没动静",而不是空等。
- **Alternatives considered**:
  - 只有 reader 真有过 append 才开始计时:增加一条隐式状态,需要新的"is_started_output"标志,代码与测试都会膨胀。
  - 启动后发一条特殊 `silent_start` 信号:多一个事件类型,subagent prompt 要解释,且效果与 stalled 等价。

## R-005 命名 / 模块归属

- **Decision**:
  - 工具名:`wait_for_process_event`(与 design 一致,沿用既有 `process_*` 前缀变体)。
  - 模块归属:落在既有 `src/business/agents/tools/command_tools.py`,跟 `process_poll` / `process_logs` / `process_wait` 同 module 同前缀。
  - `ProcessManager` 新方法 `wait_for_event(process_id, *, since_cursor, timeout_ms) -> dict`;新私有方法 `_emit_event_locked(record, event_type, payload)`。
- **Rationale**:命名连续性、定位习惯连续性;不新建子模块。
- **Alternatives considered**:无收益的拆分(新 module / 新工具组)被拒。

## R-006 并发安全声明

- **Decision**: `wait_for_process_event` MUST NOT 被声明 `is_concurrency_safe`;沿用既有 process 系列工具的全部非并发约束(`src/CLAUDE.md` 已写明 "process 系列... 不得标记并发安全")。
- **Rationale**:工具在调用线程上拿 RLock + condition 等待,LLM 同轮触发多次会被 AgentLoop 串行调度;也避免与同会话内的其它 process_* 工具产生 lock 争抢的灰区。
- **Alternatives considered**:声明并发安全可让同一回合多进程一起等——但实际工作流是"主助理派给一个 subagent 盯一个进程",并发场景不存在。

## R-007 配置项命名与默认值

- **Decision**:三个新键放在既有 `agent_tools.process.*` 命名空间下:
  - `agent_tools.process.event_buffer_size`(默认 64,上限 512)
  - `agent_tools.process.stalled_threshold_ms`(默认 10000,上限 600000)
  - `agent_tools.process.chunk_threshold_chars`(默认 4096,上限 65536)
  在 `AgentToolsProcessConfig` 上补三个字段,在 `UnifiedConfigManager` 加三个 getter(沿用 `_get_bounded_positive_int` / `_get_bounded_positive_int` 模式)。
- **Rationale**:命名空间已存在;沿用 dataclass + getter 双轨,默认值随代码下发、SQLite `app_settings` 可覆盖,与既有 `default_timeout_ms` 等键完全一致。
- **Alternatives considered**:挂在新顶级命名空间(`agent_tools.events.*`)会让"和进程相关"信息散落两处。

## R-008 测试边界

- **Decision**:
  - **ProcessManager 单测**:在 `tests/execution/test_process_manager_events.py` 新建。覆盖 R-001..R-007 所有行为路径(参见 spec 测试章节)。用真子进程(短 sleep + echo)而不是 mock subprocess,确保 reader 线程真的会跑。
  - **工具层单测**:在 `tests/business/agents/tools/test_process_event_tool.py` 新建。归属校验、`process_missing`、timeoutMs 上下钳位、配置 getter 通路用 monkeypatch。
  - **行为契约**:在 `tests/integration/test_process_event_flow.py` 新建。一条端到端测,真起 subprocess,验证 `wait_for_process_event → process_logs → wait_for_process_event` 整链路。
- **Rationale**:测试金字塔与既有同类 feature(015 / 017)一致;避免 mock 掉 subprocess 后又踩"测试通过但真子进程行为不一致"的坑。
- **Alternatives considered**:UI 层 / 前端 E2E 不在范围(spec FR-011 不进 UI Event Registry),跳过。

## 未解决项

无。所有 spec 中标注的契约面、配置面、测试面均已对齐设计文档和 `src/CLAUDE.md` 约束。

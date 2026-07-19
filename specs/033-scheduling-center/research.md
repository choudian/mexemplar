# Research: Scheduling Center（调度中心）

**Phase 0 产出**。解决 spec Assumptions 与设计稿 §14 的全部开放问题。每条 Decision / Rationale / Alternatives considered。接入点证据来自 4 路代码库调查（见 plan.md 引用）。

---

## R1. 命名区隔：调度中心 vs `graph_scheduler` vs 「100% 调度」

**Decision**：中文产品名「调度中心」；模块 `src/business/scheduling/`；类 `SchedulerWorker` / `SchedulerService` / `SessionLauncher` / `RunCompletionMonitor`；表 `scheduled_tasks` / `scheduled_task_runs`。在模块 `AGENTS.md` 与 `docs/ARCHITECTURE.md` 点明区隔。

**Rationale**：「调度中心」承载完整平台语义（触发 + 执行 + 监控 + 通知，XXL-Job 式）。三处「调度」词汇重叠靠文档区隔而非改名：
- **调度中心（scheduling）= 时间维度触发中枢**（到点唤醒）
- **`graph_scheduler` = 依赖维度推进器**（任务图 DAG 就绪推进节点）
- **「100% 调度」（dispatch）= 任务派发机制**（主助理派活给执行体）

**Alternatives**：
- 「定时中心 / 计划中心 / 自动化中心」：避撞名但语义偏窄（漏掉「立即触发」与「监控通知」）。
- 改 `graph_scheduler` 名字：回归风险大、无收益，拒绝。

---

## R2. 时区 / 工作日 / DST / `next_fire_at` 存储

**Decision**：
- 数据库 `next_fire_at` / `last_fired_at` 等 `*_at` 列一律**存 UTC naive**（项目时间戳惯例 `utc_now_naive()`，`base_repository.py`），DB 列 `TEXT`（ISO8601）。
- 调度参数（`run_at` / `time_of_day` / `weekdays`）保留用户意图语义：无 offset 的 ISO 与日历时刻是**用户本地时区**（用户说「17 点」指本地 17 点），带 offset 的 ISO 服从其 offset；在 `schedule_payload` JSON 存原始意图字段，**不把 naive 本地时间误当 UTC**。计算 `next_fire_at` 时用 `zoneinfo`（Python 3.9+ 标准库）按显式 `tz` 或系统本地时区推导再转 UTC 存。
- 时区来源：`get_unified_config()` 的用户时区设置（若已有），否则由直接运行时依赖 `tzlocal` 发现系统本地时区；依赖缺失或发现失败时拒绝创建调度并记录错误，绝不静默回退 UTC。
- DST：用 `zoneinfo` round-trip 显式识别切换边界；ambiguous 时刻取 `fold=0` 的较早实例，不存在时刻按 DST gap 向后推进到真实本地时刻，两者均记 warning。

**Rationale**：存 UTC 是跨「app 重启时段」一致性的唯一安全方式（naive 本地时会在 DST 切换后错一小时）。意图字段保留本地语义避免「9 点」被误解。时区换算使用 stdlib `zoneinfo`，只引入 `tzlocal` 发现系统的 IANA 时区名，不引入完整时间规则库。

**Alternatives**：
- 存本地 naive：DST 切换错乱，拒绝。
- 存带 tzinfo 的 aware：项目惯例是 naive UTC（`utc_now_naive()`），混用会撞既有 Repository 比较逻辑。
- 引入 `pendulum`/`dateutil` rrule：设计稿 §15 已排除完整 rrule（留后续批次），stdlib 够用。

---

## R3. 周期 `next_fire_at` 计算算法（第一批）

**Decision**：第一批支持 4 种周期，各自一个纯函数，输入「上次触发时刻（本地）+ payload」输出「下次触发时刻（本地）」：
- **每隔 N（分钟/小时）**：`last + interval`（若已过，滚动到未来首个 `last + k*interval`）。
- **每天某时**：次日 `time_of_day`。
- **每周某天某时**：下一个匹配 weekday 的 `time_of_day`。
- **工作日**：周一 00:00–周五 23:59（周末跳到下周一 `time_of_day`）。

统一入口 `compute_next_fire(payload, after_local) -> datetime`（纯函数，无副作用，易测）。`SchedulerWorker` 周期扫描 + 触发后调它滚动。

**Rationale**：4 种覆盖典型家用场景（设计稿 §6）；不引入 cron/rrule（§15 非目标）。纯函数化便于确定性单测（Constitution IV）。

**Alternatives**：
- APScheduler：设计稿 §1.2 已核实未用、§15 不引入；且 APScheduler 的持久化 jobstore 与项目 SQLite 自管 migration 体系不契合。
- 完整 cron 表达式：超第一批范围。

---

## R4. 全局并发上限

**Decision**：第一批**不做**多不同任务同时触发的全局 session 数上限；仅做 per-task 重入控制（D9：同任务上次未静默本次跳过）。多不同任务并发默认允许（runtime 已是 per-session worker 门控，`assistant_runtime.py:68` `_workers` dict）。

**Rationale**：单用户家用、周期任务一天几次，并发量天然低；runtime per-session 门控已隔离；加全局上限是预设优化。per-task 重入是真实问题（runtime 跨 session 真并发无天然串行保护，已核实）。

**Alternatives**：
- 全局信号量限 N 个并发 scheduled 会话：留后续批次，按实际负载再加（YAGNI）。

---

## R5. 桌面通知 capabilities（`tauri-plugin-notification`）

**Decision**：从零安装，最小授权 `notification:default`（不申请 `requestPermission` 等额外权限）。四层改动：
1. `src-tauri/Cargo.toml`：`tauri-plugin-notification = "2"`
2. `src-tauri/src/lib.rs`：`.plugin(tauri_plugin_notification::init())`
3. `src-tauri/capabilities/default.json`：`"notification:default"`
4. `frontend/package.json`：`@tauri-apps/plugin-notification`，前端收到 `scheduled_task.completed/failed/needs_takeover` 事件时 `sendNotification`。

**Rationale**：调查确认四层全未装（当前仅 `shell` + `http` 插件）。`notification:default` 够发通知；遵循最小权限（Constitution III/CC-010）。发通知是桌面壳能力，业务规则（何时发）留在 Python 业务层，前端仅按事件触发（不把规则塞 Rust，CLAUDE.md）。

**Alternatives**：
- `notification:all`：超出需要，拒绝。
- 仅 Toast 不做桌面：设计稿 §10 要求双通道（app 未运行时虽不通知，但运行时桌面通知是核心价值）。
- **Windows 注意**：nsis 打包（`tauri.conf.json:27`）下 `identifier`（`com.mexamplar.desktop`）作 AUMID，须实测弹窗不落 Action Center（tasks 阶段验证项）。

---

## R6. 待办入口 UI 形态

**Decision**：待办条目上**行内动作按钮**（非右键菜单），复用 D12 创建确认卡。指令框预填 `title + description`、可编辑。

**Rationale**：项目既有交互以可见按钮为主（NavRail/TodoList 均显式按钮），右键菜单 discoverability 差、与既有风格不符。接入语义已由 D6/FR-015~017 定完，这只是交互细节。

**Alternatives**：
- 右键菜单：隐藏入口、家用场景不直观，拒绝。
- 长按 / 拖拽：移动端范式，桌面不适用。

---

## R7. per-task 免确认机制（不碰 `_auto_approve_enabled`）

**Decision**：新建 `src/business/scheduling/unattended_confirmation_manager.py`，**完全独立**于进程级 `_auto_approve_enabled`：
- 独立 `set[str]` 保存 per-task 授权 ID（从 SQLite `scheduled_tasks.unattended_auto_approve` 加载）。
- 在高危确认决策点 `_confirm_or_reject` **前**插一层判断：若当前 run 关联的 session 是 scheduled 且其 task 在授权集 → 放行（决策来源记既有确认审计日志）；若已权威确认是 scheduled 但未授权，或非空 session 无法权威识别，则按 D7 立即拒绝。普通用户会话与空上下文 passthrough，继续走既有进程级自动批准 / 交互确认路径。
- 判定「当前 run 是否 scheduled + 关联哪个 task」：经 session 的 `source='scheduled'` + `scheduled_task_id` 字段（v30 新增）。

**Rationale**：调查硬证据——`_auto_approve_enabled` 是进程级单一布尔，writer `(enabled, source)` 无 session 形参，reader `() -> bool`；开启即放行**所有**高危工具、波及**所有**会话。per-task 必须独立维度。仿 `clarification_manager.py` / `TrialPreviewRequestManager` 的「独立 manager」先例。

**Alternatives**：
- 复用 `_auto_approve_enabled` 加 session 维度：要改全局标志的读写签名 + 所有调用点，且仍难做 per-task 粒度，回归风险大。
- scheduled 会话完全禁高危：D7 已是默认（未授权即拒）；免确认是用户显式 opt-in 的受控开口，不能省。
- prompt 约束：不可靠（CT-1）。

**门卫**：guard test 断言开启 per-task 免确认不改变 `_auto_approve_enabled` 的值、不影响其他 session。

---

## R8. 完成判定订阅与 `all_terminal` 复用

**Decision**：
- 完成判定三条件用既有 API 自行组合成 `is_session_quiescent(session_id)`（无现成聚合函数，调查确认）：`not has_active_worker(session_id)` ∧ `not has_pending(session_id)`（`ParentReentrySink`）∧ 图全终态。
- 图终态：**抽取公共函数 `compute_graph_terminal_state(snapshot) -> (all_terminal, all_completed)`**（消除 `graph_scheduler.py:149-163` + `reentry_briefing.py:244-245` 的第三份复制），归属语义所有者 `task_collaboration/graph_terminal.py`，三处共用且 scheduling 只单向依赖。必须排除 root 容器（`parent_task_id is None`）。
- 终态映射：`all_terminal ∧ all_completed → succeeded`；`all_terminal ∧ not all_completed → failed`；
  主助理返回 `NEEDS_USER_INPUT` 时原子 `running→waiting_user` 并单次通知。
- 触发评估采用双路径：普通 / reentry worker 从 `AssistantRuntime` 注册表移除并完成
  tail-kick 后确定性调用；`graph_scheduler` 首次全终态时额外 emit 含 `session_id` 的内部
  `graph_scheduler_terminal`，既有子任务/root failure 活动也可提前重评。事件观察者失败
  不阻断父侧回流。

**Rationale**：调查确认「含失败/取消的图 root 永不收口 completed」（`graph_scheduler.py:176-178`），故**不可读 `root.status`**，必须读 `all_terminal`。三条件 API 全存在但分散，聚合是 033 增量。抽公共函数避免第四份复制（Constitution IV 可维护性）。

**Alternatives**：
- 只靠 reentry finally：简单无图任务没有 reentry，且图终态观察可能过晚，拒绝。
- 只靠 `graph_scheduler_terminal`：简单无图任务无事件，且图终态时主助理可能仍在汇报，
  拒绝。最终采用上述双路径，并让静默三条件统一消除早触发风险。
- 从 `workflow_transitions` 派生：违 CLAUDE.md（仅 debug breadcrumb），拒绝。

---

## R9. `source` 持久化 + scheduled advisory 单点派生

**Decision**：采用 Session 作为唯一来源事实，不给 runtime / orchestrator 追加
`unattended` 透传参数：
1. `Session` 加 `source`（user/scheduled，默认 user）+ `scheduled_task_id`（可空）+ `is_scheduled`（bool，Segment opt-out 用）—— v30 migration。
2. `ChatService.create_session(*, source="user", scheduled_task_id=None, session_id=None)`
   校验/保存来源并据此派生 `is_scheduled`；只有 `source=user` 的显式新聊天才重置进程级
   确认状态，后台 scheduled 会话不得干扰用户会话。
3. `AssistantPromptBuilder` 读取权威 session 的 `is_scheduled`，生成
   `{advisory_section}`；`dispatch_message` / `run_agent` 签名保持不变。
4. 聊天屏经 Repository 查询 `exclude_sources=["scheduled"]` 隔离；调度中心从
   scheduled task/run API 读取历史，不依赖 `assistant.*` UI event 携带 source。

**Rationale**：Agent B 调查的推荐路径。Session 加列是最小信息载体，下游全凭 `source` 派生行为（聊天屏排除、Segment opt-out、免确认范围、通知）。`build_pm_prompt(mode)` 是 per-invocation prompt variant 的干净先例。

**Alternatives**：
- dispatch_message 加 `extra_context` dict 透传：类型不安全、易漏字段。
- 复用 `{supplements_section}` 注入 advisory：section header 语义错误（「自优化补充规则」），误导，拒绝。

**分层处理**：`AssistantRuntime` 在 desktop_api 层，`SessionLauncher`（business）调它需跨层——见 plan CT-2（dispatch 回调由 desktop 层注入）。

---

## R10. 调度精度：周期扫描 vs 精准定时器

**Decision**：`SchedulerWorker` 双 Event 模式（仿 `BrainBackgroundWorker`）：`_stop_event.wait(timeout=min(scan_interval, max(0, soonest_next_fire_at - now)))`——扫描间隔配置默认 30s（bounded `[5, 600]`，走 `get_scheduler_scan_interval_seconds()`），但当最近一个 `next_fire_at` 早于下个扫描点时缩短 wait 到该时刻，实现「到点秒级触发」+「周期扫描兜底」。新建/更新任务 `next_fire_at` 提前时经 `notify_scheduler_worker()` 立即唤醒。

**Rationale**：纯周期扫描（如 task_collab 单 Event）精度受 scan_interval 限制；纯精准定时器要为每个任务挂定时器、随任务数膨胀。动态 wait timeout 兼顾精度与简洁，是 brain worker 的成熟模式。misfire/reentry 由 worker 兜底。

**Alternatives**：
- 每任务一个 `threading.Timer`：任务多时线程膨胀、取消管理复杂，拒绝。
- 纯 30s 扫描：周期任务最多迟 30s，体验差。

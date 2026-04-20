    ## Context

浏览器录制模式（Playwright 拉起 Chromium）当前只采集 DOM action 事件写入 `actions` 表，截图链路完全缺失。`analyze_image` agent 工具尝试从 `actions.screenshot_before/after` 读截图，但这两列是空的 `TEXT` 类型，从未写入过。

此外，`BrowserRecorder` 和 `RecordingRecovery` 对 queue 目录的路径拼接不一致：前者用 `get_default_data_dir() / "queues"`（受 `EXEMPLAR_DATA_DIR` 控制），后者硬编码 `project_root / "data" / "queues"`。默认环境碰巧一致，但设置环境变量后 Recovery 会找错位置。

现有技术栈已包含 pynput、mss、Pillow、psutil，无需引入新依赖。截图功能仅在 Windows 上启用。

## Goals / Non-Goals

**Goals:**
- 浏览器录制期间，对鼠标左键点击和回车键自动采集 before/after 截图
- 截图存入独立 `recording_screenshots` DuckDB 表，作为独立时序流
- `analyze_image` 按时间窗查询邻近截图，不依赖 action-screenshot 精确绑定
- 统一 queue 目录路径，修复 Recovery 路径 bug
- 截图 hook 失败时优雅降级，不影响录制主链路

**Non-Goals:**
- 桌面录制模式截图
- Extension-triggered 模式截图
- 录制回放 UI
- URL 过滤 / blocklist
- 修改浏览器扩展代码或 WebSocket 协议
- Recovery 对 screenshots 的重放恢复（仅做孤儿文件清理）
- `actions.screenshot_before/after` 列清理（保留，等未来 PR）
- viewport-only 截图（只做窗口级截图，含浏览器 chrome）

## Decisions

### 1. 方案选择：B6 Native Hook 并行

**选择**：Windows 原生输入钩子（pynput）+ mss 截屏 + HWND 裁剪浏览器窗口

**理由**：
- 不改浏览器扩展（`background_simple.js` / WebSocket 协议不动）
- before 截图时序好：mousedown/keydown 瞬间即触发（vs Playwright `page.screenshot` 消息到达已 fire）
- 无 QPS 限制（vs 扩展侧 `chrome.tabs.captureVisibleTab` 硬 2 QPS）
- 已有依赖（pynput、mss、Pillow），零新依赖

**替代方案**：
- B2 扩展侧截图：时序最好，但需改扩展 + base64 传输 + 隐私审查
- B4 Playwright 侧截图：不改扩展，但 before 时序差（消息到达已 fire）

### 2. 截图存储：独立时序表 vs actions 列

**选择**：独立 `recording_screenshots` 表，按 `timestamp` + `moment` 查询

**理由**：
- Native hook 看到物理输入，无法精确对应语义级 DOM action（如 `dblclick` / `submit`）
- 时间窗查询绕开了"给语义 action 精确绑图"的难题
- `source_trigger` 等操作类型字段只作旁路元数据，查询 WHERE 不依赖
- 新增 trigger 类型（如 `Ctrl+V`）时查询代码零修改

### 3. stop 顺序重排

**选择**：新增 `_wait_for_stop_drain` + `_last_browser_action_ts` 埋点

**理由**：
- 原顺序先 gate ingress 再发 stop 命令，最后一拍晚到的 action 会丢
- 新顺序：send_stop → drain（250ms 静默或 1s 上限）→ gate ingress → hook.stop → close browser → save
- `drain` 过程中 WS ingress 仍开启；超时不抛异常，降级继续

### 4. DPI awareness 设置位置

**选择**：应用入口 `QApplication` 构造前设置 Per-Monitor V2

**理由**：
- 进程级 DPI awareness 只能设置一次
- 放 `hook.start()` 里会中途改变进程状态，干扰 Qt UI
- Hook 只做读取式 DPI 检测，按当前进程级别选坐标策略

### 5. Recovery 不重放 screenshots

**选择**：screenshots queue 失败即丢，是 best-effort 数据

**理由**：
- 截图是增强数据，不是业务必需
- Recovery 保持 actions 恢复语义不变，降低复杂度
- 孤儿 screenshots queue 在下次启动时清理 + warn

### 6. Browser PID 解析策略

**选择**：psutil + 扩展 bundle path 匹配

**理由**：
- Playwright 没有暴露 `browser_pid()` API
- bundle path（`--load-extension=.../<launch_token>`）是唯一可靠主键
- 严格过滤 `--type=` 子进程，只认主 browser process
- 多候选或共享 persistent profile 时安全降级（返回 None，不采集截图）

### 7. Capture 队列背压策略

**选择**：`_ScreenCapturer` 使用自定义 `_CaptureTaskQueue`（基于 `deque` + `threading.Condition` 实现，而非标准库 `queue.Queue`），`maxsize=50`；满时优先丢弃最旧的 `moment=before` 任务（扫描后删除一条）再入队新任务，`moment=after` 任务保留；若队列里全是 after，则丢弃当前新任务并 log.warning。

**理由**:
- 无界队列在极端积压（1000+ 任务）时会让 `hook.stop()` flush 3s 超时丢大量 pending，且长会话吃内存
- `moment=after` 任务不能轻易丢：only after completion 才能让 `_AfterScheduler` 对应条目释放，丢 after 会导致调度器挂账
- 丢弃的 before 任务对 agent 查询影响有限，时间窗内通常还有邻近截图可命中
- 丢弃仅 log.warning 诊断，不入 screenshots queue 文件（不留痕）

### 8. 帧预采样架构

**选择**：帧采样逻辑作为 `_ScreenCapturer._run_sampler()` 方法实现（非独立 `_FrameSampler` 类），由内部 "FrameSampler" 后台线程运行；`_FrameRingBuffer` 环形缓冲（64 帧，约 6.4s @100ms），`_ScreenCapturer` 优先从缓冲区按时间戳取帧；帧数据用 `_FrameSample` dataclass 封装

**理由**：
- 按需截图方案中，pynput 回调 → 入队 → worker 取出 → mss grab 整个链路需要 10-30ms，before 截图的画面实际可能已经是 JS 处理后的状态
- 预采样将截屏与输入事件解耦：帧在事件发生前就已经采好，按时间戳匹配可得到真正的事件前画面
- 环形缓冲只保留最近 64 帧（~6.4s），内存占用可控（64 × 200-400KB ≈ 13-26MB）
- 缓冲区未命中时回退到实时截图，不丢失覆盖

**替代方案**：
- 按需截图（spec 原始方案）：实现更简单，但 before 时序精度依赖 worker 线程响应速度

### 9. save_to_duckdb 事务原子性

**选择**：actions INSERT 与 recording_screenshots INSERT 必须在**同一个 DuckDB 事务**里（`BEGIN ... COMMIT`）；任一阶段抛 DB 异常触发 `ROLLBACK`，两张表都不落、两个 queue 文件都保留。

**理由**:
- 避免"actions 成功 / screenshots 失败"的混合状态导致数据不一致
- `iter_screenshots_queue` 的行级容错（log.warning + skip）属于解析期行为，不触发事务失败，保证单行损坏不拖累整次入库
- 失败后 actions queue 由 `RecordingRecovery` 正常重放兜底；screenshots queue 成孤儿，由下次 startup scan 清理 + warn（与 §Decisions #5 一致）
- 只有 repository 层 INSERT 本身抛异常才算事务失败，语义清晰

## Risks / Trade-offs

- **[HWND 窗口裁剪精度]** → 优先使用 `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)` 获取窗口视觉边界（排除阴影等非客户区），回退到 `GetWindowRect`
- **[pynput hook 被 Windows 摘钩]** → 回调 <1ms 返回（只入队 CaptureTask），真正的 mss 截图在工作线程完成
- **[before 截图是近似 before]** → pynput 非阻塞钩子，截图可能在 JS 处理后 10-30ms 才完成；`WINDOW_BEFORE=1.0s` 覆盖此抖动
- **[快速连击导致 capture 队列积压]** → 时间窗仍能**命中**该 before 条目（`WINDOW_BEFORE=1.0s` 覆盖得住），但图的实际画面会偏离理想的 pre-state，agent 拿到的是**延迟版 before 图**——"命中"不代表"图内容语义正确"。叠加队列 `maxsize=50` 背压上限，最坏情况被限制在有限积压
- **[hook.stop() flush 超时]** → 默认 3s 后丢弃剩余任务并 warning，避免 stop 无限阻塞
- **[单行 JSONL 损坏]** → `iter_screenshots_queue` log.warning + 跳过继续下一行，不 fail-fast；截图为 best-effort，不应让单行损坏拖累 actions 事务
- **[DPI awareness 设置失败]** → fallback 链：Per-Monitor V2 → System Aware → Unaware；Hook 退回 `GetDpiForWindow` 手动校正
- **[非 Windows 平台]** → `hook.start()` 返回 False，warning 后降级，录制主路径不受影响
- **[同一 PID 多浏览器窗口]** → 只截当前前台候选窗口，非 Chromium 前台窗口 skip
- **[4K 密集会话磁盘占用]** → 单张 200-400KB，500 次点击约 200-400MB；用户可调低 `screenshot_quality`
- **[帧预采样内存占用]** → 环形缓冲 64 帧 × 200-400KB ≈ 13-26MB 常驻内存；100ms 采样间隔带来持续 CPU 开销（mss grab + JPEG encode），在低配机器上可能影响浏览器性能

## Follow-up Triggers

后续动作，不在本次实施范围，但定义触发条件以便未来优化时有明确依据：

- **[recording_screenshots 索引]** → 已在 `DuckDBManager.initialize()` 中创建 `idx_screenshots_recording_moment_time (recording_id, moment, timestamp)` 复合索引。原计划 MVP 不建索引，实测后提前加入以确保查询性能
- **[actions.screenshot_before/after 清理]** → 本次保留两列不动。**触发条件**：未来有独立迁移 PR 时一并处理 DROP COLUMN，避免本次全表 rewrite 成本
- **[WINDOW_BEFORE/AFTER 开放为配置]** → 当前工具层硬编码。**触发条件**：若有用户反馈时间窗默认值不合适，评估开放为 `recording.screenshot_window_*` 配置字段

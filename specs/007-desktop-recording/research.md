# Phase 0 Research: 桌面录制 Phase 1

> 本文件汇总技术决策。所有 spec 中标 NEEDS CLARIFICATION 的项目均已通过 8 轮 clarification 解决（见 `spec.md` Clarifications 段），本文件聚焦 Phase 1 实施所需的技术选型与库 API 行为锁定。

---

## R1: 全局键鼠 hook 库

- **Decision**: 使用 `pynput` 原生 keyboard / mouse hook（`pynput.keyboard.Listener` + `pynput.mouse.Listener`），二者均为非阻塞守护线程。
- **Rationale**:
  - 项目已将 pynput 列入预期依赖（spec FR-002 显式提及）；
  - 跨 keyboard / mouse 两套 hook 同进程内可独立 start/stop，与 ring buffer / UIA 异步队列协调容易；
  - hook 注册失败抛 `RuntimeError`，符合 spec FR-002 "**阻塞**录制启动并弹错对话框"语义；
  - typing/hotkey 归类（FR-002）由 hook 回调内部状态机做，不依赖额外 IME 组件；
  - 中文 IME 候选输入归 typing：pynput 在 Windows 下 IME 候选确认会触发 `KeyEvent.char` 非空，可由此判定。
- **Alternatives considered**:
  - `keyboard` + `mouse` 双库：API 简洁但 keyboard 库缺少明确 typing/hotkey 区分钩子，且需 admin（不可接受）。
  - Win32 `SetWindowsHookEx` 直驱：低层最稳但每条 hook 自行写消息循环，与 PyQt6 主事件循环耦合复杂，YAGNI。
  - `Pynput.HotKey`：仅适合静态全局快捷键，不适合捕获完整序列，pass。

---

## R2: UIA `ElementFromPoint` 同步查询

- **Decision**: 使用 `comtypes` 直接绑定 UIA COM，`IUIAutomation.ElementFromPoint(POINT)` + 50ms 软超时（外层 `concurrent.futures.ThreadPoolExecutor.submit` + `result(timeout=0.05)`），超时则记一个未填充行 + 排进异步队列稍后回填 `uia_summary`。
- **Rationale**:
  - 项目其他模块已经间接依赖 `pywinauto` → 自带 `comtypes`，不增加新二级依赖；
  - 50ms 软超时是 hook 回调容许延迟的上限（CC-007 鼠标延迟 < 50ms 软目标对齐）；
  - UIA COM 初始化失败（`CoInitializeEx` 返回错误）时 `comtypes.CoCreateInstance(CUIAutomation, ...)` 抛异常 → spec FR-003 降级路径（uia_summary 全空 + UI toast）；
  - `window_title` 通过返回 `IUIAutomationElement.GetCurrentParent()` 链式向上溯源到 owning window 取，与 `cursor_pos` 屏锁定一致（FR-003 + 与 FR-006 cursor 屏锁定语义对齐）；
  - **不**调用 `GetForegroundWindow()`：避免 cursor 屏 owning window 与系统全局 foreground window 分裂到不同屏（spec round 2 第 2 题）。
- **Alternatives considered**:
  - `pywinauto.Desktop().from_point(x, y)`：高层封装，但每次调用引入百毫秒级 walker 遍历，超 50ms 预算。
  - `IUIAutomation.ElementFromPointBuildCache`：性能更好但需自行设计缓存策略与失效，YAGNI Phase 1。
  - 改用 MSAA：MSAA 已 deprecated，Electron / 现代 UWP 应用控件树都走 UIA。

---

## R3: 多帧 PNG + mp4 clip 双 sink 编码

- **Decision**:
  - **截屏来源**：`mss`（开源跨屏截屏库，零安装压力，Windows 上走 GDI BitBlt + DXGI Desktop Duplication 后备），15 fps 主循环 timer 驱动。
  - **PNG 落盘**：`Pillow.Image.fromarray(rgb).save(path, "PNG", compress_level=6)`（FR-005 默认压缩级别）。
  - **mp4 clip**：`opencv-python` (`cv2.VideoWriter` + `mp4v` fourcc，自带 ffmpeg 静态编译，零外部依赖)，受 `recording.desktop.enable_clip` 开关控制；编码失败时 `desktop_actions.has_clip=FALSE`、`health_stats.clip_total++` 但 `clip_success` 不变（FR-005）。
  - **vision 上传前缩放**：`PIL.Image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)`——`thumbnail` 为单向不放大语义（仅当原长边 > 1280 才缩到 1280），与 spec round 8 第 2 题"仅缩小不放大"一致。
- **Rationale**:
  - `mss` 多屏支持完善，可按 `monitor_index` 切屏取帧（FR-006 cursor 屏锁定 + DPI awareness 后取 physical pixel）；
  - opencv-python 自带 ffmpeg 静态编译，installer 多 70MB（chromium 已 200MB+，spec assumption 已显式接受）；
  - PNG `compress_level=6` 是 Pillow 默认，平衡速度与体积，满足 CC-007 磁盘 IO 突发 < 50MB/s；
  - `Image.thumbnail` 默认 LANCZOS 重采样（高质量缩小），文字识别精度优于 BICUBIC。
- **Alternatives considered**:
  - PIL 直接截屏（`ImageGrab.grab()`）：单屏可用，多屏 + DPI awareness 适配麻烦。
  - `imageio-ffmpeg` 替 opencv：体积小，但需独立分发 ffmpeg 二进制，installer 流程复杂。
  - 单 sink 仅 PNG：spec FR-005 明确双 sink，clip 是 Phase 2 UI 播放器接通的前置数据。

---

## R4: 剪贴板订阅 + Ctrl+V 立即读

- **Decision**:
  - **订阅**：`win32api.SetClipboardViewer(hwnd)`（旧 API，跨 Windows 版本最稳）+ `WM_DRAWCLIPBOARD` 消息，或用更现代的 `AddClipboardFormatListener(hwnd)` + `WM_CLIPBOARDUPDATE`（Vista+，Phase 1 仅 Win10/11 满足）。优先后者。
  - **500ms 兜底**：QTimer 轮询 `OpenClipboard / GetClipboardSequenceNumber` 检测变更，避免 `WM_CLIPBOARDUPDATE` 偶发漏发（已知 Win10 RS5 早期版本边界 case）。
  - **Ctrl+V 立即读**：pynput 抓到 Ctrl+V 组合键 → 同步在 hook 回调内 `OpenClipboard / GetClipboardData(CF_UNICODETEXT|CF_BITMAP)` 立即取一次（兜底"用户粘贴时剪贴板内容已变 + WM 消息尚未到达"）。
  - **图片落盘**：`clipboard/<recording_id>_<event_seq>.png`，`event_seq` 在本次 recording 内自增整数（FR-004 + spec round 6 第 4 题）；Recorder 维护 `_ClipboardLatest` 最新引用。
- **Rationale**:
  - `AddClipboardFormatListener` + 500ms 轮询双轨保证 `clipboard_event_count` 不漏；
  - 图独立落盘 + `clipboard_image_path` 仅引用 hook 触发瞬间最新一张，保持 `desktop_actions` schema 简洁，同时 Phase 2 接通 UI 播放器时按 `event_seq` 时序回放（spec round 6 第 4 题）；
  - 订阅失败时降级启动 + UI toast（FR-004），与 FR-002 hook 阻塞不同——剪贴板不是录制根基。
- **Alternatives considered**:
  - 只用 `WM_CLIPBOARDUPDATE`：偶发漏发风险已知。
  - 只用轮询：CPU 浪费且 500ms 粒度对 Ctrl+V 立即读不够。
  - `pyperclip` 高层封装：仅提供 get_text，缺少图与监听。

---

## R5: Per-Monitor V2 DPI awareness

- **Decision**: 进程启动期（`src/main.py` 的 `get_unified_config()` 之前）调用 `ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)`（`-4` 即 `DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2`）。
- **Rationale**:
  - PyQt6 默认走 system-DPI 感知，多屏不同 DPI 时坐标系错位（FR-006 + spec round 2 第 4 题）；
  - V2 模式下 pynput / Win32 API / UIA `ElementFromPoint` 三者统一使用 physical pixel，零转换；
  - 必须在 PyQt6 `QGuiApplication` 创建之前调用，否则 Qt 已锁定 DPI 模式。
- **Alternatives considered**:
  - `SetProcessDpiAwareness(2)` (`PROCESS_PER_MONITOR_DPI_AWARE`)：旧 API，V2 是其超集；
  - manifest XML 声明：installer 流程复杂，YAGNI。

---

## R6: 全局热键 Ctrl+Alt+S

- **Decision**: `win32gui.RegisterHotKey(hwnd, id, MOD_CONTROL|MOD_ALT, ord('S'))` + 注册失败 `GetLastError()` 拿到 `ERROR_HOTKEY_ALREADY_REGISTERED` (1409) → 降级启动 + UI toast（FR-023）。
- **Rationale**:
  - `RegisterHotKey` 是 Windows 唯一稳健的全局快捷键 API（pynput 也无法跨进程优先级抢占）；
  - 失败不阻塞录制（FR-023），与 hook 注册失败语义不同——快捷键只是兜底入口，浮窗按钮仍可停止；
  - `WM_HOTKEY` 由专用隐藏 QWidget hwnd 接收，不污染主窗消息循环。
- **Alternatives considered**:
  - pynput 全局监听 Ctrl+Alt+S 组合：低优先级，被其他工具抢占时无 fallback 可观测。

---

## R7: Qt minimize 完成事件回调

- **Decision**: 在主窗 `QMainWindow.changeEvent(self, event)` 重写中检测 `event.type() == QEvent.WindowStateChange` 且 `self.windowState() & Qt.WindowState.WindowMinimized` 跃迁；该监听属于 UI 内部 eventFilter，跃迁触发后 UI 通过 `DesktopRecordingService` / business bridge 调用桌面录制启动流程，由业务层创建并启动 Recorder（hook + ring buffer + UIA 异步队列 + 剪贴板订阅）。
- **Rationale**:
  - 物理上消除"点开始"按钮 click 被 hook 抓为首动作的污染（spec round 7 第 3 题）；
  - Qt minimize 在 Windows 上通常 ≤ 100ms 完成，对用户感知无影响（spec FR-022 "立即启动"重定义为"用户视角连续，非物理时刻零延迟"）；
  - UI 内部可以用 eventFilter / Qt signal 表达 minimize 完成，但跨模块通知仍走 `src/utils/events.py` blinker；UI → 业务启动调用必须经 Service / Bridge，不直接实例化 Recorder。
- **Alternatives considered**:
  - 200-500ms `QTimer.singleShot` 短延迟：简单但与 minimize 完成时机非严格绑定，理论仍可漏抓。
  - 主窗内自行监听 → 直接调 Recorder：违反分层（UI 反向依赖业务）。

---

## R8: vision provider routing（沿用 `analyze_image`）

- **Decision**:
  - provider 维度沿用 `analyze_image` 当前 provider 配置（不新增 `recording.desktop.vision_provider` 字段）；
  - 仅 `recording.desktop.vision_model`（str，无默认）独立指定 vision-capable model；
  - keyring entry 沿用 `analyze_image` 同套（不分裂密钥）；
  - 未配置 `vision_model` → `analyze_desktop_action` 不注入桌面 PM/Programmer/Trial 工具集（自然降级，CC-005 一致）；
  - vision-capable provider 假设由用户自负（spec round 7 第 2 题：不引入启动期 provider 白名单校验，失败由 FR-013 现有 `[error: vision_failed]` 路径兜底）。
- **Rationale**:
  - "密钥统一"语义：provider 与 keyring entry 强绑定，分裂 provider 必然分裂 keyring；
  - Phase 1 用户场景假设"用户已配置 vision LLM 提供方"——即 `analyze_image` provider 本身就是支持 vision 的 provider；
  - 实施成本最低：复用 `analyze_image` provider routing factory；
  - 跨 provider 混搭（OpenAI 文本 + Anthropic vision）推迟到 Phase 2。
- **Alternatives considered**:
  - 新增 `vision_provider` 字段独立配置：违反"密钥统一"，跨 provider 混搭 YAGNI Phase 1。
  - model 字符串自带 prefix（`openai:gpt-4o`）：路由复杂、与 `analyze_image` 现行 model 字段格式不一致。

---

## R9: Trial 子进程隔离

- **Decision**:
  - **启动**：`subprocess.Popen([sys.executable, "-u", "-c", wrapper_code], stdin=PIPE, stdout=PIPE, stderr=PIPE, cwd=trial_dir, env=whitelisted_env, creationflags=CREATE_NEW_PROCESS_GROUP)`。
  - **wrapper**：模板字符串注入 Programmer 输出代码（已通过 `ast.parse` syntax gate）+ 末行 `print(json.dumps({"ok": ..., "summary": ..., "details": ...}))`；外层 `try/except Exception as e` 包装异常为 `{"ok": False, "summary": f"{type(e).__name__}: {e}", "details": {"traceback": traceback.format_exc()}}` 写 stdout 末行（FR-021a + spec round 4 第 5 题）。
  - **cwd**：`data/trials/<trial_id>/`，由 `desktop_trial_runner` 在试用启动前创建；business 层只编排 runner 调用与 blinker 事件，UI 不直接创建或写入 `data/trials/`；保留 7 天，超期由 `ensure_startup_recovery()` 扫描 mtime > 7 天 `rmtree` cleanup。
  - **env 白名单**：仅传 `{PATH, SYSTEMROOT, SYSTEMDRIVE, WINDIR, TEMP, TMP, PYTHONPATH, PYTHONHOME, LANG, LC_ALL, USERPROFILE, APPDATA, LOCALAPPDATA, PROGRAMFILES, "PROGRAMFILES(X86)"}`；含 `API_KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `KEYRING` 子串（大小写不敏感）变量必过滤（spec round 5 第 2 题）。
  - **120s kill**：`Popen.terminate()` 后 `subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=5)`，整树 kill 子孙进程（pywin32 / subprocess.run 等孙子进程）。
  - **stdout 末行 JSON 解析**：`desktop_trial_runner` 收集 stdout/stderr 后解析末行 JSON 并构造 `TrialResult`；解析失败时 runner 返回兜底结果，UI Toast 标题 "试用失败" + 正文 = stderr 末 5 行（截断到 ≤ 200 字符），完整 stdout/stderr 落 `data/trials/<trial_id>/{stdout.log, stderr.log}`（spec round 4 第 4 题）。
- **Rationale**:
  - `python -u` unbuffered，防止子进程崩溃时 stdout buffer 丢失末行 JSON；
  - `CREATE_NEW_PROCESS_GROUP` 让 `taskkill /F /T <pid>` 能整树 kill；
  - cwd 隔离 + env 白名单是 Phase 1 安全边界双轨（spec round 5 第 2 题 + round 6 第 2 题）；
  - stdout PIPE 由 execution runner 收集并解析，既避免 stdout 阻塞子进程（PIPE buffer 满），也避免 UI 承担子进程协议解析职责。
- **Alternatives considered**:
  - 临时 venv：依赖隔离更彻底但启动慢（数秒级），spec round 1 第 5 题显式拒绝。
  - Windows Job Object：能监控 RSS / CPU / 句柄，但 Phase 1 spec round 2 第 5 题显式拒绝。
  - 不限 env：spec round 5 第 2 题显式禁止——env 通道泄漏面在 Phase 1 即收紧。

---

## R10: 5 通用工具 mode dispatch + sqlglot security gate

- **Decision**:
  - `create_recording_tools(recording_id)` 工厂在构造时一次性查 `RecordingRepository.get_recording_mode(recording_id)`（浏览器录制从 `recording_sessions.recording_mode` 读取，桌面录制从 `desktop_recordings.recording_mode` 读取，两表均未命中返回 `recording_not_found`），闭包传给 5 个 handler（`describe_data` / `query_data` / `execute_code` / `read_recording` / `read_field_chunk`）+ `query_data_pre_hook`（FR-012）。
  - `describe_data` / `query_data` / `execute_code` 内部按闭包 `recording_mode` 切表：浏览器走现有 5 张表，桌面走 `desktop_recordings` / `desktop_actions`。
  - `query_data_pre_hook` 通过闭包拿到 `recording_mode`，调 `src/recording/filtering/sql_rewriter.py` 新增的 `validate_table_against_mode_allowlist(sql, mode)` 接口（依赖 sqlglot 列血缘分析），跨 mode 表访问 → 返回 `{"error": "table_not_in_mode", "table": "<name>", "mode": "<current_mode>"}`（FR-012a）。
  - **门卫不变量保留**：`recording_data_tools.py` 不直接 import sqlglot（CC-002 #5），所有 sqlglot 调用集中在 `src/recording/filtering/`。
- **Rationale**:
  - 闭包传递避免 hook contract 缺 mode 的漏洞（spec FR-012 显式提及）；
  - sqlglot 列血缘已在 `query_projection_analyzer.py` 用于浏览器 `network_requests` 过滤，本次仅扩展 allowlist 校验入口，保持 sqlglot 调用边界；
  - 浏览器路径 byte-equal 由 SC-005 门卫不变量 1-7 守住。
- **Alternatives considered**:
  - 工具 handler 内每次查 `recording_mode`：每次 DuckDB 查询，性能差且增加 mode 查询点。
  - 引入新 mode 维度参数到 ToolDefinition signature：破坏现有 5 工具 schema 兼容性（SC-005 浏览器 baseline byte-equal 不通过）。

---

## R11: Programmer 代码 `ast.parse` syntax gate + 自动反馈重试

- **Decision**:
  - 在 Orchestrator 拿到 Programmer 输出代码后、交给 Trial 子进程前执行 `ast.parse(code)`；
  - `SyntaxError` 时按 spec FR-017a 模板构造反馈消息（含 `lineno` / `msg` / 出错行 ± 2 行片段）→ 自动作为新一轮 user message 注入 Programmer Agent 的 conversation；
  - 重试上限 = 2 次（共最多 3 次 Programmer 出码尝试）；
  - 3 次连续失败 → UI Toast 标题 "Programmer 输出代码持续语法错误" + 正文 = 末次 `SyntaxError.msg` + `lineno`，全部 3 次代码 + 反馈消息 + 原始异常落进程日志；
  - 全程对用户透明（用户视角只感知"Programmer 思考中..."状态延长）。
- **Rationale**:
  - syntax gate 守住语法错不传到 Trial 子进程（避免 Trial wrapper 解析失败的间接报错路径，简化故障归因）；
  - 自动反馈重试与现有 PM/Programmer 自治闭环风格一致（不暴露内部 QC 给用户，spec round 5 第 1 题）；
  - 3 次上限避免无限循环。
- **Alternatives considered**:
  - 不做 syntax gate，直接交 Trial：Trial wrapper `try/except` 包装异常返回 `{"ok": False, "summary": "SyntaxError: ..."}` UI Toast 显示——用户视角易混淆"是 Trial 还是 Programmer 出错"；
  - 重试上限 = 1 次：Programmer 一次 LLM 输出受 temperature 影响有偶发性，重试 2 次的 P(成功) 显著高。

---

## R12: 桌面 PM/Programmer 双轨 prompt

- **Decision**:
  - 浏览器 mode 返回 `PM_SYSTEM_PROMPT_LEGACY` 全文字节级保留（FR-016 + CC-003 + SC-006）；
  - 桌面 mode 返回 `_PM_COMMON_HEADER + _PM_DESKTOP_GUIDANCE + _PM_COMMON_FOOTER` 三段拼接；
  - 三段中 `_PM_COMMON_HEADER` / `_PM_COMMON_FOOTER` 是新提取的桌面 prompt 通用骨架，**不**强制与 LEGACY 共享（避免双轨耦合到四轨）；
  - Orchestrator 启动 PM/Programmer 前 `dataclasses.replace(PM_CONFIG, prompt=build_pm_prompt(workflow.recording_mode))` 构造临时 AgentConfig 拷贝，`agent_loop.format_system_prompt()` 不改造。
- **Rationale**:
  - 字节级保留浏览器 prompt 是 SC-005 / SC-006 门卫前置；
  - 三段拼接桌面 prompt 让 `_PM_DESKTOP_GUIDANCE` 段独立可测（导航策略：先看头尾 → 按 window_title 聚焦 → 跳过冗余类型 → 关键节点用 `analyze_desktop_action`，FR-019）；
  - `dataclasses.replace` 是不可变拷贝，零状态泄漏。
- **Alternatives considered**:
  - 单轨 prompt 内动态判断 `recording_mode` 增加分支：违反 SC-005 浏览器 byte-equal。
  - 全局 LEGACY 改造为三段：破坏字节级保留契约。

---

## R13: Trial 桌面工具集对称（Trial = 浏览器 Trial 经 mode dispatch）

- **Decision**:
  - 桌面 Trial 工具集 = 浏览器 Trial 现行配置经 mode dispatch 后的对称等效；
  - 浏览器 Trial 若包含 `analyze_image`，桌面 Trial 等价替换为 3 桌面专属工具（`list_desktop_actions` / `analyze_desktop_action` / `read_action_clip`）；
  - 5 通用工具 mode dispatch 自动生效（Trial 与 PM 同走 `create_recording_tools(recording_id)` 工厂）；
  - 由 `create_desktop_specific_tools(recording_id)` 独立工厂提供 3 桌面专属工具，由 Orchestrator 拼接到桌面 PM **以及** Trial 工具集（FR-015）。
- **Rationale**:
  - PM / Programmer / Trial 三者工具集对称，避免 Programmer 依赖某工具但 Trial 拿不到；
  - 桌面 Trial 在执行试用代码时仍能调 `list_desktop_actions` / `analyze_desktop_action` 验证其他动作（虽然 Trial 主要执行 Programmer 出的代码，但 spec FR-015 显式要求对称）。
- **Alternatives considered**:
  - Trial 仅给 5 通用工具不给 3 桌面专属：破坏对称，spec FR-015 显式拒绝。

---

## R14: `health_stats` JSON 写入时机

- **Decision**:
  - Recorder 内部维护 in-memory counter（`uia_hit` / `uia_total` / `clip_success` / `clip_total` / `clipboard_event_count` / `action_type_counts: dict[str, int]`）；
  - 录制停止时一次性把汇总以 JSON 写入 `desktop_recordings.health_stats` 列（spec round 1 第 1 题 + FR-007）；
  - sanity check 对话框直接读该列（FR-024），不扫 `desktop_actions` 表；
  - `uia_total` / `uia_hit` 仅累加鼠标类动作（mouse_left / mouse_right / mouse_middle / wheel / drag），typing / hotkey 不计入分母（spec round 2 第 1 题 + FR-003）。
- **Rationale**:
  - in-memory 累加避免每次 hook 触发都 UPDATE `desktop_recordings`（高频写）；
  - 停止时一次写入是事务边界（健康反馈不需要录制中实时刷新）；
  - sanity check 读单行 JSON 即可，避免聚合扫表带来的 UI 阻塞。
- **Alternatives considered**:
  - 每 hook UPDATE：高频写损耗。
  - 录制完成后聚合扫 `desktop_actions`：sanity check 弹出延迟，且 `clip_success` / `clipboard_event_count` 等不在 actions 表，仍需 in-memory counter。

---

## R15: monitor_index per action

- **Decision**: 每条 `desktop_actions` 行加 `monitor_index INTEGER` 列，记录 hook 触发瞬间 cursor 所在屏 index；session 级 `desktop_recordings.monitor_index` 仍保留作"录制启动时主屏"参考（spec round 7 第 1 题 + FR-008）；drag 取 mouse_up 终点屏（与 frame 取自 up 屏一致）。
- **Rationale**:
  - 跨屏录制下单条动作可独立溯源；
  - Phase 2 接通 UI 播放器时按 `desktop_actions.monitor_index` 回放无需回查 cursor 屏；
  - 增量成本极低（1 列 INTEGER）。
- **Alternatives considered**:
  - 不加列仅 session 级：跨屏录制下行无屏溯源能力，spec round 7 第 1 题显式拒绝。

---

## R16: 多模态消息组装顺序

- **Decision**: `analyze_desktop_action` 内部按以下顺序组装多模态消息（FR-013）：
  1. 对每个 `action_id` 按 `timestamp` 升序串接帧序列；
  2. 对 typing 类型 action（`type=typing`）在该 action 帧序列**之前**插入前缀文字 `Action <id> 用户输入文本: <text_content>`（已 large_field 占位时按占位形态原样插入）；
  3. 该 action 若有剪贴板图（`clipboard_image_path` 非空），剪贴板图紧接帧序列**之前**插入，前缀文字 `Action <id> 剪贴板图（动作 hook 触发瞬间最新一张）`；
  4. typing 文本前缀与剪贴板图前缀同时存在时排序为"typing 文本前缀 → 剪贴板图前缀 → 帧序列"（输入文本是动作核心、剪贴板图是输入背景）；
  5. 每张帧前插入文字说明 `Action <id> 帧 N/M (T={t}ms 相对动作开始)`；
  6. 多个 `action_ids` 间用文字 `--- Action <prev_id> 帧序列结束 / Action <next_id> 开始 ---` 显式分隔；
  7. 用户传入的 `question` 参数放在所有图与说明文字之后作为最终 prompt。
- **Rationale**:
  - typing 文本前缀让 vision LLM 直接知道用户输入了什么文本，无需从画面推断（IME / 非英文字符画面识别困难场景，spec round 8 第 1 题）；
  - 剪贴板图前置作为"动作的输入背景"符合自然逻辑；
  - 显式分隔避免 LLM 混淆多 action 帧。
- **Alternatives considered**:
  - text_content 不进 prompt：vision 仅从画面推断输入，IME 场景误读率高。
  - 全部 text 元数据进末尾 / 散落帧间：vision LLM 会被淹没。

---

## R17: 5 标准场景 manual e2e 漏斗判定

- **Decision**: 5 场景固化最小任务骨架到 `quickstart.md` + spec SC-001 已含；执行流程：用户按场景骨架完成录制 → sanity check 颜色非红 → 进 intent 页让 PM 出方案 → Programmer 出码 `ast.parse` 通过 → Trial 子进程退出 + 末行 JSON `ok=True` → 检查代码捷径命中（按 SC-004 机械规则 + 人工 spot check）。
- **Rationale**:
  - 5 场景 manual e2e 是 Phase 1 唯一退出标准（spec round 2 第 4 题：SC-002 整体作为 manual e2e 漏斗判定记录，不进自动化端到端测试）；
  - 漏斗 = 5/5 录制成功（SC-001）→ 5/5 出方案（SC-002）→ ≥ 3/5 试用通过（SC-003）+ ≥ 3/5 走捷径（SC-004）。
- **Alternatives considered**:
  - 自动化 e2e：对 LLM 输出 + 真实桌面 UI 自动化测试不稳定，YAGNI Phase 1。

---

## R18: Phase 1 不引入崩溃恢复 / retention / quota

- **Decision**:
  - 录制中崩溃 → 不打 `status='crashed'` tag、不清理目录 / DB 行；`ensure_startup_recovery()` 不扫描 desktop 表（FR-027 + Edge Case "录制中崩溃"）；
  - 用户主动放弃路径走软删除（`status='abandoned'`，DB 行 + 目录保留待用户手动 `rm -rf`）；
  - vision LLM 调用累计无 quota（FR-013 + spec round 2 第 3 题），仅 INFO 日志事后审计；
  - Trial 子进程不监控 RSS / CPU / 句柄（spec round 2 第 5 题），仅靠 120s + taskkill；
  - 录制规模无硬上限（CC-008），仅靠 CC-007 软目标 + sanity check 反馈 + 用户主动停止。
- **Rationale**:
  - Phase 1 用户 = 开发/内测，孤儿与超量都由用户现场判断手动处理；
  - YAGNI：Phase 2 视实际事故率再决定是否引入。

---

## 总结

| Decision Group | Resolved | Rationale Source |
|----------------|----------|------------------|
| 库与 API 选型 | R1-R7 (pynput / UIA / mss / opencv-python / clipboard / DPI / minimize 回调) | spec FR-002~006, FR-022 |
| Provider 与 routing | R8 (vision provider 沿用 analyze_image) | spec round 7 第 2 题 |
| 子进程隔离 | R9 (Trial subprocess + cwd + env 白名单 + 120s taskkill) | spec FR-021a + round 5 第 2 题 + round 6 第 2 题 |
| 工具与编排 | R10-R13 (mode dispatch + sqlglot gate + syntax gate + 双轨 prompt + Trial 对称) | spec FR-011~020 |
| 数据契约 | R14-R16 (health_stats / monitor_index / 多模态组装) | spec FR-007, FR-008, FR-013 + round 7 第 1 题 + round 8 第 1 题 |
| 验收路径 | R17 (5 场景 manual e2e 漏斗) | spec SC-001~004, SC-007 |
| Phase 1 边界 | R18 (无崩溃恢复 / retention / quota) | spec FR-027 + round 2 第 3-5 题 |

所有 NEEDS CLARIFICATION 通过 spec 8 轮 clarification 解决；本研究文档无遗留待澄清项。

# Feature Specification: 桌面录制 Phase 1

**Feature Branch**: `007-desktop-recording`
**Created**: 2026-05-01
**Status**: Completed
**Input**: User description: "desktop-recording — 桌面录制 Phase 1：UIA + pynput hook + 多帧截图 + clip 编码 + 剪贴板 + 5 通用工具 mode dispatch + 3 桌面专属多模态工具 + PM/Programmer prompt 双轨"
**Source**: 决策来源 `docs/local/_archive/design-drafts/2026-04-29-desktop-recording-brainstorm.md`（§9.10 最终 Phase 1 范围 + §9.12 / §9.14 / §9.15 修订）

## Clarifications

### Session 2026-05-01

- Q: `analyze_desktop_action` 调用时（向外部 vision LLM 上传帧+剪贴板图）UI 是否需要任何运行期确认？ → A: 不引入任何运行期确认，全部依赖 CC-004 + SC-008 静态合规签字（vision 未配置→工具不注入即天然降级）
- Q: 录制中崩溃后已采集的 `desktop_recordings` 孤儿行 / 目录如何处理？ → A: Phase 1 完全不处理（Phase 1 无录制历史列表 UI，孤儿行无路径被用户/Agent 触达；三模式互斥基于 in-memory active recorder state，不查 DB，因此孤儿行不阻塞下次录制；崩溃恢复整体推迟到 Phase 2）
- Q: 单次录制是否设时长 / 动作数 / 磁盘硬上限？ → A: 不设任何硬上限，仅靠 CC-007 软目标 + sanity check + 用户自律（Phase 1 用户是开发/内测，5 个标准场景均为分钟级；硬限制策略推迟到 Phase 2）
- Q: sanity check 红/黄/绿健康判定的具体阈值？ → A: 给关键阈值——动作总数=0→红 / UIA 命中率<50%→黄 / clip 失败率>20%→黄 / 其余指标（帧总数 / 录制时长 / 剪贴板事件）只展示数值不上色
- Q: SC-004 "走捷径"如何客观判定？ → A: 给客观规则——生成代码任一命中即算捷径：调用 `subprocess` / `os.startfile` / `webbrowser` / Win32 协议 URL（如 `wechat:`） / `pywin32` 高级 API / `pywinauto` 控件级 API；纯 `pyautogui` 坐标点击循环不算；Win32 协议 URL 检测排除 Windows 盘符路径（如 `C:\foo`），`pywin32` 命中集合限定为 `win32api` / `win32gui` / `win32com` / `win32process` / `win32service` / `win32clipboard` / `pythoncom` 等高级 API 模块；人工 review 仅做 spot check 复核

### Session 2026-05-01 (round 2)

- Q: sanity check 健康指标（UIA 命中率 / clip 失败率 / 各类型分布等）从哪里取数、何时持久化？ → A: Recorder 内部维护 in-memory counter（uia_hit / uia_total / clip_success / clip_total / clipboard_event_count / 各 action_type 计数），录制停止时一次性把汇总以 JSON 写入 `desktop_recordings.health_stats` 列；UI sanity check dialog 通过 `DesktopRecordingService.get_health_stats(recording_id)` 间接读该列，不扫 `desktop_actions` 表、不直连 Repository
- Q: `desktop_recordings.status` 字段取值与"放弃录制"语义？ → A: `status` 取值 `recording / stopped / abandoned`，"放弃录制"走软删除（UPDATE status='abandoned'，DB 行 + 目录都保留），用户事后手动 `rm -rf data/recordings/<recording_id>/` + DELETE DB 行
- Q: 桌面 Trial Agent 工具集？ → A: 沿用浏览器 Trial 现行配置经 mode dispatch 后的对称等效——浏览器 Trial 拿到的 5 通用工具（按 mode 切表）桌面 Trial 同样拿到；浏览器 Trial 若拿到 `analyze_image` 则桌面 Trial 不注入 `analyze_image`、改为注入 3 桌面专属工具（`list_desktop_actions` / `analyze_desktop_action` / `read_action_clip`），保持 PM / Programmer / Trial 三者工具集对称
- Q: `recording_id` / `action_id` 标识符生成规则？ → A: 与现有 `recording_sessions.recording_id` / `actions.action_id` 完全沿用同格式（VARCHAR + 主仓现行 UUID 规则），桌面表新行的 ID 通过同一个生成函数；目录约定 `data/recordings/<recording_id>/` 浏览器 / 桌面共用根
- Q: 试用代码的进程隔离方式？ → A: `subprocess.Popen + python -u -c <code>` 启动子进程，stdout/stderr 走 PIPE 收集；120s 超时用 `Popen.terminate()` + Windows `taskkill /F /T <pid>` 兜底，保证 Programmer 代码 spawn 的孙子进程（如 `subprocess.run(["code", file])`）一并整树 kill；依赖直接继承父进程 site-packages，不引入临时 venv

### Session 2026-05-01 (round 3)

- Q: Programmer 生成的 `async def execute(...)` 函数签名 / 入参 / 返回值 / 调用入口契约？ → A: 强约束 `async def execute() -> dict` 无参；返回 `{"ok": bool, "summary": str, "details": dict | None}`；Trial 子进程 wrapper 自动包 `asyncio.run(execute())` 并把返回值序列化为 JSON 写到 stdout 末行；recording_id / PM intent 由 Programmer 在代码内部硬编码（来自 prompt 上下文），不通过子进程边界传参
- Q: `analyze_desktop_action` 返回给 Agent 主上下文的文本结构？ → A: 纯字符串，按 action_id 分段（"Action `<id1>`：<text>\n\nAction `<id2>`：<text>"，≤2 段对应 ≤2 个 action_ids）；不带 provider/model 元数据；超过 `recording.large_field.threshold_chars` 自动 large_field 占位
- Q: clip 编码失败时的降级行为？ → A: PNG 多帧仍正常生成；`desktop_actions.has_clip=FALSE`，clip 文件不落盘；`health_stats.clip_total++` 但 `clip_success` 不变（"clip 失败率 > 20% → 黄"分母 = clip_total）；`read_action_clip(action_id)` 在 `has_clip=FALSE` 时返回标准化错误对象 `{"error": "clip_unavailable", "action_id": "<id>"}`
- Q: `typing` 序列在 `desktop_actions` 行的存储粒度？ → A: 一段切片 = 一行 `desktop_actions`，type=`typing`；新增 `text_content` 文本列存整段输入，超过 `recording.large_field.threshold_chars` 自动 large_field 占位（与 `clipboard_text` 同套）；`coord_x` / `coord_y` 取序列起点 cursor_pos，`timestamp` 取序列起点；序列时长落独立 `duration_ms` 列

### Session 2026-05-01 (round 4)

- Q: `analyze_desktop_action` 失败时（vision LLM 超时 / 401 / 部分 action 分析失败）的返回形态？ → A: 全程保持"按 action_id 分段字符串"格式（与 FR-013 一致），失败段写为 `"Action <id>：[error: <reason_code>]"` 与成功段拼接为同一字符串返回；不引入 dict 错误对象、不抛异常；reason_code 至少覆盖 `vision_timeout` / `vision_unauthorized` / `vision_failed`（兜底）；上层 Agent 通过文本中的 `[error: ...]` 片段识别失败段并自行决定退避
- Q: 5 个标准场景的"录制成功 / Agent 给方案 / 试用通过"判定如何固化？ → A: 每个场景固化最小任务描述（写入 spec §Success Criteria 与 quickstart），"录制成功"客观判定 = `health_stats.action_type_counts` 之和 > 0；US4 完成后该状态在 sanity check UI 上表现为颜色非红；动作数与类型不强制，保留人工执行灵活性
- Q: 桌面录制启动时核心子系统（pynput hook / UIA / 剪贴板订阅）任一初始化失败的策略？ → A: 分级处理——pynput keyboard/mouse hook 注册失败 = 阻塞启动并弹错对话框（hook 是录制根基，无 hook 无意义）；UIA COM 初始化失败 / 剪贴板 WM_CLIPBOARDUPDATE 订阅失败 = 降级启动 + UI 一次性 toast 提示降级范围（uia_summary 全空 / 剪贴板事件全空），录制照常开始，sanity check 后续会反映；与 FR-023 (Ctrl+Alt+S 注册失败=降级+toast) 同模式
- Q: vision LLM provider/model 与现有 `analyze_image` 的配置关系？ → A: 密钥统一 + model 独立——provider key 仍走 keyring 沿用 `analyze_image` 同套（不分裂密钥）；新增 `recording.desktop.vision_model` 配置字段独立指定 vision-capable model（避免误用纯文本 model 导致功能哑火）；未配置 `vision_model` 时工厂层不注入 `analyze_desktop_action`（与 CC-005 自然降级路径一致）
- Q: 桌面试用"跑完通知"的 UX 形态？ → A: 复用现有普通 Toast（右下角浮层、非模态、自动消失约 5s、不抢焦点），与"跑期间无遮挡 + 不弹任何模态遮挡焦点"精神一致；通知标题 = "试用成功" / "试用失败"（按 `ok` 字段），通知正文 = stdout 末行 JSON 中的 `summary` 字段；不复用 `AuthToastSurface`（那是高危确认浮层，受 FIFO 队列约束）；不进入对话历史；不接入 Windows 系统原生通知中心

### Session 2026-05-02

- Q: `read_recording` 工具在桌面 mode 的处理？（原 spec FR-011 曾漏列 `read_recording`，与 CLAUDE.md 声明的"5 工具模型"不一致） → A: 加入 mode dispatch——桌面 mode 下 `read_recording(recording_id)` 返回 `desktop_recordings` 行 + 关联 `desktop_actions` 摘要，与浏览器输出结构同形（同一组工具、同一 schema、内部按 mode 切表）；FR-011 / CC-002 / SC-005 / Edge Case "浏览器路径回归" / Architecture Impact 中所有通用工具数量表述全部修正为 "5 通用工具"；read_field_chunk stable locator 与 read_recording 入口对齐桌面侧扩展
- Q: SC-002 "可执行方案"的客观判定标准？ → A: 中等判定——PM Agent 完成 intent 输出 + Programmer Agent 输出 `async def execute() -> dict` 代码且代码本身能通过 `ast.parse` 语法解析（不要求实际运行成功，运行成功由 SC-003 单独度量）；与 SC-003 (3/5 试用通过) 形成"5/5 出方案 → 3/5 跑通"漏斗
- Q: `hotkey` 与 `typing` 类型的客观区分边界？ → A: 修饰键归类——按键事件含 Ctrl / Alt / Win（不含 Shift） = `hotkey` 单事件；Shift+letter / 纯字符键累积为 `typing` 序列（Shift 视为输入修饰，决定大小写/符号，不改变"用户在打字"语义）；功能键单按（F1-F12 / Esc / Enter / Tab / 方向键）= `hotkey` 单事件；中文 IME 候选输入仍归 `typing`
- Q: 试用前"事前提示对话框"的内容与按钮设计？ → A: 中等版——文案"试用代码即将在桌面真实执行（最长 120s）" + 代码前约 20 行预览（可滚动） + 检测到的高危 API 列表（按 SC-004 同套规则机械检测：subprocess / os.startfile / webbrowser / Win32 协议 URL / pywin32 高级 API / pywinauto 控件级 API 命中即标签化）+ "开始 / 取消"双按钮；用户点"取消"放弃试用，回到 intent 页
- Q: PNG 帧分辨率与编码策略？ → A: 双链路分离——录制时按原生屏幕分辨率截屏落盘（PNG 默认压缩 compress_level=6），保留 Phase 2 接通 UI 播放器的可能性；`analyze_desktop_action` 上传 vision LLM 前在工具内部自动缩放到长边 1280px（保识别精度同时控 token 成本与上传带宽），落盘文件本身不缩放

### Session 2026-05-02 (round 2)

- Q: `health_stats.uia_total` 健康指标分母语义？(直接影响 FR-024 "UIA 命中率 < 50% → 黄" 判定) → A: `uia_total` / `uia_hit` 仅累加鼠标类动作（mouse_left / mouse_right / mouse_middle / wheel / drag），typing / hotkey 不触发 UIA 查询且不计入分母；纯键盘场景下 `uia_total = 0` 时，UIA 命中率轴不参与颜色判定（避免假性变黄），仅 clip 失败率 / 动作总数轴生效
- Q: 当鼠标光标在屏 A、但系统 foreground window 在屏 B 时，`window_title` / `uia_summary` 取哪侧？ → A: 与 FR-006 cursor 屏锁定语义对齐——从 `ElementFromPoint(cursor_pos)` 返回控件向上溯源到 owning window 取 `window_title`，`uia_summary` 也按同一控件树展开；不调 `GetForegroundWindow()`，避免控件信息与点击坐标分裂到不同屏
- Q: `analyze_desktop_action` vision LLM 调用累计上限 / 成本控制策略？ → A: Phase 1 不设硬上限（不引入 quota / rate limit / UI 阻断 Toast），Phase 1 用户 = 开发/内测、token 自负；每次调用后**记录 INFO 日志**（recording_id / action_ids / 本次帧数 / 当前会话累计调用次数与累计帧数）便于事后审计；Phase 2 视审计数据再决定是否引入 quota
- Q: SC-002 "PM 完成 talk_to_user 终态 + Programmer 代码 `ast.parse` 通过"两条客观判定的执行形态？ → A: SC-002 整体作为 5 场景 manual e2e 漏斗判定（与 SC-001 / SC-003 / SC-004 / SC-007 同形），不进自动化端到端测试；其中 `ast.parse` 校验落到 Orchestrator 在 Programmer 输出代码后、交给 Trial 子进程前的 syntax gate（守住语法错不传到 Trial），并由独立单元测试覆盖（fixture：合法代码通过 / 故意语法错被拦截）
- Q: 试用子进程除 120s 时长上限外，是否监控/限制内存与 CPU 占用？ → A: Phase 1 不监控、不限制——只靠 120s 时长 + `Popen.terminate()` + `taskkill /F /T <pid>` 整树 kill 兜底；不引入 Windows Job Object / RSS 监控 / CPU 配额；Phase 1 用户 = 开发/内测在本机现场可观察并手动停，OS page file 兜底防止立即崩；Phase 2 视实际事故率再决定是否引入 Job Object

### Session 2026-05-02 (round 3)

- Q: drag 类型的 `coord_x` / `coord_y` / `timestamp` 落库取起点 (mouse_down) 还是终点 (mouse_up)？ → A: 取 **mouse_up 终点**——`coord_x` / `coord_y` 用 up 时刻坐标，`timestamp` 用 up 时刻；`duration_ms` 记 down→up 时长（与 typing `duration_ms` 共用列）；UIA `ElementFromPoint(up_x, up_y)` 查 up 点控件（"用户拖到了哪"），与 Edge Case "拖拽 up 触发画面（看放下后状态）" 语义一致
- Q: `read_recording(recording_id)` 在桌面 mode 返回的"`desktop_actions` 摘要"具体形态？ → A: 聚合摘要——`desktop_recordings` 行（含 health_stats）+ 动作总数 + 按 `type` 分组计数 + 按 `window_title` 分组计数（前 5 个） + 时间范围 [first_ts, last_ts] + 首尾节点原始行（前 5 + 后 5 共 ≤10 行）；不返回中段原始动作（Agent 用 `list_desktop_actions` 翻页取深，避免首调 token 压爆）
- Q: 桌面 mode 下 `describe_data` / `query_data` 的 allowlist 表清单与跨表 JOIN 策略？ → A: allowlist = `{desktop_recordings, desktop_actions}`，**完全屏蔽**浏览器 5 张表（`recording_sessions` / `actions` / `network_requests` / `sibling_snapshots` / `recording_screenshots`）；允许两张桌面表跨表 JOIN；触及浏览器表 sqlglot security gate 拒绝并返回 `{"error": "table_not_in_mode", "table": "<name>", "mode": "desktop"}`；浏览器 mode 反向同理（屏蔽桌面 2 张表）
- Q: 多屏不同 DPI scale（如屏 A 100% + 屏 B 150%）时坐标语义如何对齐？ → A: 进程启动期显式声明 **Per-Monitor V2 DPI awareness**（`SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)`）；pynput / Win32 API / UIA `ElementFromPoint` 全部用 **physical pixel**，三者对齐零转换；`desktop_actions.coord_x` / `coord_y` 落库即 physical pixel；不做 logical/physical 转换、不引入额外 schema 列
- Q: Trial 子进程 wrapper 遇到 `ImportError` / 其它运行时异常如何处理？ → A: wrapper 在最外层 `try/except Exception as e` 兜底，把任意异常（含 ImportError / 业务异常 / asyncio 异常）包成 `{"ok": False, "summary": f"{type(e).__name__}: {e}", "details": {"traceback": "<完整 traceback 字符串>"}}` 写 stdout 末行，与正常返回同通道；UI Toast 直接显示 `summary` 字段（异常类型 + 消息）；不依赖 stderr 与退出码做异常分类

### Session 2026-05-02 (round 4)

- Q: Frame ring buffer 在录制启动 < 1 秒就触发首动作时（buffer 不足 15 帧），如何取帧？ → A: 取 buffer 里**所有可用帧**（不足 15 帧也写，不丢首动作）+ 后 2 秒约 30 帧；首动作完整捕获，`frame_count` 字段如实记录实际帧数（可能 < 45）；不等齐 1 秒、不复制填充——保证 5 标准场景"切窗口/打开应用"等首动作不被遮蔽
- Q: Trial 子进程 stdout 完全没有有效末行 JSON 时（如 spawn 失败、进程立即崩、只有 stderr 输出）的 UI Toast 兜底？ → A: 标题 "试用失败"（与正常异常路径标题一致避免混淆），正文 = stderr **末 5 行**（截断到 ≤ 200 字符）显示给用户做快速诊断；完整 stdout / stderr 同时落进程日志文件供事后追溯；超时路径继续用独立标题 "试用超时"（不混入此兜底）
- Q: 录制点"开始"→ 实际开始抓动作之间是否引入倒计时（让用户切到目标窗口）？ → A: **不引入倒计时**——点"开始"立即启动 pynput hook + ring buffer，hook 立即抓首动作（与"学习捷径"训练目标对齐：首动作通常就是切窗口/打开应用，恰是录制学习重点）；同时 Exemplar 主窗 MUST 自动 minimize 到任务栏（浮窗保留），给用户让出工作区，用户从任务栏 minimize 的瞬间切到目标应用；UX 增益但不影响首动作捕获
- Q: `list_desktop_actions` 的 `action_types` 参数取值规范？ → A: 类型 `list[str] | None`，元素从枚举集 `{"mouse_left", "mouse_right", "mouse_middle", "wheel", "drag", "typing", "hotkey"}` 取，大小写敏感、与 `desktop_actions.type` 列值完全一致；`None` 或省略 = 不过滤（返回所有类型）；元素含枚举集外字符串时工具 MUST 返回 `{"error": "invalid_action_type", "value": "<x>"}` 而非静默忽略（避免 Agent 拼错被悄悄漏数据）
- Q: `desktop_recordings` / `desktop_actions` 是否引入 `schema_version` 列防 Phase 2 加列破坏旧数据？ → A: **不引入**——Phase 1 是开发/内测阶段，孤儿录制本就由用户手动清理（FR-027），Phase 2 加列时旧数据视为 obsolete 由用户清理而非强行兼容；DuckDB `ALTER TABLE ADD COLUMN` 默认 NULL 满足渐进加列；走 YAGNI 路线，Phase 2 真正需要 schema 演进时再引入数据库 migration 工具，不在 Phase 1 提前加 DDL 复杂度

### Session 2026-05-02 (round 5)

- Q: Programmer 输出代码 `ast.parse` syntax gate 拒绝后的下游处理路径？ → A: Orchestrator MUST 在拦截到语法错误后**自动反馈给 Programmer Agent 重新生成**，最多重试 2 次（共最多 3 次 Programmer 出码尝试），全程对用户透明（用户视角看到的是延长的"Programmer 思考中..."状态）；3 次连续失败才上报终态失败，UI Toast 标题"Programmer 输出代码持续语法错误"+ 正文 = 末次 `ast.parse` 异常的 `msg` + `lineno`，并把代码与错误同时落进程日志供事后追溯；与现有 PM/Programmer 自治闭环风格一致，避免把工具内部 QC 暴露给用户
- Q: 试用子进程的环境变量继承策略？（敏感信息隔离边界） → A: **白名单继承**——子进程 MUST 仅继承运行 Python 必需的 env vars 白名单 `{PATH, SYSTEMROOT, SYSTEMDRIVE, WINDIR, TEMP, TMP, PYTHONPATH, PYTHONHOME, LANG, LC_ALL, USERPROFILE, APPDATA, LOCALAPPDATA, PROGRAMFILES, "PROGRAMFILES(X86)"}`；其余一律不传入，特别是任何含 `API_KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `KEYRING` 子串（大小写不敏感）的变量 MUST 被过滤；理由：Programmer 代码源自 LLM 输出且可自由调用 `subprocess` / `os.environ`，env var 泄漏面在 Phase 1 即应收紧，与 CC-005"按需上传"精神一致；keyring secret 仍可被需要它的子进程代码主动读取（keyring 后端走 OS 层凭据库而非 env），但默认不通过 env 通道暴露
- Q: 录制结束后 Exemplar 主窗是否自动 restore？sanity check 对话框与主窗的层级关系？ → A: 录制停止瞬间（浮窗"停止"按钮或 Ctrl+Alt+S 触发后）UI MUST **自动 restore 主窗**到点"开始"前的位置/大小（`QWidget.showNormal()` + 几何恢复），sanity check 对话框作为 **modal child** 弹在主窗之上；从录制态到反馈态视觉过渡连续，与 FR-024"立即弹 sanity check"的"立即"语义一致——若主窗未 restore，对话框被遮蔽即"反馈不可见"，违背契约。点"开始"前 UI MUST 记录主窗的 geometry / window state，停止时按记录还原
- Q: 一个 action 期内多次剪贴板事件（如多次 Ctrl+C 复制不同图片）的关联落盘策略？`desktop_actions.clipboard_image_path` 只能存单路径。 → A: **剪贴板事件独立于 action 行落盘**——每次剪贴板变更产生的图按 `clipboard/<recording_id>_<event_seq>.png` 命名（`event_seq` recording 内自增整数）落盘；Recorder 内部维护 `_ClipboardLatest` 最新引用；`desktop_actions.clipboard_image_path` 仅记录"动作 hook 触发瞬间最新一张剪贴板图的路径"（不存历史），动作期内更早的剪贴板图全部保留落盘但**不进 action 行**；`health_stats.clipboard_event_count` 仍按所有事件累加；保持 `desktop_actions` schema 简洁（不引入 1:N 子表也不改 `clipboard_image_path` 列类型），同时不丢任何剪贴板图（Phase 2 接通 UI 播放器时可按 event_seq 时序回放）
- Q: `_FrameRingBuffer` 容量上限？连续动作 lookback 重叠时的 buffer 复用策略？ → A: **固定容量 30 帧（约 2 秒）**——FIFO 自动丢弃最老帧；按原生屏幕分辨率（典型 1920×1080 RGB ≈ 6MB/帧；缩放估算下限 1280×720 ≈ 2.6MB/帧）30 帧约 78-180MB，远低于 CC-007 < 500MB 软目标；2 秒长度可保证间隔 ≥ 0 秒的两个连续动作都能拿到完整前 1 秒 lookback（不会因第二动作来得太快而 lookback 被截短），相比 1 秒容量更稳，相比 4 秒更省内存；首动作 buffer 不足 30 帧时仍按 FR-005 既定规则取所有可用帧

### Session 2026-05-02 (round 6)

- Q: sanity check "放弃录制" vs "重新录制"两按钮在 `desktop_recordings.status` 终态、目录处理、UI 跳转上的具体差别？ → A: **status 完全一致**——两按钮都把 `desktop_recordings.status` UPDATE 为 `abandoned`，DB 行 + 目录均保留待用户手动清理；区别仅在 UI 跳转目标：**放弃录制** → 回到录制页且**不预选 mode**（用户自由切换浏览器/桌面/扩展触发任一模式）；**重新录制** → 回到录制页且**默认预选桌面 mode**（不立即启动 hook，避免 hook 突然启动），用户需再次手动点"开始"。理由：保持 status 状态机仅 `recording / stopped / abandoned` 三态，避免引入第四态；"重新录制"语义本质 = "放弃 + 立即开始下一次"，与"放弃 + 回到原态"差的只是 UI 入口预选状态
- Q: 试用子进程的工作目录（cwd）契约？影响 Programmer 代码相对路径行为与可调试性 → A: **cwd = 本次试用专属临时目录 `data/trials/<trial_id>/`**——`trial_id` 用与 `recording_id` / `action_id` 同套 UUID 生成函数；`src/execution/desktop_trial_runner.py` 在试用启动前 MUST 自动创建该目录，业务层只负责调用 runner 与编排事件，UI MUST NOT 直接创建或写入 `data/trials/`；Trial 退出后**保留 7 天**供事后调试（完整 stdout / stderr 落该目录下 `stdout.log` / `stderr.log`，与 FR-021a "完整 stdout / stderr 落进程日志文件"语义对齐）；超期由 startup-time cleanup hook 删除（`ensure_startup_recovery()` 同期扫描 `data/trials/` 下 mtime > 7 天的子目录并 `rmtree`）；隔离 Programmer 代码对项目根 / 录制数据的意外写入，相对路径行为每次都从同样的空目录起点解析，可预测可复现
- Q: syntax gate 失败时反馈给 Programmer Agent 的消息格式？影响重试成功率 → A: **自然语言简述 + lineno + 出错行±2 行代码片段 + "请重新输出完整函数"指令**——格式模板：`你之前生成的代码在 line {lineno} 出现语法错误：{msg}\n\n出错位置（含上下 2 行）：\n{snippet}\n\n请重新输出修复后的完整 \`async def execute() -> dict\` 函数。`；不暴露 `offset` / `filename` 等内部属性以降低 LLM 输出噪声；"请重新输出完整函数"指令明确避免 LLM 误判增量修复语义；上下 2 行片段（共 5 行）token 占用可控；3 次连续失败时上报终态前的最后一次反馈也用此格式落进程日志
- Q: `recording.desktop.vision_model` 未配置时对用户的可见提示路径？避免 P2 多模态分析静默失败用户找不到原因 → A: **UI 设置面板暴露字段 + intent 页首次进入弹一次性 toast**——(1) 设置面板新增"桌面录制"配置区，显式列出 `vision_model` 字段（带说明文本"留空 → 桌面 mode 下 `analyze_desktop_action` 多模态分析工具不可用，PM 仅能基于动作元数据回答问题"）；(2) 桌面 mode 下首次进入 intent 页时，若 `vision_model` 缺失 UI MUST 显示一次性 toast"未配置 vision_model，多模态分析功能不可用，可在 设置 → 桌面录制 配置后重启"，自动消失约 **8 秒**（比普通 5s toast 长，确保用户读完），非模态、不阻塞 PM 启动；(3) toast 仅每个 recording_id 第一次进 intent 页时显示一次，避免重复打扰；不修改桌面 PM prompt（避免 LLM 推理负担去判断工具是否存在）
- Q: `analyze_desktop_action` 内部把多帧 PNG + 剪贴板图喂给 vision LLM 时的排列顺序、时序元数据、剪贴板图位置？影响 vision LLM 输出质量与 token 成本 → A: **每帧前附简短文字说明 + 剪贴板图前置 + 多 action 显式分隔**——工具内部 MUST 按以下结构组装多模态消息：(1) 对每个 action_id，按 `timestamp` 升序串接其帧序列；(2) 每张帧前 MUST 插入文字说明 `Action <id> 帧 N/M (T={t}ms 相对动作开始)`，其中 N=当前帧序号、M=该动作总帧数、t=该帧 timestamp 相对动作 hook 触发时刻的毫秒偏移（动作前为负值）；(3) 该 action 若有剪贴板图（`clipboard_image_path` 非空），剪贴板图 MUST 紧接该 action 帧序列**之前**插入，前缀文字 `Action <id> 剪贴板图（动作 hook 触发瞬间最新一张）`；(4) 多个 `action_ids` 时按 timestamp 顺序串接，不同 action 之间用文字 `--- Action <prev_id> 帧序列结束 / Action <next_id> 开始 ---` 分隔；(5) 用户传入的 `question` 参数 MUST 放在所有图与说明文字之后作为最终 prompt，避免被中间元数据淹没。短文字元数据对 vision LLM 时序理解的价值 >> token 成本；剪贴板图作为"动作的输入背景"放在帧前符合自然逻辑；显式分隔避免 LLM 混淆多 action 帧

### Session 2026-05-02 (round 7)

- Q: `desktop_actions` 是否需要 `monitor_index` 列以记录单条动作所在屏？影响跨屏录制下单条动作的屏溯源能力 → A: **加 `monitor_index INTEGER` 列**——每条动作落 hook 触发瞬间 cursor 所在屏 index，与 FR-006 "锁定动作时刻屏幕" 语义对齐（frames 取自该屏，meta 也记录该屏）；session 级 `desktop_recordings.monitor_index` 仍保留作为"录制启动时主屏"语义参考，跨屏录制下两者可能不一致；Phase 2 接通 UI 播放器时按 `desktop_actions.monitor_index` 回放无需回查 cursor 屏
- Q: vision LLM provider（OpenAI / Anthropic / 本地多模态）选择是否独立于 `analyze_image` 现行 provider 配置？影响 config 模型与 provider routing 路径 → A: **provider 完全沿用 `analyze_image` 当前 provider 配置**——不新增 `recording.desktop.vision_provider` 字段，仅 `recording.desktop.vision_model` 独立指定 model 字符串；provider routing 复用 `analyze_image` factory；与 "密钥统一"语义一致（provider 与 keyring entry 强绑定，分裂 provider 必然分裂 keyring）；前置假设：用户的 `analyze_image` provider 本身就是支持 vision 的 provider（不在 vision-capable provider 列表时 `analyze_desktop_action` 仍按 `vision_model` 字符串调用，失败由 FR-013 现有 `[error: vision_failed]` 路径兜底，不引入启动期 provider 白名单校验）；跨 provider 混搭推迟到 Phase 2
- Q: 用户点录制页"开始"按钮的 mouse_left click 是否会被 hook 抓为首动作？影响 5 标准场景首动作语义与 SC-001 客观判定可靠性 → A: **hook 在主窗 minimize 完成事件回调后启动**——点"开始"按钮触发 `QMainWindow.showMinimized()`，Recorder MUST 监听 `QWidget.changeEvent` 中 `windowState() & Qt.WindowMinimized` 跃迁信号（或等价 Qt minimize 完成回调），跃迁触发后再启动 pynput hook + ring buffer + UIA 异步队列 + 剪贴板订阅；物理上消除"点开始"click 被 hook 抓为首动作的可能（minimize 完成时该 click 已被 Qt 消费完毕）；与 FR-022 "minimize 让出工作区"自然串联，不引入倒计时不引入额外 UX 元素；Qt minimize 事件在 Windows 上通常 ≤ 100ms 完成，对"立即启动"用户感知无影响——FR-022 "立即启动"语义此处定义为"相对用户视角连续，非物理时刻零延迟"

### Session 2026-05-02 (round 8)

- Q: `analyze_desktop_action` 分析的 `action_ids` 含 typing 类型动作时，该 action 的 `text_content`（已知用户输入文本）是否进 vision LLM prompt？影响 vision 输出对"用户输入了什么"判断精度（IME / 非英文字符画面识别困难场景） → A: **`text_content` MUST 作为前缀文字进 prompt**——多模态消息组装时，对 typing 类型 action（`type=typing`），在该 action 帧序列**之前**（与剪贴板图前置位置同模式）插入文字 `Action <id> 用户输入文本: <text_content>`；若 `text_content` 已被 large_field 占位替换（≥ `recording.large_field.threshold_chars` 即 1000 字符），prompt 中按占位形态原样插入（前缀文字仍写但占位符片段保持）；非 typing action（mouse_* / wheel / drag / hotkey）不插入 `text_content` 前缀（这些类型 `text_content` 列为 NULL）；剪贴板图前缀（如有）与 text_content 前缀**两条同时存在时**，typing 文本前缀在前、剪贴板图前缀在后（输入文本是动作核心、剪贴板图是输入背景，按"核心 → 背景 → 帧序列"语义排序）
- Q: PNG 帧上传 vision LLM 前"缩放到长边 1280px"是仅缩小还是双向？影响 vision LLM 文字识别精度与 token 成本（低分辨率屏被放大引入插值噪声 vs 归一化 token 可预测） → A: **仅缩小不放大**——`new_long_edge = min(1280, 原长边)`，短边按原图比例等比同向缩放（原长边 ≤ 1280 时整图保持原尺寸不做任何缩放，避免插值噪声降低文字识别精度）；语义对齐 `PIL.Image.thumbnail` 默认行为；Phase 1 落盘 PNG 仍为原生屏幕分辨率（FR-005 不变），仅 `analyze_desktop_action` 上传 vision LLM 前在工具内部做此单向缩小

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 录制桌面操作并产出可分析数据 (Priority: P1)

用户在录制页选择"桌面"模式并点"开始"，在主屏上完成一段桌面任务（例如：在记事本里打开 → 输入 → 保存）；用户随时可通过浮窗按钮或全局快捷键停止录制。停止后系统弹出健康反馈对话框，用户点"继续分析"进入 intent 页；Agent 对桌面录制的完整分析能力由 User Story 2 覆盖。

**Why this priority**: 这是桌面录制的最小可用闭环——没有它，整个 Phase 1 无法验证。当前主仓库 `RecordingMixin._on_recording_started` 对 DESKTOP 直接弹"暂不支持"，本故事的目标是把这个分支变成完整可用路径。

**Independent Test**: 单独跑通"开始录制 → 在记事本完成至少 5 个动作 → 停止 → 健康对话框显示动作总数 ≥ 5 → 点'继续分析'进入 intent 页"。不依赖后续多模态分析或试用层；Agent 基于桌面数据回答由 User Story 2 独立验收。

**Acceptance Scenarios**:

1. **Given** 用户位于录制页且未启动其他录制，**When** 用户选"桌面"模式并点"开始"，**Then** 主屏右下角出现"🔴 录制中 0 个动作 [停止]"浮窗，全局键鼠/剪贴板抓取启动
2. **Given** 录制中且用户在记事本里完成 5 个以上动作，**When** 用户点浮窗"停止"或按 Ctrl+Alt+S，**Then** 录制结束，健康反馈对话框弹出，显示动作总数、各类型分布、UIA 命中率、剪贴板事件数
3. **Given** 健康对话框已弹出，**When** 用户点"继续分析"，**Then** status 变为 `stopped`，UI 进入 intent 页并可启动后续 PM Agent 流程
4. **Given** 用户已在使用浏览器录制或扩展触发录制，**When** 用户尝试启动桌面录制，**Then** 桌面入口被禁用且程序拒绝启动（双保险）

---

### User Story 2 - Agent 用多模态分析桌面录制 (Priority: P1)

用户在 intent 页向 Agent 提问"刚才那段操作里我点了什么？"或"用户最后保存到哪里了？"。Agent 通过桌面专属工具列出动作元数据、按需请求多模态模型分析关键节点的画面，并把文本结论用于推理。Agent 不直接看图（图片不进主上下文），但能给出基于画面的具体答案。

**Why this priority**: P1 共两个故事；没有这个故事，P1 故事 1 产出的数据无法被 Agent 真正消费，桌面录制也就无法驱动后续技能学习。多模态识别是桌面场景与浏览器（DOM 可读）的关键差异。

**Independent Test**: 用一段已录制好的桌面 fixture（5 个动作以上、含 1 个剪贴板复制）跑 PM Agent，验证 Agent 能调用 `list_desktop_actions` 列出动作、调用 `analyze_desktop_action` 拿到画面文本结论、最终生成可执行的 intent 描述。

**Acceptance Scenarios**:

1. **Given** 一段桌面录制已落库，**When** Agent 调用 `list_desktop_actions(recording_id)`，**Then** 返回每条动作的元数据（type / timestamp / coords / window_title / uia_summary / clipboard_text 占位 / has_clipboard_image / frame_count / has_clip）
2. **Given** Agent 想理解某个动作发生了什么，**When** Agent 调用 `analyze_desktop_action(action_ids=["..."], question="点击后界面发生了什么变化？")`，**Then** 工具内部把多帧 PNG 与剪贴板图喂给配置的 vision LLM，仅返回文本结论给主 Agent 上下文（图片不进主上下文）
3. **Given** Agent 在大量动作里需要导航，**When** Agent 调用 `query_data` 按 window_title 分组聚焦或按时间范围切片，**Then** 通用工具内部按 mode 切表查 `desktop_actions`，行为与浏览器路径一致（同一组 SQL 占位/错误码语义）
4. **Given** 浏览器录制已有的 5 个通用工具（`describe_data` / `query_data` / `execute_code` / `read_recording` / `read_field_chunk`）被沿用到桌面 mode，**When** 在浏览器 fixture 上重跑 baseline，**Then** 返回 JSON 与改造前 byte-equal（mode dispatch 不引入浏览器回归）

---

### User Story 3 - 试用 Agent 在桌面真实执行 (Priority: P2)

PM Agent 在 intent 页给出方案后，Programmer Agent 按强契约写出 `async def execute() -> dict` 无参函数（自选 pywin32 / COM / subprocess / pywinauto 等），返回 `{"ok": bool, "summary": str, "details": dict | None}`；试用 Agent 在主屏真实执行验证（wrapper 自动 `asyncio.run` + JSON 写 stdout 末行）。试用启动前显示提示对话框、跑期间不抢焦点、跑完通知用户结果；超过 120 秒强制 kill 兜底。

**Why this priority**: 没有这个故事，桌面录制只是"看得见"，不是"学得会"——技能闭环未完成。但相对于 P1（录制 + 分析），试用是后置闭环，可独立后落地。

**Independent Test**: 用一段记事本"打开 → 输入 'hello' → 保存"录制走完 PM → Programmer，得到一段执行代码；启动试用，观察"事前提示 → 跑期间无遮挡 → 跑完通知"流程；故意写一段死循环代码验证 120 秒 kill 兜底。

**Acceptance Scenarios**:

1. **Given** Programmer Agent 已生成桌面执行代码，**When** 用户点"试用"，**Then** 弹出事前提示对话框；用户点"开始"后试用正式执行；执行期间不弹任何模态遮挡焦点
2. **Given** 试用代码正常完成，**When** 子进程退出，**Then** execution runner 解析 stdout 末行 JSON（`{"ok", "summary", "details"}`）并生成 `TrialResult`，UI 通过 business/blinker 结果按 `ok` 决定标题"成功/失败"、用 `summary` 填充正文，弹出完成通知
3. **Given** 试用代码超过 120 秒未返回，**When** 内部超时触发，**Then** 通过 `Popen.terminate()` + `taskkill /F /T <pid>` 整树 kill 子孙进程并通知用户超时
4. **Given** Programmer 给出的代码体现"找捷径"思维（如启动 VSCode 走 `subprocess.run(["code", file])` 而非全坐标模拟），**When** 按 SC-004 客观规则机械判定 + 人工 spot check 复核 5 个标准场景，**Then** 至少 3/5 走捷径

---

### User Story 4 - 录制健康反馈与早期止损 (Priority: P3)

用户停止录制时立即看到一个 sanity check 对话框，按健康判定标红/黄/绿（动作总数 / 帧总数 / UIA 命中率 / 剪贴板事件）。如果数据明显异常（如动作 = 0、UIA 命中率偏低或 clip 失败率过高），用户可直接点"放弃录制"软删除本次数据（标记 `status='abandoned'`，行与目录保留待用户手动清理）；觉得需要重来则点"重新录制"回到录制页重新开始。

**Why this priority**: 提升用户体验和减少无效录制对下游的干扰，但不阻碍 P1/P2 闭环。先有 P1/P2，P3 在 UX 维度增益。

**Independent Test**: 故意让一段录制无任何动作（不点不输入，30 秒后停），验证 sanity check 标红且"动作总数 = 0"高亮，"放弃录制"按钮把 `desktop_recordings.status` UPDATE 为 `abandoned`（DB 行 + 目录保留），后续 PM Agent 入口不再可达该录制；再做一段正常录制验证"继续分析"按钮路径与绿色态。

**Acceptance Scenarios**:

1. **Given** 录制结束，**When** sanity check 对话框弹出，**Then** 显示动作总数 / 各类型分布 / 帧总数 / clip 数 / 剪贴板事件 / UIA 命中率 / 录制时长，按健康判定标色
2. **Given** 用户对本次数据不满意，**When** 用户点"放弃录制"，**Then** `desktop_recordings.status` 被 UPDATE 为 `abandoned`（DB 行 + 目录均保留待用户手动清理），后续 PM Agent 入口不再可达该录制，UI 回到录制页
3. **Given** 用户点"重新录制"，**When** 当前录制被放弃（`status` UPDATE 为 `abandoned`，DB 行 + 目录保留），**Then** 回到录制页且默认**预选桌面 mode**（不立即进入录制态，避免 hook 突然启动；用户需手动再次点"开始"）；与"放弃录制"按钮的区别仅在 UI 预选行为，status 终态完全一致

---

### Edge Cases

- **录制中崩溃**：进程异常退出导致部分目录与 `desktop_recordings` / `desktop_actions` 行残留——Phase 1 不做任何 crashed 处理（不打 status tag、不清理目录、不清理 DB 行）；启动期 `ensure_startup_recovery()` 不扫描 desktop 表；孤儿目录用户手动 `rm -rf data/recordings/<recording_id>/`；崩溃恢复整体推迟到 Phase 2。Phase 1 无录制历史列表 UI，孤儿行无路径被用户/Agent 触达，因此安全
- **跨屏切换**：录制中用户把鼠标从屏 A 拖到屏 B——按 9.12 #8 锁定动作时刻屏幕，前后所有帧从那屏取；新屏出现时新屏前 1 秒可空（不补帧）
- **多屏不同 DPI scale**（如屏 A 100% + 屏 B 150%）：进程显式声明 Per-Monitor V2 DPI awareness，pynput / Win32 / UIA 全部按 physical pixel 对齐；`coord_x` / `coord_y` 落库即 physical，跨屏切换不需做坐标换算
- **全局快捷键被占用**：Ctrl+Alt+S 被 OBS / 截图工具占用导致 `RegisterHotKey` 失败——录制依然可启动，UI 弹一次 toast 提示用户改用浮窗按钮
- **vision LLM 调用失败**：API 超时或 401——`analyze_desktop_action` 仍返回纯字符串，失败段以 `"Action <id>：[error: <reason_code>]"` 形式与成功段拼接（reason_code: `vision_timeout` / `vision_unauthorized` / `vision_failed`），Agent 解析文本识别失败段并决定退避策略；不阻塞工具集其他工具
- **typing 序列长尾**：用户连续打字超过 30 秒——按 9.14 B1 方案 e（停字 1s / 切非字符键 / 切窗口 / 鼠标动作 任一先到结束序列）切片
- **拖拽 vs 单击边界**：位移 ≤ 5px 且时间 ≤ 200ms 视为单击；任一超阈视为拖拽，拖拽 up 也触发画面（看放下后状态），且 `coord_x` / `coord_y` / `timestamp` / UIA 查询点全部取 up 终点
- **剪贴板巨型文本/图片**：长文本走现有 `recording.large_field.*` 占位 + `read_field_chunk`；图片不暴露给 Agent，仅由 `analyze_desktop_action` 内部喂给 vision LLM
- **桌面与浏览器并发录制尝试**：UI 禁用 + 程序拒绝双保险，三模式（浏览器/桌面/扩展触发）两两互斥
- **浏览器路径回归**：5 个通用工具 mode dispatch 改造期间，浏览器 fixture diff 必须为零

## Requirements *(mandatory)*

### Functional Requirements

#### 录制层

- **FR-001**: 系统 MUST 支持启动桌面录制模式，从 `RecordingMixin._on_recording_started` 经 `DesktopRecordingService` / business bridge 路由到 `DesktopRecorder`，去除"暂不支持"分支；UI 层不得直接实例化或启动 Recorder
- **FR-002**: 系统 MUST 通过 pynput 全局 hook 抓取鼠标左键 / 右键 / 中键 / 滚轮 / 拖拽 / 特殊键 + 组合键 / 字符输入序列；不抓鼠标移动；**pynput keyboard/mouse hook 注册失败 MUST 阻塞录制启动**并弹错对话框（hook 是录制根基，无 hook 无意义），不进入降级路径。键盘类动作 MUST 按以下规则归类为 `hotkey` 或 `typing`：
  - `hotkey`（单事件）：按键事件含 Ctrl / Alt / Win 任一修饰键（不含 Shift）；或功能键单按（F1-F12 / Esc / Enter / Tab / 方向键 / Backspace / Delete / Home / End / PageUp / PageDown）
  - `typing`（累积序列）：纯字符键（含 Shift+letter 这种纯输入修饰）+ 中文 IME 候选输入；Shift 视为输入修饰（决定大小写/符号），不打断 typing 序列
- **FR-003**: 系统 MUST 在 hook 触发时同步查询 UIA `ElementFromPoint(x, y)`（50ms 超时），超时排进异步队列稍后 UPDATE 该 action 的 `uia_summary`；**UIA COM 初始化失败 MUST 降级启动**（uia_summary 全空，对应 health_stats.uia_total = uia_hit = 0），UI 弹一次 toast 提示"UIA 不可用，控件元数据将为空"。`uia_total` / `uia_hit` 仅累加**鼠标类动作**（mouse_left / mouse_right / mouse_middle / wheel / drag），typing / hotkey 不触发 UIA 查询且不计入分母。`window_title` MUST 从 `ElementFromPoint(cursor_pos)` 返回控件向上溯源到 **owning window** 取（与 FR-006 cursor 屏锁定语义对齐），不调 `GetForegroundWindow()`；这样 cursor 屏的 owning window 与控件信息保持同一来源，避免与系统全局 foreground window 分裂到不同屏
- **FR-004**: 系统 MUST 在剪贴板变更时（WM_CLIPBOARDUPDATE 订阅 + 500ms 兜底；Ctrl+V 立即读）抓取剪贴板内容，文本类内联或长文本占位、图片类落到 `clipboard/` 目录不暴露给 Agent；剪贴板图 MUST 按 `clipboard/<recording_id>_<event_seq>.png` 命名（`event_seq` 在本次 recording 内从 1 自增），所有事件的图都独立落盘不互相覆盖；Recorder MUST 内部维护 `_ClipboardLatest` 最新引用，`desktop_actions.clipboard_image_path` 在 hook 触发时取该引用（即"动作瞬间最新一张"路径，单路径），动作期内更早的剪贴板图保留落盘但不写入 action 行；`health_stats.clipboard_event_count` 按所有事件累加。**剪贴板 WM_CLIPBOARDUPDATE 订阅失败 MUST 降级启动**（剪贴板事件全空），UI 弹一次 toast 提示"剪贴板订阅失败，剪贴板事件不会被捕获"
- **FR-005**: 系统 MUST 维护一个共享的 `_FrameRingBuffer`（15 fps，**固定容量 30 帧 ≈ 2 秒**，FIFO 自动丢弃最老帧），动作触发时从缓冲取前 1 秒 + 后 2 秒约 45 帧，分两条 sink 编码：多帧 PNG（必有）+ mp4 clip（受 `recording.desktop.enable_clip` 开关控制）；2 秒容量保证间隔 ≥ 0 秒的两个连续动作都能拿到完整前 1 秒 lookback（不会因第二动作来得太快而被截短）；按原生屏幕分辨率单帧约 6MB（1920×1080 RGB）估算，30 帧 ≈ 180MB，符合 CC-007 < 500MB 软目标。clip 编码失败时 PNG sink MUST NOT 受影响（PNG 仍生成），`desktop_actions.has_clip=FALSE`、clip 文件不落盘，`health_stats.clip_total++` 但 `clip_success` 不变。PNG 帧 MUST 按原生屏幕分辨率落盘（不缩放），PNG 压缩级别使用默认 `compress_level=6`；`analyze_desktop_action` 上传 vision LLM 前 MUST 在工具内部对帧做**仅缩小不放大**的等比缩放（`new_long_edge = min(1280, 原长边)`，短边按原图比例同向缩放；原长边 ≤ 1280 时整图保持原尺寸不做任何缩放，避免低分辨率屏被放大引入插值噪声降低文字识别精度；语义对齐 `PIL.Image.thumbnail` 默认行为）；落盘文件本身保持原生分辨率以保留 Phase 2 接通 UI 播放器的可能性。录制启动 < 1 秒就触发首动作时，前置帧 MUST 取 buffer 里**所有可用帧**（不足 15 帧也写、不丢首动作、不等齐 1 秒、不复制填充），`frame_count` 如实记录实际帧数（可能 < 45）
- **FR-006**: 系统 MUST 在主屏多显示器场景下只录制鼠标所在屏幕，按 `cursor_pos` 解析 monitor，跨屏时锁定动作时刻屏幕。进程启动期 MUST 显式声明 **Per-Monitor V2 DPI awareness**（`SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)`），pynput / Win32 / UIA `ElementFromPoint` 三者统一使用 **physical pixel**；`desktop_actions.coord_x` / `coord_y` 落库即 physical，不做 logical↔physical 转换、不增加额外坐标列

#### 数据层

- **FR-007**: 系统 MUST 新建 `desktop_recordings` 与 `desktop_actions` 两张 DuckDB 表（仅动作流元数据），帧 / clip / 剪贴板图按 `data/recordings/<recording_id>/{frames/<action_id>/, clips/, clipboard/}` 目录约定不进 DB；`desktop_recordings` MUST 包含 `health_stats` JSON 列（停止时由 Recorder 一次性写入汇总：uia_hit / uia_total / clip_success / clip_total / clipboard_event_count / 各 action_type 计数）
- **FR-008**: 系统 MUST 在 `desktop_actions` 表里包含 `coord_x` / `coord_y` 两列、`monitor_index` INTEGER 列（hook 触发瞬间 cursor 所在屏 index，与 FR-006 锁定动作时刻屏幕语义对齐；drag 取 up 终点屏；跨屏录制下与 session 级 `desktop_recordings.monitor_index` 可能不一致，session 级保留作"录制启动时主屏"参考）、`recording_mode` 列、与现有 `actions` 表一致的 `timestamp` 语义；`recording_id` / `action_id` MUST 复用现有 `recording_sessions` / `actions` 同套生成函数（VARCHAR + 主仓 UUID 规则），不引入桌面专属 ID 格式。drag 类型的 `coord_x` / `coord_y` / `timestamp` MUST 取 **mouse_up 终点**（与 Edge Case "拖拽 up 触发画面" 一致），`duration_ms` 记 down→up 时长；UIA 查询 MUST 用 up 点坐标（即 "用户拖到了哪"）
- **FR-009**: 系统 MUST 修正 `RecordingRepository.save_recording_session()` 的 `recording_mode` default（当前 `'desktop'` 是隐患），改为必填或默认 `'browser'`
- **FR-010**: 系统 MUST 修正 `src/data/config_models.py:176` (`default_recording_mode = "desktop"`) 与 `src/ui/widgets/recording_widget.py:459` (`fallback=BROWSER`) 的 default 错配，统一为 `BROWSER`

#### Agent 工具层

- **FR-011**: 系统 MUST 让 5 个通用工具（`describe_data` / `query_data` / `execute_code` / `read_recording` / `read_field_chunk`）按 `recording_mode` 内部切表：浏览器走现有 5 张表，桌面走 `desktop_recordings` / `desktop_actions`；`read_recording(recording_id)` 在桌面 mode MUST 返回 `desktop_recordings` 行（含 `health_stats` JSON） + **聚合摘要**：动作总数、按 `type` 分组计数、按 `window_title` 分组计数（前 5 个）、时间范围 `[first_ts, last_ts]`、首尾节点原始行（前 5 + 后 5 共 ≤10 行）；MUST NOT 返回中段原始动作行（Agent 用 `list_desktop_actions` 翻页取深，避免首调 token 压爆）；输出结构与浏览器 mode 同形（同一 schema、内部按 mode 切数据源）
- **FR-012**: 系统 MUST 在 `create_recording_tools(recording_id)` 工厂里通过 `RecordingRepository.get_recording_mode(recording_id)` 查询 mode 一次，闭包传给 5 个 handler 与 `query_data_pre_hook`（解决 hook contract 拿不到 mode 的漏洞）。`get_recording_mode()` 是唯一 mode 查询入口：先按浏览器录制路径查 `recording_sessions.recording_mode`，未命中再查 `desktop_recordings.recording_mode`；两表均未命中时返回标准化 `recording_not_found` 错误，不要求桌面录制镜像写入 `recording_sessions`
- **FR-012a**: `describe_data` / `query_data` MUST 按 mode 严格隔离 allowlist：浏览器 mode allowlist = 现有 5 张浏览器表（`recording_sessions` / `actions` / `network_requests` / `sibling_snapshots` / `recording_screenshots`），**完全屏蔽**桌面 2 张表；桌面 mode allowlist = `{desktop_recordings, desktop_actions}`，**完全屏蔽**浏览器 5 张表；允许 mode 内两表 JOIN（如 `desktop_recordings × desktop_actions`）；触及非本 mode 表时 sqlglot security gate MUST 拒绝并返回标准化错误 `{"error": "table_not_in_mode", "table": "<name>", "mode": "<current_mode>"}`
- **FR-013**: 系统 MUST 提供 3 个桌面专属工具：
  - `list_desktop_actions(recording_id, time_range?, action_types?, offset=0, limit=100)` — `limit` 上限 500；`action_types: list[str] | None` 元素从枚举集 `{"mouse_left", "mouse_right", "mouse_middle", "wheel", "drag", "typing", "hotkey"}` 取（大小写敏感、与 `desktop_actions.type` 列值完全一致），`None` / 省略 = 不过滤；元素含枚举集外字符串时 MUST 返回 `{"error": "invalid_action_type", "value": "<x>"}`，不静默忽略
  - `analyze_desktop_action(action_ids, question)` — `action_ids` Phase 1 上限 2 个；**始终**返回纯字符串，按 action_id 分段（`"Action <id1>：<text>\n\nAction <id2>：<text>"`），不带 provider/model 元数据；超过 `recording.large_field.threshold_chars` 自动 large_field 占位。失败时（vision LLM 超时 / 401 / 单段分析失败）失败段写为 `"Action <id>：[error: <reason_code>]"` 与成功段拼接为同一字符串返回；不返回 dict 错误对象、不抛异常；reason_code 至少覆盖 `vision_timeout` / `vision_unauthorized` / `vision_failed`（兜底）。Phase 1 不设单次会话/单 recording 累计调用上限（无 quota / rate limit / UI 阻断），仅在每次调用后写一条 INFO 日志（含 recording_id / action_ids / 本次上传帧数 / 当前会话累计调用次数与累计帧数）便于事后成本审计。多模态消息组装顺序 MUST 按以下结构：对每个 action_id 按 `timestamp` 升序串接帧序列；**对 typing 类型 action（`type=typing`）MUST 在该 action 帧序列之前插入前缀文字 `Action <id> 用户输入文本: <text_content>`**（`text_content` 已 large_field 占位时按占位形态原样插入；非 typing action 不插入此前缀，列值为 NULL）；该 action 若有剪贴板图（`clipboard_image_path` 非空），剪贴板图 MUST 紧接该 action 帧序列**之前**插入，前缀文字 `Action <id> 剪贴板图（动作 hook 触发瞬间最新一张）`；**typing 文本前缀与剪贴板图前缀同时存在时排序为"typing 文本前缀 → 剪贴板图前缀 → 帧序列"**（输入文本是动作核心、剪贴板图是输入背景）；每张帧前插入文字说明 `Action <id> 帧 N/M (T={t}ms 相对动作开始)`（N=当前帧序号、M=该动作总帧数、t=该帧 timestamp 相对动作 hook 触发时刻的毫秒偏移，动作前为负值）；多个 `action_ids` 间用文字 `--- Action <prev_id> 帧序列结束 / Action <next_id> 开始 ---` 显式分隔；用户传入的 `question` 参数 MUST 放在所有图与说明文字之后作为最终 prompt
  - `read_action_clip(action_id)` — 仅返回 mp4 路径与元数据，不进 Agent 主上下文；`has_clip=FALSE` 时返回标准化错误对象 `{"error": "clip_unavailable", "action_id": "<id>"}`
- **FR-014**: 系统 MUST 在桌面 mode 下不注入 `analyze_image`（由 `analyze_desktop_action` 取代）；浏览器 mode 下保留 `analyze_image` 不变
- **FR-015**: 系统 MUST 通过独立工厂 `create_desktop_specific_tools(recording_id)` 提供 3 桌面专属工具，由 Orchestrator 拼接到桌面 PM / Programmer / Trial 工具集。桌面 Trial 工具集 = 浏览器 Trial 现行配置经 mode dispatch 后的对称等效；浏览器 mode 下任一 PM / Programmer / Trial 工具集若包含 `analyze_image`，桌面 mode 均等价替换为 3 桌面专属工具，保持三者工具集对称

#### Agent 编排层

- **FR-016**: 系统 MUST 实现 `build_pm_prompt(recording_mode)` / `build_programmer_prompt(recording_mode)`，浏览器 mode 返回 `PM_SYSTEM_PROMPT_LEGACY` 全文（字节级保留），桌面 mode 返回 `_PM_COMMON_HEADER + _PM_DESKTOP_GUIDANCE + _PM_COMMON_FOOTER` 三段拼接
- **FR-017**: 系统 MUST 在 Orchestrator 启动 PM / Programmer Agent 前分别用 `dataclasses.replace(PM_CONFIG, system_prompt=build_pm_prompt(...))` 与 `dataclasses.replace(PROGRAMMER_CONFIG, system_prompt=build_programmer_prompt(...))` 构造临时 AgentConfig 拷贝；`agent_loop.format_system_prompt()` 不改造
- **FR-017a**: Orchestrator MUST 在拿到 Programmer 输出代码后、交给 Trial 子进程前执行 `ast.parse` syntax gate；语法错误时 MUST **自动把错误反馈给 Programmer Agent 重新生成**（重试上限 = 2 次，共最多 3 次 Programmer 出码尝试），全程对用户透明（用户视角仅感知"Programmer 思考中..."状态延长）。反馈消息 MUST 按以下模板构造：
  ```
  你之前生成的代码在 line {lineno} 出现语法错误：{msg}

  出错位置（含上下 2 行）：
  {snippet}

  请重新输出修复后的完整 `async def execute() -> dict` 函数。
  ```
  其中 `{msg}` = `SyntaxError.msg`，`{lineno}` = `SyntaxError.lineno`，`{snippet}` = 出错行 ± 2 行代码片段（共 ≤ 5 行）；MUST NOT 暴露 `offset` / `filename` 等内部属性；3 次连续失败 MUST 终态失败并 UI Toast 标题 "Programmer 输出代码持续语法错误" + 正文 = 末次 `ast.parse` 异常的 `msg` + `lineno`，同时把全部 3 次代码、按上述模板构造的反馈消息、原始 `SyntaxError` 异常落进程日志供事后追溯；syntax gate 与重试逻辑 MUST 由独立单元测试覆盖（fixture：合法代码一次通过 / 一次语法错二次通过 / 连续 3 次语法错触发终态失败 / 反馈消息模板渲染断言）
- **FR-018**: 系统 MUST 给 `execution_strategy` 增加 `desktop` 取值，至少同步 `src/business/agents/tools/programmer_tools.py` 的 tool schema enum 与 `src/business/tool_trial/trial_models.py` 中 `execution_strategy` 的语义注释 / 允许值，保证 Programmer 输出、持久化快照和 Trial 分发都接受桌面策略
- **FR-019**: 桌面 PM prompt MUST 包含导航策略段（先看头尾 → 按 window_title 聚焦 → 跳过冗余类型 → 关键节点用 `analyze_desktop_action`），不在工具层强制配额
- **FR-020**: 桌面 Programmer prompt MUST 包含 1-2 个"找捷径"元思维例子（如双击微信图标 → `start wechat:` / Windows Search），不写死对照表；MUST 强约束生成代码契约——`async def execute() -> dict` 无参函数，返回 `{"ok": bool, "summary": str, "details": dict | None}`

#### 试用层

- **FR-021**: 桌面试用 MUST 走方案 e：事前提示对话框 → 用户点"开始" → 跑期间无遮挡 → 跑完通知；子进程执行协议（含 120s 超时 kill、env 隔离、cwd 隔离、wrapper 契约等）见 FR-021a；不做模态强守门、不做全局热键中止。"事前提示对话框" MUST 包含：(a) 文案"试用代码即将在桌面真实执行（最长 120s）"；(b) 代码前约 20 行预览（可滚动展示完整代码）；(c) 检测到的高危 API 列表（按 SC-004 同套规则机械检测：`subprocess` / `os.startfile` / `webbrowser` / Win32 协议 URL / `pywin32` 高级 API / `pywinauto` 控件级 API 命中即标签化展示；Win32 协议 URL 排除 Windows 盘符路径如 `C:\foo`）；(d) "开始 / 取消"双按钮，"取消"= 放弃试用并回到 intent 页。"跑完通知" MUST 复用现有普通 Toast（右下角浮层、非模态、自动消失约 5s、不抢焦点），不复用 `AuthToastSurface`（高危确认浮层），不接入 Windows 系统原生通知中心，不写入对话历史
- **FR-021a**: 试用代码 MUST 通过 `src/execution/desktop_trial_runner.py` 使用 `subprocess.Popen` 启动 `python -u -c <wrapper>` 独立子进程执行；wrapper 自动包 `asyncio.run(execute())` 调用 Programmer 生成的 `async def execute() -> dict`，并把返回字典序列化为 JSON 写到 stdout 末行。

  stdout/stderr MUST 由 execution runner 走 PIPE 收集、落盘并解析；runner MUST 构造 `TrialResult` 后交给 business/orchestrator，business 通过 blinker 事件把结果转给 UI bridge，UI 仅负责展示普通 Toast。`TrialResult` MUST 至少包含 `ok`、`summary`、`details`、`exit_code`、`timed_out`、`stdout_path`、`stderr_path`、`trial_id`。Toast 标题 = "试用成功" / "试用失败"（按 `ok` 字段），正文 = `summary` 字段；SC-003 的"试用通过"判定 MUST 同时满足 `exit_code == 0`、stdout 末行 JSON 解析成功、`ok=True`。

  120 秒超时 MUST 调 `Popen.terminate()` 并以 Windows `taskkill /F /T <pid>` 兜底，整树 kill 子孙进程，超时 Toast 标题 = "试用超时"；子进程依赖直接继承父进程 site-packages，不引入临时 venv。子进程**工作目录（cwd）MUST 设为本次试用专属临时目录 `data/trials/<trial_id>/`**（`trial_id` 用与 `recording_id` / `action_id` 同套 UUID 生成函数）；execution runner MUST 在试用启动前自动创建该目录，业务层只负责编排 runner 调用与 blinker 事件，UI MUST NOT 直接创建或写入 `data/trials/`；Trial 退出后**保留 7 天**供事后调试（完整 stdout / stderr 落该目录下 `stdout.log` / `stderr.log`），超期由 `ensure_startup_recovery()` 在启动期扫描 `data/trials/` 下 mtime > 7 天的子目录并 `rmtree` cleanup；隔离 Programmer 代码对项目根 / 录制数据的意外写入，相对路径行为每次都从同样的空目录起点解析，可预测可复现。

  子进程环境变量 MUST 走**白名单继承**：仅传入 `{PATH, SYSTEMROOT, SYSTEMDRIVE, WINDIR, TEMP, TMP, PYTHONPATH, PYTHONHOME, LANG, LC_ALL, USERPROFILE, APPDATA, LOCALAPPDATA, PROGRAMFILES, "PROGRAMFILES(X86)"}`，其余 env vars 一律不传入，含 `API_KEY` / `TOKEN` / `SECRET` / `PASSWORD` / `KEYRING` 子串的变量（大小写不敏感）MUST 被显式过滤，避免 Programmer 生成的代码（可调 `os.environ`）通过 env 通道外泄敏感信息；keyring secret 走 OS 层凭据库而非 env，子进程仍可主动 `import keyring` 读取（如代码确实需要），但默认不通过 env 暴露。Phase 1 MUST NOT 监控/限制子进程 RSS / CPU / 句柄（不引入 Windows Job Object / 资源配额），仅靠 120s 时长 + taskkill 整树兜底；Phase 1 用户 = 开发/内测现场可观察并手动停。

  wrapper MUST 在最外层 `try/except Exception as e` 兜底，把任意异常（含 ImportError / 业务异常 / asyncio 异常）包成 `{"ok": False, "summary": f"{type(e).__name__}: {e}", "details": {"traceback": "<完整 traceback 字符串>"}}` 写 stdout 末行（与正常返回同通道），UI Toast 直接显示 `summary` 字段；不依赖 stderr 与退出码做异常分类。当 stdout 完全没有有效末行 JSON 时（如 wrapper 自身崩溃 / spawn 失败 / 进程被外部 kill），runner 的兜底 `TrialResult` MUST 触发 UI Toast：标题 "试用失败"（与正常异常路径同标题）+ 正文 = stderr **末 5 行**（截断到 ≤ 200 字符）；完整 stdout / stderr MUST 同时落进程日志文件供事后追溯；"试用超时"独立标题路径不混入此兜底

#### UI 层

- **FR-022**: 录制页 UI MUST 提供录制态浮窗（约 100×40 px、右下角默认、用户可拖、`Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint`、显示"🔴 录制中 N 个动作 [停止]"实时计数）；点"开始"后 Exemplar 主窗 MUST 自动 minimize 到任务栏（浮窗保留可见），给用户让出工作区切到目标应用，且 UI MUST 在 minimize 前记录主窗的 geometry 与 window state；MUST NOT 引入倒计时。**hook + ring buffer + UIA 异步队列 + 剪贴板订阅 MUST 在主窗 minimize 完成事件回调后启动**（监听 `QWidget.changeEvent` 中 `windowState() & Qt.WindowMinimized` 跃迁信号或等价 Qt minimize 完成回调），物理上消除"点开始"按钮 click 被 hook 抓为首动作的污染；"立即启动"在此定义为"相对用户视角连续，非物理时刻零延迟"——Qt minimize 在 Windows 上通常 ≤ 100ms 完成，对用户感知无影响；首动作（通常是切窗口/打开应用）由此干净捕获，与"学习捷径"训练目标对齐。录制停止瞬间（浮窗"停止"按钮或 Ctrl+Alt+S 触发后）UI MUST **自动 restore 主窗**到点"开始"前记录的几何与状态（`QWidget.showNormal()` + 几何恢复），随后 FR-024 sanity check 对话框作为 **modal child** 弹在主窗之上，保证从录制态到反馈态视觉过渡连续
- **FR-023**: 系统 MUST 注册全局快捷键 Ctrl+Alt+S 作为停止入口；注册失败时不阻塞录制启动，UI 弹一次 toast 提示用户改用浮窗按钮
- **FR-024**: 录制停止 MUST 立即弹 sanity check 对话框（**modal child** 挂在已 restore 的主窗之上，与 FR-022 主窗自动恢复路径串联），通过 `DesktopRecordingService.get_health_stats(recording_id)` **间接读取** `desktop_recordings.health_stats` JSON 列（不扫 `desktop_actions` 表，UI 不直连 Repository），显示动作总数 / 各类型分布 / 帧总数 / clip 数 / 剪贴板事件 / UIA 命中率 / 录制时长，三按钮"继续分析 / 放弃录制 / 重新录制"。三按钮的状态转移与 UI 跳转 MUST 严格区分：
  - **继续分析** → status=`stopped`，UI 跳 intent 页
  - **放弃录制** → status=`abandoned`（DB 行 + 目录保留），UI 回录制页**不预选 mode**
  - **重新录制** → status=`abandoned`（DB 行 + 目录保留），UI 回录制页且**默认预选桌面 mode**（不立即启动 hook，需用户手动再次点"开始"）

  健康颜色判定 MUST 按以下规则：
  - 红：动作总数 = 0
  - 黄：UIA 命中率 < 50% **或** clip 失败率 > 20%（任一触发；`uia_total = 0` 时 UIA 命中率轴不参与判定——纯键盘场景或 UIA 失败降级；`enable_clip = false` 时 clip 失败率轴不参与判定）
  - 绿：以上条件均不触发
  - 其余指标（帧总数 / 录制时长 / 剪贴板事件 / 各类型分布）仅展示数值，不参与颜色评级
- **FR-025**: 三种录制模式（浏览器 / 桌面 / 扩展触发）MUST 两两互斥，UI 禁用 + 程序拒绝双保险；互斥判定 MUST 基于 in-memory active recorder state（不查 DB），保证崩溃留下的孤儿 `desktop_recordings` 行不会阻塞下次录制启动

#### 配置

- **FR-026**: 系统 MUST 新增配置项 `recording.desktop.enable_clip`（默认开），关闭后只生成多帧 PNG 不生成 mp4 clip
- **FR-026a**: 系统 MUST 新增配置项 `recording.desktop.vision_model`（字符串，无默认值），独立于 `analyze_image` 现行 model 配置；**provider 维度沿用 `analyze_image` 当前 provider 配置**（不新增 `recording.desktop.vision_provider` 字段，provider routing 复用 `analyze_image` factory），仅 model 维度独立；provider API key 仍沿用 `analyze_image` 同套 keyring entry（不引入独立密钥，与 provider 沿用一致）；`vision_model` 未配置时 `analyze_desktop_action` MUST NOT 被注入到桌面 PM / Programmer / Trial 工具集（自然降级，与 CC-005 一致）；前置假设：用户的 `analyze_image` provider 本身就是支持 vision 的 provider，不在 vision-capable provider 列表时 `analyze_desktop_action` 仍按 `vision_model` 字符串调用，失败由 FR-013 现有 `[error: vision_failed]` 路径兜底，MUST NOT 引入启动期 provider 白名单校验。UI 层 MUST 提供两条用户可见提示路径避免静默失败：(a) 设置面板新增"桌面录制"配置区，显式列出 `vision_model` 字段并附说明文本"留空 → 桌面 mode 下 `analyze_desktop_action` 多模态分析工具不可用，PM 仅能基于动作元数据回答问题"；(b) 桌面 mode 下首次进入 intent 页时，若 `vision_model` 缺失 UI MUST 显示一次性 toast"未配置 vision_model，多模态分析功能不可用，可在 设置 → 桌面录制 配置后重启"，自动消失约 **8 秒**（比普通 5s toast 长以确保用户读完），非模态、不阻塞 PM 启动；toast 仅每个 `recording_id` 第一次进 intent 页时显示一次，避免重复打扰；MUST NOT 在桌面 PM prompt 内动态判断 `vision_model` 是否配置（避免 LLM 推理负担与 prompt 双轨变四轨）
- **FR-027**: Phase 1 MUST 不引入录制数据 retention / cleanup / compress / disk quota 配置；用户主动放弃路径走软删除（`desktop_recordings.status='abandoned'`，DB 行 + 目录保留待用户手动清理）；崩溃孤儿不主动清理。此约束不禁止 FR-021a 的 `data/trials/<trial_id>/` 调试目录 7 天 startup cleanup，二者边界不同：录制数据保留，试用临时日志超期清理

### Key Entities

- **DesktopRecordingSession**：一次桌面录制的元数据，对应 `desktop_recordings` 表；含 `recording_id`、`recording_mode='desktop'`、`start_time`、`end_time`、`monitor_index`、`status`（取值 `recording / stopped / abandoned`）、`health_stats`（JSON：`uia_hit` / `uia_total` 仅统计鼠标类动作（mouse_left / mouse_right / mouse_middle / wheel / drag），typing / hotkey 不计入；`clip_success` / `clip_total` / `clipboard_event_count` / `action_type_counts`）等
- **DesktopAction**：录制中的一条动作事件，对应 `desktop_actions` 表；含 `action_id`、`recording_id`、`type`（`mouse_left` / `mouse_right` / `mouse_middle` / `wheel` / `drag` / `typing` / `hotkey`）、`coord_x` / `coord_y`、`monitor_index`（INTEGER，hook 触发瞬间 cursor 所在屏 index，与 FR-006 锁定动作时刻屏幕语义对齐）、`window_title`、`uia_summary`、`clipboard_text` / `clipboard_image_path`、`text_content`（typing 整段文本，超阈值走 large_field 占位）、`timestamp`、`duration_ms`（typing 序列时长 / drag down→up 时长，其他类型可空）、`frame_count`、`has_clip` 等。typing 类型 MUST 一段切片 = 一行（不按字符展开），`coord_x` / `coord_y` / `timestamp` 取序列起点。drag 类型 MUST `coord_x` / `coord_y` / `timestamp` 取 **mouse_up 终点**（"用户拖到了哪"），UIA 查询用 up 坐标，`monitor_index` 取 up 终点 cursor 屏（与 frame 取自 up 屏一致）
- **FrameSet**：一个动作关联的 PNG 多帧（约 45 帧）+ 可选 mp4 clip；落在 `data/recordings/<recording_id>/frames/<action_id>/`、`clips/<action_id>.mp4`；剪贴板图落在 `clipboard/<recording_id>_<event_seq>.png`（按事件序独立命名，与单个 action 行解耦），`desktop_actions.clipboard_image_path` 仅引用动作 hook 触发瞬间最新一张的路径

### Constraints & Compatibility

- **CC-001**: Phase 1 仅支持 Windows（UIA 限制）；macOS / Linux 桌面录制不在本期范围
- **CC-002**: 5 个通用工具 mode dispatch 改造 MUST 守住 9.15 门卫不变量 1-7（浏览器路径 byte-equal、`network_requests.filtered = FALSE` 视图、`recording_data_tools.py` 不直接 import sqlglot 等）；桌面 mode allowlist MUST 严格隔离（仅 `desktop_recordings` + `desktop_actions`，浏览器 5 张表完全屏蔽，反向同理），跨 mode 表访问 MUST 在 sqlglot security gate 被拒
- **CC-003**: PM / Programmer 浏览器 prompt MUST 字节级保留（双轨方案），由 prompt 行为级守卫测试（关键短语断言）兜底防回归
- **CC-004**: Phase 1 不做任何运行期隐私机制（含 UI 告知）；风险已知，installer 公开发版前必须由产品/安全侧对"全局录制 + 无隐私机制 + vision 按需上传"的风险范围签字
- **CC-005**: 数据落地约束——原始录制数据仅落本地（`data/recordings/`）；vision 分析"按需"= Agent 按工具调用按需触发，**不引入任何运行期用户确认**（与 CC-004 一致）；上传范围 = 本次 `analyze_desktop_action` 调用涉及的 ≤ 2 个动作的帧 + 关联剪贴板图（如有），不批量上传；`recording.desktop.vision_model` 未配置时 `analyze_desktop_action` **不注入桌面 PM / Programmer / Trial 工具集**（天然降级，桌面录制 + `list_desktop_actions` + `read_action_clip` 仍可用）
- **CC-006**: 桌面录制 MUST 与浏览器录制、扩展触发录制两两互斥；不支持中途切换或并发
- **CC-007**: 性能软目标（不卡退出标准、不写自动化测试）：CPU 单核 < 15% / 鼠标延迟 < 50ms / 内存 < 500MB / 磁盘 IO 突发 < 50MB/s
- **CC-008**: 单次录制规模 MUST NOT 设任何硬上限（无最长时长 / 最大动作数 / 最大磁盘占用强制停止逻辑）；仅靠 CC-007 软目标 + sanity check 反馈 + 用户主动停止兜底；硬限制策略推迟到 Phase 2

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **UI** (`src/ui/`) — 新增桌面录制浮窗、Ctrl+Alt+S 全局快捷键 + 兜底 toast、sanity check dialog、试用 e 方案三步骤（事前提示 / 完成通知）；调整 `RecordingMixin._on_recording_started` 桌面分支；修正 `recording_widget.py:459` UI default
- [x] **Business** (`src/business/`) — Orchestrator 按 `workflow.recording_mode` 路由 prompt（`dataclasses.replace(PM_CONFIG/PROGRAMMER_CONFIG, system_prompt=...)`）；`execution_strategy` 加 `desktop` 取值；3 桌面专属工具工厂；5 通用工具 mode dispatch；Trial 只编排 preview / runner 调用 / result 事件，不直接启动 subprocess
- [x] **Execution** (`src/execution/`) — 试用 Agent 桌面执行沙箱：`src/execution/desktop_trial_runner.py` 负责子进程启动、cwd/env 白名单、stdout/stderr 落盘、内部 120 秒 kill 兜底（事前提示与跑完通知由 UI 层负责）
- [x] **Data** (`src/data/`) — 新建 `desktop_recordings` / `desktop_actions` 表 schema 与对应 Repository 方法；修正 `RecordingRepository.save_recording_session()` default；修正 `config_models.py:176` default
- [x] **Recording** (`src/recording/`) — 新增 `src/recording/desktop_recorder.py` + `src/recording/desktop/` 子模块（pynput hook / UIA 同步+异步 / 剪贴板 / 多帧 ring buffer / PNG 编码 / mp4 clip 编码）
- [ ] **Utils** (`src/utils/`)

### Agent Impact

- 受影响 Agent：**PM / Programmer / Trial**（Assistant 不受影响）；三者工具集对称——桌面 mode 下任一 Agent 的工具集 = 浏览器 mode 同 Agent 工具集经 mode dispatch + analyze_image↔3 桌面专属等价替换后的结果
- 新工具：`list_desktop_actions` / `analyze_desktop_action` / `read_action_clip`（桌面专属，独立工厂）
- 修改工具：`describe_data` / `query_data` / `execute_code` / `read_recording` / `read_field_chunk` 内部按 `recording_mode` 切表；`query_data_pre_hook` 通过工厂闭包获得 mode；桌面 mode 不注入 `analyze_image`（PM / Programmer / Trial 任一 Agent 的浏览器路径 `analyze_image` 在桌面路径都被替换为 3 桌面专属）
- System prompt 改造：`build_pm_prompt(mode)` / `build_programmer_prompt(mode)`，双轨方案（浏览器 legacy 全文保留；桌面三段：HEADER + DESKTOP_GUIDANCE + FOOTER），由行为级守卫测试兜底防浏览器路径回归
- Orchestrator dispatch：启动 PM / Programmer 前分别用 `dataclasses.replace(PM_CONFIG, system_prompt=build_pm_prompt(workflow.recording_mode))` 与 `dataclasses.replace(PROGRAMMER_CONFIG, system_prompt=build_programmer_prompt(workflow.recording_mode))` 构造临时 AgentConfig

### Data Store Impact

- **SQLite** (`src/data/repos/`)：无变更（业务库不动）
- **DuckDB** (`src/recording/filtering/`)：新增 `desktop_recordings` / `desktop_actions` 表；5 通用工具 mode dispatch（浏览器路径门卫不变量 1-7 不退化）；`read_field_chunk` / `read_recording` stable locator 桌面侧扩展（`desktop_actions.action_id` 等）；`describe_data` / `query_data` 桌面 allowlist
- **Config** (`src/data/unified_config.py`)：新增 `recording.desktop.enable_clip`（默认开）；新增 `recording.desktop.vision_model`（字符串，无默认值，独立于 `analyze_image` 现行 model）；修正 `default_recording_mode` UI/dataclass default 错配
- **Secrets** (keyring)：vision LLM 提供方 API key 走现有 `analyze_image` 同套 keyring entry（不分裂密钥），仅 model 维度独立

### Event Impact

- 跨模块通知 MUST 走 `src/utils/events.py` 的 blinker 事件；本期新增/复用事件包括：`recording_started` / `recording_stopped` / `desktop_action_count_changed` / `desktop_recorder_start_failed` / `desktop_recording_degraded` / `desktop_syntax_gate_retry_failed` / `desktop_trial_preview_ready` / `desktop_trial_finished`
- UI 层通过本地 Qt bridge 把 blinker 事件转回 UI 线程后更新浮窗、弹 toast、弹 sanity check；业务 / recording / Trial 层不直接 import UI widget，也不直接 emit 跨模块 Qt signal

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 5 个标准场景全部录制成功。"录制成功"客观判定 = `health_stats.action_type_counts` 之和 > 0；US4 完成后该状态在 sanity check UI 上表现为颜色非红。5 个标准场景最小任务骨架（quickstart 复用，不强制具体动作数与类型）：
  - **记事本**：打开 notepad → 输入一段文本（约 10-30 字符） → Ctrl+S 另存为桌面 `.txt`
  - **PPT**：打开任一现有 .pptx → 切换到第 2 页 → 在标题框输入文字 → Ctrl+S
  - **微信发消息**：从托盘打开微信 → 选一个联系人 → 在输入框输入消息 → 按 Enter / 点发送
  - **资源管理器复制**：打开任一文件夹 → 选中一个文件 → Ctrl+C → 切换到桌面 → Ctrl+V
  - **启动 VSCode 并打开桌面文件**：从开始菜单或快捷方式启动 VSCode → 通过 File → Open File 选桌面任一已有文件打开
- **SC-002**: 5 个标准场景 Agent 都能进入 intent 页给出可执行方案。"可执行方案"客观判定 = PM Agent 完成 intent 输出（即 PM 进入 talk_to_user 终态）+ Programmer Agent 产出的 `async def execute() -> dict` 代码能通过 `ast.parse` 语法解析；不要求实际运行成功（运行成功由 SC-003 单独度量）。SC-002 / SC-003 共同构成"5/5 出方案 → 3/5 跑通"漏斗。SC-002 整体作为 5 场景 manual e2e 漏斗判定记录（与 SC-001 / SC-003 / SC-004 / SC-007 同形），**不进自动化端到端测试**；其中 `ast.parse` 校验 MUST 在 Orchestrator 把 Programmer 输出代码交给 Trial 子进程前执行（syntax gate，守住语法错不进 Trial），并由独立单元测试覆盖（fixture：合法代码通过 / 故意语法错被拦截）
- **SC-003**: 5 个标准场景中至少 3/5 试用通过——"通过"的客观判定：子进程退出码 0 + stdout 末行 JSON 解析成功 + `ok=True`
- **SC-004**: 5 个标准场景中至少 3/5 走捷径。"走捷径"的客观判定规则：生成代码中任一命中即算捷径——调用 `subprocess` / `os.startfile` / `webbrowser` / Win32 协议 URL（如 `wechat:` / `mailto:`，但排除 Windows 盘符路径如 `C:\foo`） / `pywin32` 高级 API（限定 `win32api` / `win32gui` / `win32com` / `win32process` / `win32service` / `win32clipboard` / `pythoncom` 等模块 import 或调用） / `pywinauto` 控件级 API；纯 `pyautogui` 坐标点击循环不算。判定流程：先按规则机械判定，再由人工 review 做 spot check 复核（避免规则误伤合理坐标方案）
- **SC-005**: 浏览器路径门卫不变量 1-7 在 mode dispatch 改造前后 100% 通过（5 通用工具 canonical JSON baseline 字节级 byte-equal）
- **SC-006**: 浏览器 PM / Programmer prompt 行为级守卫测试在 prompt 改造前后 100% 通过（关键短语断言不退化）
- **SC-007**: 5 场景 manual e2e 期间用户主观判断"不卡"（鼠标响应延迟、整体流畅度无感知卡顿）
- **SC-008**: installer 公开发版前完成产品/安全侧对"全局录制 + 无隐私机制 + vision 按需上传"的隐私风险签字（Phase 1 默认仅供开发/内测）

## Assumptions

- 用户在 Windows 10/11 上使用，UIA 服务可用；macOS / Linux 在 Phase 1 范围外
- 用户已配置 vision LLM 提供方（OpenAI / Anthropic / 本地多模态 三选一），provider API key 走 keyring 与 `analyze_image` 同套（不分裂密钥）；vision-capable model 通过新增的 `recording.desktop.vision_model` 字段独立指定，未配置则 `analyze_desktop_action` 工具不注入（自然降级）
- 主屏单显示器或多显示器都允许，但 Phase 1 只录鼠标所在屏；多显示器跨屏切换走 9.12 #8
- 桌面录制使用方式遵循 9.10 退出标准的 5 个标准场景为典型用例；Phase 2 再覆盖 Electron / Java Swing 等 UIA 弱场景
- 主仓库现有浏览器录制路径（`recording_sessions` / `actions` / `network_requests` / `sibling_snapshots` / `recording_screenshots` 5 张表 + `analyze_image` 工具 + PM/Programmer legacy prompt）保持不变，桌面分支不修改浏览器原有契约
- opencv-python 作为 mp4 clip 编码库（自带 ffmpeg、零部署），通过 mexemplar installer 分发（installer 已含 chromium 200MB+，多 70MB 不显著）
- intent 页 UI 播放器 Phase 1 不接通；clip 文件 Phase 1 落盘但用户暂时看不到，等 Phase 2 接通
- vision LLM 调用结果缓存推 Phase 2；同 `action_ids` + 同 `question` 在 Phase 1 重复上传不优化
- vision LLM 调用 token / 上传成本 Phase 1 由用户自承担（开发/内测）；不设单次会话或单 recording 的累计调用次数硬上限，仅靠 INFO 日志做事后审计；Phase 2 视审计数据再决定是否引入 quota / rate limit
- 试用子进程 Phase 1 仅靠 120s 时长 + taskkill 整树兜底；不监控/限制 RSS / CPU / 句柄数；用户在本机现场可观察并手动停，OS page file 兜底防止系统立即崩
- `desktop_recordings` / `desktop_actions` Phase 1 不引入 `schema_version` 列；Phase 2 加列时旧数据视为 obsolete 由用户手动清理而非强行向前兼容；DuckDB `ALTER TABLE ADD COLUMN` 默认 NULL 满足 Phase 2 渐进加列；真正需要 schema 演进时引入数据库 migration 工具

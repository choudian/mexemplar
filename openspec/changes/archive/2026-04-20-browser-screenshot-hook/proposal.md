## Why

浏览器录制模式下截图链路完全缺失——`analyze_image` agent 工具按 BLOB bytes 读取截图，但 DuckDB 的 `actions.screenshot_before/after` 列实际为空 `TEXT`，无法为 agent 提供视觉上下文。此外 queue 目录路径在 `BrowserRecorder` 和 `RecordingRecovery` 间不一致，`EXEMPLAR_DATA_DIR` 环境变量下 Recovery 会指向错误位置。

## What Changes

- 新增 `BrowserScreenshotHook` 模块：用 Windows 原生输入钩子（pynput）在录制期间并行采集鼠标左键点击和回车键的前后截图，通过 mss 截屏 + HWND 裁剪浏览器窗口，JPEG 编码后写入独立 queue file。内部采用帧预采样架构：`_FrameSampler` 后台线程以 100ms 间隔持续采样浏览器窗口画面到 `_FrameRingBuffer`（64 帧环形缓冲，约 6.4s），`_ScreenCapturer` 处理任务时优先从缓冲区按时间戳匹配帧，仅在缓冲区未命中时回退到实时截图
- 新增 `recording_screenshots` DuckDB 表：截图作为独立时序流存储，不绑定到具体 action 行；`analyze_image` 按时间窗（而非 sequence_number）查询邻近截图
- 新增 `queue_paths.py` helper：统一 actions / screenshots queue 文件路径，修复 `RecordingRecovery` 硬编码路径 bug
- 新增 `resolve_browser_pid()`：基于 psutil + 扩展 bundle path 解析 Playwright 启动的 Chromium 主进程 PID
- 改造 `_analyze_image` 工具：从按 `sequence_number` 查 `actions.screenshot_before/after` 改为按 `action.timestamp` + 时间窗查 `recording_screenshots` 表
- 修改 `BrowserRecorder` stop 顺序：新增 `_wait_for_stop_drain` 和 `_last_browser_action_ts` 埋点，确保最后一拍晚到的 action 不丢失
- 修改 `RecordingRecovery` startup scan：从"仅 WAL 异常时扫描 queue 目录"提升为"启动时总是扫描"，并清理孤儿 screenshots queue
- 应用入口新增 DPI awareness 设置：在 `QApplication` 构造前设置 Per-Monitor V2

## Capabilities

### New Capabilities
- `screenshot-hook`: Windows 原生输入钩子并行截图采集（pynput 钩子 + 帧预采样环形缓冲 + mss 截屏 + HWND 裁剪 + JPEG 编码 + 独立 queue file）
- `screenshot-storage`: 截图时序表存储与查询（`recording_screenshots` DuckDB 表 + `analyze_image` 时间窗查询改造）
- `browser-pid-resolution`: Playwright Chromium 进程 PID 解析（psutil + bundle path 匹配 + `--type=` 子进程过滤）

### Modified Capabilities
<!-- 无现有 spec 需修改 -->

## Impact

- **新增文件**：`browser_screenshot_hook.py`、`queue_paths.py`、`screenshot_queue_parser.py`
- **修改文件**：`browser_recorder.py`、`playwright_recording_driver.py`、`duckdb_recording_persister.py`、`duckdb_manager.py`、`recording_repository.py`、`recording_data_tools.py`、`recording_recovery.py`、`main.py`
- **DuckDB Schema**：新增 `recording_screenshots` 表 + `recording_screenshot_id_seq` 序列；`actions` 表不变
- **依赖**：无新依赖（pynput、mss、Pillow、psutil 已在项目中）
- **平台**：截图功能仅 Windows 启用；非 Windows 平台 hook.start() 返回 False，不影响录制主路径
- **应用入口**：DPI awareness 设置需在 `main.py` 中 `QApplication` 构造前完成

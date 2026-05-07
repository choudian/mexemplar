# Contract: UI 信号与状态机

## 1. 录制态浮窗（FR-022）

### 实例化时机

- 用户点录制页"开始"按钮 → UI 触发主窗 `showMinimized()` → 监听 `changeEvent` minimize 完成 → 此时实例化浮窗（与 hook 启动同时机）；
- 浮窗为独立 `QWidget` with `Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint`，不挂在主窗下（主窗 minimize 时浮窗保留可见）。

### 几何与外观

- 默认右下角，约 100×40 px；
- 用户可拖（实现 `mousePressEvent` / `mouseMoveEvent` / `mouseReleaseEvent` 监听）；
- 显示文本：`"🔴 录制中 N 个动作 [停止]"`，N 为当前 `desktop_actions` 行数（typing 序列已切片为单行计入）；
- 实时刷新：Recorder 发 `desktop_action_count_changed` blinker 事件 → UI 本地 bridge 切回 UI 线程 → 浮窗 slot 更新 N 显示。

### 停止按钮

- 浮窗内 `QPushButton` "停止" → 点击 emit UI 内部 signal `stopRequested` → `recording_widget` slot 调用 `DesktopRecordingService.stop(recording_id)` 触发停止流程；
- 与 Ctrl+Alt+S 全局热键双轨入口（FR-023）。

## 2. 主窗 minimize / restore 时机

### Minimize 时机

```python
# src/ui/widgets/recording_widget.py

def _on_start_button_clicked(self):
    if self._selected_mode != RecordingMode.DESKTOP:
        return self._start_browser_or_extension_recording()

    # 桌面 mode 路径
    self._main_window_geometry_before = self._main_window.saveGeometry()    # 记录几何
    self._main_window_state_before = self._main_window.windowState()
    self._main_window.showMinimized()    # 触发 changeEvent

    # 监听 changeEvent 中的 minimize 完成跃迁
    self._main_window.installEventFilter(self._minimize_listener)
```

```python
# 主窗 changeEvent 监听器
def eventFilter(self, watched, event):
    if event.type() == QEvent.WindowStateChange:
        if watched.windowState() & Qt.WindowState.WindowMinimized:
            self._main_window.removeEventFilter(self)
            self.recordingWidget._on_main_window_minimized_for_desktop_recording()
    return False
```

### 启动 hook 时机（spec round 7 第 3 题 + FR-022）

```python
def _on_main_window_minimized_for_desktop_recording(self):
    # 此时主窗 minimize 完成，"点开始" click 已被 Qt 消费完毕
    self._desktop_recording_service.start_after_minimize(self._recording_id)
    # business 层内部创建并启动 DesktopRecorder：pynput hook + ring buffer + UIA 异步队列 + 剪贴板订阅
    self._floating_widget = RecordingFloatingWidget(...)
    self._floating_widget.show()
```

### Restore 时机

- 用户点浮窗"停止" 或 按 Ctrl+Alt+S → Recorder 发 `recording_stopped` blinker 事件；
- UI slot 收到信号：
  ```python
  def _on_recording_stopped(self):
      self._floating_widget.hide()
      self._main_window.showNormal()    # 恢复 normal state
      self._main_window.restoreGeometry(self._main_window_geometry_before)
      self._main_window.setWindowState(self._main_window_state_before)
      # sanity check 对话框作为 modal child
      dialog = DesktopSanityCheckDialog(parent=self._main_window, recording_id=self._recording_id)
      dialog.exec()
  ```

## 3. Sanity check 对话框（FR-024）

### 数据来源

- **直读** `desktop_recordings.health_stats` JSON 列；
- **不扫** `desktop_actions` 表（FR-024 + spec round 1 第 1 题）；
- 通过 `DesktopRecordingService.get_health_stats(recording_id) -> HealthStats` 读取（UI 不直访 Repository）。

### 显示元素

```text
┌─ 录制健康反馈 ─────────────────────────────────────┐
│  ⚫ 状态：绿  (颜色判定见下文)                      │
│                                                     │
│  动作总数：27                                       │
│  各类型分布：                                       │
│    mouse_left: 14                                   │
│    wheel: 2                                         │
│    drag: 2                                          │
│    typing: 5                                        │
│    hotkey: 4                                        │
│    mouse_right: 0                                   │
│    mouse_middle: 0                                  │
│  帧总数：1215                                       │
│  clip 数：14                                        │
│  剪贴板事件：3                                      │
│  UIA 命中率：12/18 = 66.7%                          │
│  录制时长：47.3 秒                                  │
│                                                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐    │
│  │ 继续分析    │  │ 放弃录制    │  │ 重新录制    │    │
│  └────────────┘  └────────────┘  └────────────┘    │
└─────────────────────────────────────────────────────┘
```

### 颜色判定

```python
def determine_health_color(stats: HealthStats, enable_clip: bool) -> str:
    action_total = sum(stats.action_type_counts.values())
    if action_total == 0:
        return "red"

    # 黄判定：UIA / clip 任一触发
    yellow = False
    if stats.uia_total > 0 and stats.uia_hit / stats.uia_total < 0.5:
        yellow = True
    if enable_clip and stats.clip_total > 0:
        clip_failure_rate = (stats.clip_total - stats.clip_success) / stats.clip_total
        if clip_failure_rate > 0.2:
            yellow = True

    return "yellow" if yellow else "green"
```

**边界情况**：
- `uia_total = 0`：UIA 命中率轴不参与判定（纯键盘场景或 UIA 失败降级，spec round 2 第 1 题）；
- `enable_clip = false`：clip 失败率轴不参与判定（spec round 5 第 6 题）；
- 帧总数 / 录制时长 / 剪贴板事件 / 各类型分布 仅展示数值不参与颜色评级。

### 三按钮状态转移

| 按钮 | `desktop_recordings.status` 终态 | 目录与 DB 行 | UI 跳转 |
|---|---|---|---|
| 继续分析 | `stopped` | 保留 | 跳 intent 页（PM Agent 启动） |
| 放弃录制 | `abandoned` | 均保留待用户手动清理 | 回录制页 + **不预选 mode** |
| 重新录制 | `abandoned` | 均保留待用户手动清理 | 回录制页 + **默认预选桌面 mode**（不立即启动 hook） |

**约束**：
- "放弃录制" 与 "重新录制" status 终态完全一致（避免引入第四态，spec round 6 第 1 题）；
- 区别仅在 UI 跳转目标的 mode 预选状态。

## 4. 试用流程 UI（FR-021）

```text
PM Agent 完成 intent → Programmer Agent 出码 → ast.parse syntax gate
                                                       ↓
                                              [代码合法]
                                                       ↓
                              用户在 intent 页点 "试用" 按钮
                                                       ↓
                             ┌─ 事前提示对话框（modal child） ─┐
                             │ 文案 + 代码预览 + 高危 API 标签 │
                             │ ┌──────┐  ┌──────┐              │
                             │ │ 开始 │  │ 取消 │              │
                             │ └──────┘  └──────┘              │
                             └─────────────────────────────────┘
                                ↓ 开始             ↓ 取消
                                ↓                  └→ 回 intent 页
                                ↓
                       Trial 子进程启动 + 跑期间无遮挡（不弹任何模态）
                                ↓
                       子进程退出 / 120s kill
                                ↓
                       execution runner 解析 stdout/stderr 为 TrialResult
                                ↓
                       普通 Toast（5s 自动消失，非模态）
                            标题 = "试用成功" / "试用失败" / "试用超时"
                            正文 = summary 字段 / stderr 末 5 行 / "代码执行超过 120 秒已被终止"
```

**约束**：
- 跑期间**不弹任何模态遮挡焦点**（FR-021）；
- Toast **不写入对话历史**；
- Toast 不接入 Windows 系统原生通知中心。

## 5. 设置面板"桌面录制"配置区（FR-026a）

```text
设置 → 桌面录制
├─ Vision Model: [输入框                              ]
│   留空 → 桌面 mode 下 analyze_desktop_action 多模态分析工具不可用，
│         PM 仅能基于动作元数据回答问题
└─ Enable Clip:  [✓] 录制 mp4 视频片段
    关闭后只生成多帧 PNG，不生成 mp4 clip
```

### vision_model 缺失提示路径

- 桌面 mode 下首次进入 intent 页时，若 `vision_model` 缺失：
  - UI 显示一次性 toast，自动消失约 **8 秒**（比普通 5s toast 长，确保用户读完）；
  - 文案："未配置 vision_model，多模态分析功能不可用，可在 设置 → 桌面录制 配置后重启"；
  - 非模态、不阻塞 PM 启动；
  - 仅每个 `recording_id` 第一次进 intent 页时显示一次（`_vision_model_warning_shown_for_recordings: set[str]` 内存集合记录）。

## 6. 跨模块事件拓扑（blinker → UI bridge）

```text
Recorder
  ├─ desktop_action_count_changed(recording_id, count)     → UI bridge → 浮窗 slot
  ├─ recording_stopped(RecordingEventData)                  → UI bridge → recording_widget._on_recording_stopped
  ├─ desktop_recorder_start_failed(reason)                  → UI bridge → 弹错对话框（仅 hook 注册失败等阻塞启动）
  └─ desktop_recording_degraded(reason, message)            → UI bridge → 一次性 toast（UIA COM / 剪贴板订阅 / Ctrl+Alt+S 降级）

Orchestrator
  ├─ requirement_confirmed / code_completed（既有事件）       → UI bridge → intent 页跳转 / 试用按钮启用
  └─ desktop_syntax_gate_retry_failed(msg, lineno)           → UI bridge → Toast "Programmer 输出代码持续语法错误"

DesktopTrialRunner
  ├─ desktop_trial_preview_ready(code, high_risk_apis)       → UI bridge → 事前提示对话框
  └─ desktop_trial_finished(TrialResult result)              → UI bridge → 普通 Toast（含超时路径）
```

**约束**（与 Constitution Principle I 对齐）：
- 业务 / recording / Trial 层 → UI 的跨模块通知 MUST 通过 `src/utils/events.py` blinker 事件；
- UI bridge 是 UI 层内部适配器，负责订阅 blinker 并用 Qt signal / `QTimer.singleShot(0, ...)` 等方式切回 UI 线程；
- UI 内部 widget 之间（如浮窗按钮 → recording_widget）可使用 Qt signal，但不能替代跨模块 blinker 事件；
- UI → 业务层通过 Service 方法调用（如 `DesktopRecordingService.stop(recording_id)`）；
- UI 不直接调 Repository（FR-024 sanity check 通过 `DesktopRecordingService.get_health_stats()`）。

## 7. 测试切面

| 测试 | 验证 |
|---|---|
| `test_floating_widget_count_updates` | Recorder 发 `desktop_action_count_changed(count=5)` → UI bridge 后浮窗显示 "🔴 录制中 5 个动作 [停止]" |
| `test_main_window_minimize_geometry_restore` | start 前 geometry → minimize → restore 后几何还原 |
| `test_hook_starts_after_minimize_complete` | 记录 hook start 时刻 vs minimize completed 时刻：hook 时刻 ≥ minimize 时刻 |
| `test_sanity_check_color_red` | health_stats action_type_counts 全 0 → 红 |
| `test_sanity_check_color_yellow_uia` | uia_hit=4, uia_total=10（40% < 50%）→ 黄 |
| `test_sanity_check_color_yellow_clip` | clip_success=10, clip_total=14（28.5% > 20% 失败率）→ 黄 |
| `test_sanity_check_color_green` | uia_hit=15, uia_total=18, clip_success=14, clip_total=14, action_total=27 → 绿 |
| `test_sanity_check_uia_skip_when_zero` | uia_total=0 + clip_success=10/10 + action_total=5 → 绿（UIA 轴跳过） |
| `test_three_button_status_transition` | 点继续分析 → status=stopped；放弃 → abandoned；重新 → abandoned + 桌面 mode 预选 |
| `test_vision_model_missing_toast_once_per_recording` | 同一 recording_id 多次进 intent 页只显示一次 toast；不同 recording_id 各显示一次 |
| `test_high_risk_api_detection_in_preview` | 代码含 `subprocess.run([...])` → 事前对话框含 "subprocess" 标签 |

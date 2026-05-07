# Quickstart: 桌面录制 Phase 1

> 5 个标准场景的 manual e2e 验收路径。本文件固化执行步骤与漏斗判定，是 SC-001 / SC-002 / SC-003 / SC-004 / SC-007 的唯一退出标准依据。

## 前置条件

- Windows 10/11；
- 项目已 `pip install -e .` 安装依赖（含 `pynput` / `comtypes` / `mss` / `opencv-python` / `Pillow` / DuckDB / PyQt6 等）；
- `data/recordings/` 与 `data/trials/` 目录已创建（`ensure_startup_recovery()` 自动创建）；
- 配置：
  - `recording.desktop.enable_clip = true`（默认）；
  - `recording.desktop.vision_model = "<your-vision-model>"`（必配，否则 `analyze_desktop_action` 不注入桌面 PM/Programmer/Trial 工具集）；
  - `analyze_image` provider API key 已落 keyring（vision provider 沿用同套）。

---

## 5 标准场景骨架

### Scenario 1：记事本

**任务**：打开 notepad → 输入一段文本（约 10-30 字符） → Ctrl+S 另存为桌面 `.txt`。

**步骤**：

1. 启动 mexemplar GUI；
2. 录制页选"桌面"模式 → 点"开始"；
3. 主窗自动 minimize、浮窗在右下角出现（"🔴 录制中 0 个动作 [停止]"）；
4. 用户操作：
   - Win+R / 开始菜单 / 桌面图标启动 notepad（任意方式）；
   - 在 notepad 输入框输入"hello desktop recording"；
   - Ctrl+S 弹"另存为"对话框；
   - 切到桌面 → 输入文件名 `test.txt` → 点"保存"；
5. 用户点浮窗"停止"或按 Ctrl+Alt+S；
6. 主窗 restore，sanity check 对话框弹出。

**SC-001 录制成功判定**：`health_stats.action_type_counts` 之和 > 0；US4 完成后该状态在 sanity check UI 上表现为颜色非红。

---

### Scenario 2：PPT

**任务**：打开任一现有 .pptx → 切换到第 2 页 → 在标题框输入文字 → Ctrl+S。

**前置**：桌面已有任一 `.pptx` 文件（至少 2 页）。

**步骤**：

1. 录制页选"桌面"模式 → 点"开始"；
2. 用户操作：
   - 双击桌面 `.pptx` 启动 PowerPoint；
   - 等待加载完成；
   - 左侧缩略图区域点击第 2 页缩略图（或 PageDown 切到第 2 页）；
   - 点击标题文本框 → 输入"hello slide 2"；
   - Ctrl+S 保存；
3. 用户停止录制 → sanity check。

---

### Scenario 3：微信发消息

**任务**：从托盘打开微信 → 选一个联系人 → 在输入框输入消息 → 按 Enter / 点发送。

**前置**：微信已登录、有可发消息的联系人（自己/文件传输助手即可）。

**步骤**：

1. 录制页选"桌面"模式 → 点"开始"；
2. 用户操作：
   - 系统托盘点击微信图标 → 主窗口打开；
   - 左侧联系人列表点击"文件传输助手"（或任一联系人）；
   - 输入框输入"hello wechat"；
   - Enter 发送；
3. 停止录制 → sanity check。

---

### Scenario 4：资源管理器复制

**任务**：打开任一文件夹 → 选中一个文件 → Ctrl+C → 切换到桌面 → Ctrl+V。

**前置**：桌面有任一非桌面快捷方式的文件（如 `test.txt` 或前一场景的产物）。

**步骤**：

1. 录制页选"桌面"模式 → 点"开始"；
2. 用户操作：
   - Win+E 打开资源管理器（或任一其他方式）；
   - 导航到 Documents 或任一含文件的目录；
   - 单击选中一个文件；
   - Ctrl+C；
   - 切到桌面（Win+D 或关闭资源管理器）；
   - 桌面空白处右键 → "粘贴"（或 Ctrl+V）；
3. 停止录制 → sanity check。

**特别关注**：
- `health_stats.clipboard_event_count >= 1`（Ctrl+C 触发）；
- `desktop_actions` 中应有 typing / hotkey 类的 Ctrl+C 与 Ctrl+V 行；
- 剪贴板路径栏（如复制的是图片）会落 `clipboard/<recording_id>_<event_seq>.png`。

---

### Scenario 5：启动 VSCode 并打开桌面文件

**任务**：从开始菜单或快捷方式启动 VSCode → 通过 File → Open File 选桌面任一已有文件打开。

**前置**：VSCode 已安装、桌面有任一文件。

**步骤**：

1. 录制页选"桌面"模式 → 点"开始"；
2. 用户操作：
   - Win 键 → 输入"vscode" → Enter（或桌面快捷方式双击）；
   - 等待 VSCode 启动；
   - 顶部菜单 File → Open File...；
   - 文件对话框导航到桌面 → 选 `test.txt` → 点"打开"；
3. 停止录制 → sanity check。

---

## 漏斗判定（5 场景共通）

### 阶段 1：录制成功（SC-001）

每场景 `health_stats.action_type_counts` 之和 > 0 即过；US4 完成后可用 sanity check 颜色非红作为 UI 表现复核。

```text
SC-001 通过 = 5/5 场景 `health_stats.action_type_counts` 之和 > 0
```

### 阶段 2：Agent 给出可执行方案（SC-002）

每场景在 sanity check 点"继续分析" → intent 页 → 用户问 PM "用户做了什么？/ 怎么自动化这段操作？" → PM 完成 intent 输出 + Programmer 出码 + `ast.parse` 通过。

```text
SC-002 通过 = 5/5 场景出方案
判定 = (PM 进入 talk_to_user 终态) AND (Programmer 输出代码 ast.parse 通过)
```

**注意**：
- `ast.parse` 通过由 Orchestrator syntax gate 自动判定（FR-017a，3 次重试机会）；
- 不要求实际运行成功（运行成功由 SC-003 单独度量）。

### 阶段 3：试用通过（SC-003）

每场景点"试用"→ 事前提示对话框 → 点"开始"→ Trial 子进程执行。

```text
SC-003 通过 = ≥ 3/5 场景试用通过
判定 = 子进程退出码 0 + stdout 末行 JSON 解析成功 + ok=True
```

**Toast 反馈**：
- "试用成功" → ok=True；
- "试用失败" → ok=False（含 wrapper 异常包装路径）；
- "试用超时" → 120s kill 触发；

### 阶段 4：找捷径（SC-004）

每场景 review Programmer 生成的代码。

```text
SC-004 通过 = ≥ 3/5 场景走捷径
判定（机械规则）= 代码任一命中即算捷径：
  - subprocess
  - os.startfile
  - webbrowser
  - Win32 协议 URL（如 wechat: / mailto:；排除 Windows 盘符路径如 C:\foo）
  - pywin32 高级 API（限定 win32api / win32gui / win32com / win32process / win32service / win32clipboard / pythoncom 等模块）
  - pywinauto 控件级 API
反例：纯 pyautogui 坐标点击循环不算捷径
最终 = 机械规则通过 + 人工 spot check 复核
```

### 阶段 5：性能主观判断（SC-007）

整个 5 场景 manual e2e 期间用户主观判断"不卡"，并在验收记录里写明是否观察到 CC-007 软目标明显偏离（CPU 单核 < 15% / 鼠标延迟 < 50ms / 内存 < 500MB / 磁盘 IO 突发 < 50MB/s）。

```text
SC-007 通过 = 用户主观判断 5 场景全程鼠标响应延迟、整体流畅度无感知卡顿；
若观察到明显偏离 CC-007 软目标，记录场景、现象和大致数值，不作为自动化门禁。
```

不需要自动化测试，不要求精确压测；只要求 manual e2e 记录主观结论和明显异常。

---

## 漏斗汇总表

| 场景 | SC-001 录制 | SC-002 出方案 | SC-003 试用 | SC-004 捷径 |
|---|---|---|---|---|
| 1 记事本 | ☐ | ☐ | ☐ | ☐ |
| 2 PPT | ☐ | ☐ | ☐ | ☐ |
| 3 微信 | ☐ | ☐ | ☐ | ☐ |
| 4 资源管理器 | ☐ | ☐ | ☐ | ☐ |
| 5 VSCode | ☐ | ☐ | ☐ | ☐ |
| **总计** | **5/5** | **5/5** | **≥ 3/5** | **≥ 3/5** |

**Phase 1 退出标准**：上表全部满足 + SC-007 主观判断不卡 + SC-005（浏览器路径门卫不变量）+ SC-006（浏览器 prompt 守卫断言）+ SC-008（installer 公开发版前产品/安全签字）。

---

## 故障排查

### 录制启动失败

| 现象 | 可能原因 | 处理 |
|---|---|---|
| pynput hook 注册失败弹错对话框 | 权限不足 / 防病毒拦截 / pynput 版本不兼容 | 以管理员权限启动 / 加入防病毒白名单 |
| UIA COM 初始化失败 toast | UIA 服务未启动 | 控制面板启动 UI Automation Service |
| 剪贴板订阅失败 toast | 剪贴板服务异常 | 重启 Windows Clipboard Service |
| Ctrl+Alt+S 注册失败 toast | OBS / 截图工具占用 | 改用浮窗"停止"按钮（不阻塞录制） |

### 录制中崩溃

- Phase 1 不做任何 crashed 处理；
- 重启进程后录制不会自动恢复；
- 孤儿目录用户手动 `rm -rf data/recordings/<recording_id>/`；
- DB 行用户手动 DELETE：`duckdb data/recordings.duckdb -c "DELETE FROM desktop_recordings WHERE recording_id = '<id>'; DELETE FROM desktop_actions WHERE recording_id = '<id>';"`。

### Trial 子进程异常

| 现象 | 可能原因 | 处理 |
|---|---|---|
| Toast "试用失败" + summary "ImportError: ..." | Programmer 代码 import 了未安装的库 | 装该库后重试 |
| Toast "试用失败" + summary "ValueError: ..." | execute() 业务异常 | review `data/trials/<trial_id>/stderr.log` 看 traceback |
| Toast "试用超时" | execute() 跑超过 120 秒 | review 代码是否有死循环 / 阻塞 IO |
| Toast "试用失败" + 正文 stderr 末 5 行 | wrapper 自身崩溃 | review `data/trials/<trial_id>/stdout.log` 与 stderr.log |

### 多模态分析失败

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `analyze_desktop_action` 工具不可用（PM 工具集不含） | `recording.desktop.vision_model` 未配置 | 设置面板配置 vision_model 后重启 |
| 返回 `[error: vision_unauthorized]` | API key 失效 / 401 / 403 | 检查 keyring 中 `analyze_image` 同套 entry |
| 返回 `[error: vision_timeout]` | 网络慢 / vision 服务慢 | 重试或换更快的 model |
| 返回 `[error: vision_failed]` | 其他失败（5xx / parse 异常） | 查 INFO 日志看具体异常 |

---

## 调试工具

### 看 Recording 数据

```bash
duckdb data/recordings.duckdb -c "SELECT * FROM desktop_recordings WHERE recording_id = '<id>';"
duckdb data/recordings.duckdb -c "SELECT action_id, type, window_title, frame_count FROM desktop_actions WHERE recording_id = '<id>' ORDER BY timestamp LIMIT 50;"
```

### 看 health_stats

```bash
duckdb data/recordings.duckdb -c "SELECT health_stats FROM desktop_recordings WHERE recording_id = '<id>';"
```

### 看 Trial stdout/stderr

```bash
cat data/trials/<trial_id>/stdout.log
cat data/trials/<trial_id>/stderr.log
```

### 看 vision 调用 INFO 日志

```bash
grep "analyze_desktop_action" logs/mexemplar.log
```

---

## Cleanup

### 手动清理录制数据

```bash
# 删除单次录制
rm -rf data/recordings/<recording_id>/
duckdb data/recordings.duckdb -c "DELETE FROM desktop_recordings WHERE recording_id = '<id>'; DELETE FROM desktop_actions WHERE recording_id = '<id>';"

# 批量删除 abandoned 录制
duckdb data/recordings.duckdb -c "SELECT recording_id FROM desktop_recordings WHERE status='abandoned';" | while read id; do rm -rf "data/recordings/$id/"; done
duckdb data/recordings.duckdb -c "DELETE FROM desktop_recordings WHERE status='abandoned'; DELETE FROM desktop_actions WHERE recording_id NOT IN (SELECT recording_id FROM desktop_recordings);"
```

### Trial 自动 cleanup

- 启动期 `ensure_startup_recovery()` 扫描 `data/trials/` 子目录，mtime > 7 天的 `rmtree`；
- 用户无需手动操作。

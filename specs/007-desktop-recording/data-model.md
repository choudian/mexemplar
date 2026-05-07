# Phase 1 Data Model: 桌面录制 Phase 1

> 本文件锁定 DuckDB 表 schema、JSON shape、目录约定与 large_field 占位规则。所有字段语义溯源 spec FR / Clarifications。

---

## 1. DuckDB 表

存放位置：`data/recordings.duckdb`（既有，与浏览器录制 5 张表共库）。

### 1.1 `desktop_recordings`

> 一次桌面录制的元数据汇总。

| 列 | 类型 | 约束 | 来源 / 语义 |
|---|---|---|---|
| `recording_id` | VARCHAR | PRIMARY KEY | 复用 `recording_sessions.recording_id` 同套 UUID 生成函数（FR-008）；与 `recording_sessions` 共用主键命名空间 |
| `recording_mode` | VARCHAR | NOT NULL DEFAULT `'desktop'` | 固定 `'desktop'`；`RecordingRepository.get_recording_mode(recording_id)` 会把本表作为桌面录制的 mode 来源，不要求镜像写入 `recording_sessions` |
| `start_time` | TIMESTAMP | NOT NULL | 录制启动时刻（hook 已启动后第一帧落 ring buffer 的 monotonic 时间转 UTC） |
| `end_time` | TIMESTAMP | NULL | 录制停止时刻；`status='recording'` 时为 NULL |
| `monitor_index` | INTEGER | NOT NULL | 录制启动时主屏 index（cursor 所在屏，0-based）；跨屏录制下与 `desktop_actions.monitor_index` 可能不一致，仅作"启动主屏"参考（spec round 7 第 1 题） |
| `status` | VARCHAR | NOT NULL CHECK (status IN ('recording', 'stopped', 'abandoned')) | 三态机：录制中 / 用户继续分析 / 用户放弃（FR-024 + spec round 6 第 1 题） |
| `health_stats` | JSON | NULL | 录制停止时由 Recorder 一次性写入汇总；`status='recording'` 时为 NULL；shape 见 §1.3 |
| `created_at` | TIMESTAMP | NOT NULL DEFAULT `current_timestamp` | DuckDB 行插入时刻，审计用 |

**索引**：`recording_id` 是 PRIMARY KEY 自带唯一索引，无需额外索引（Phase 1 查询模式 = 按 recording_id 直查或全表 SELECT）。

### 1.2 `desktop_actions`

> 录制中的一条动作事件。

| 列 | 类型 | 约束 | 来源 / 语义 |
|---|---|---|---|
| `action_id` | VARCHAR | PRIMARY KEY | 复用 `actions.action_id` 同套 UUID 生成函数（FR-008） |
| `recording_id` | VARCHAR | NOT NULL | 关联 `desktop_recordings.recording_id`；不显式 FOREIGN KEY（DuckDB Phase 1 不强制约束，由插入路径保证） |
| `recording_mode` | VARCHAR | NOT NULL DEFAULT `'desktop'` | 与 `actions.recording_mode` 列语义对齐 |
| `type` | VARCHAR | NOT NULL CHECK (type IN ('mouse_left', 'mouse_right', 'mouse_middle', 'wheel', 'drag', 'typing', 'hotkey')) | 7 枚举值大小写敏感（FR-013 list_desktop_actions 参数枚举与此一致） |
| `coord_x` | INTEGER | NULL | 动作时刻 cursor 屏 physical pixel x；typing/hotkey 无意义但仍记起点 cursor_pos；drag 取 mouse_up 终点（FR-008 + spec round 3 第 1 题） |
| `coord_y` | INTEGER | NULL | 同上 y |
| `monitor_index` | INTEGER | NOT NULL | hook 触发瞬间 cursor 所在屏 index（spec round 7 第 1 题）；drag 取 up 终点屏 |
| `window_title` | VARCHAR | NULL | 从 `ElementFromPoint(cursor_pos)` 向上溯源到 owning window 取（FR-003），不调 `GetForegroundWindow()` |
| `uia_summary` | JSON | NULL | UIA 控件摘要 JSON：`{"control_type": "Button", "name": "确定", "automation_id": "okBtn", "class_name": "TButton"}` 等浅层字段；50ms 同步超时则 NULL，由异步队列稍后 UPDATE；UIA COM 失败降级时全空 |
| `clipboard_text` | VARCHAR | NULL | 剪贴板文本内容（CF_UNICODETEXT）；超 `recording.large_field.threshold_chars`（默认 1000 字符）走 large_field 占位（与浏览器 actions 表同套机制） |
| `clipboard_image_path` | VARCHAR | NULL | hook 触发瞬间最新一张剪贴板图路径 `clipboard/<recording_id>_<event_seq>.png`；`_ClipboardLatest` 引用快照（FR-004 + spec round 6 第 4 题） |
| `text_content` | VARCHAR | NULL | typing 类型的整段输入文本（物理键事件重组）；非 typing 类型为 NULL；超 `recording.large_field.threshold_chars` 走 large_field 占位 |
| `timestamp` | TIMESTAMP | NOT NULL | hook 触发时刻 UTC；typing 取序列起点；drag 取 mouse_up 终点（FR-008） |
| `duration_ms` | INTEGER | NULL | typing 序列时长 / drag down→up 时长；其他类型为 NULL |
| `frame_count` | INTEGER | NOT NULL DEFAULT 0 | 实际落盘 PNG 帧数（首动作 buffer 不足 30 帧时 < 45 也如实记录，FR-005） |
| `has_clip` | BOOLEAN | NOT NULL DEFAULT FALSE | mp4 clip 是否成功落盘；clip 编码失败或 `enable_clip=false` 时 FALSE（FR-005） |
| `created_at` | TIMESTAMP | NOT NULL DEFAULT `current_timestamp` | 行插入时刻 |

**索引**：
- `action_id` PRIMARY KEY 自带唯一索引；
- `(recording_id, timestamp)` 复合索引 — `list_desktop_actions(recording_id, time_range, ...)` 按 `recording_id` 过滤后按 `timestamp` 排序的主查询路径；
- `(recording_id, type)` 复合索引 — `health_stats.action_type_counts` 聚合 + `list_desktop_actions` `action_types` 过滤路径。

DuckDB 索引语法：`CREATE INDEX desktop_actions_recording_timestamp_idx ON desktop_actions (recording_id, timestamp);` 等。

### 1.3 `health_stats` JSON shape

```json
{
  "uia_hit": 12,
  "uia_total": 18,
  "clip_success": 14,
  "clip_total": 14,
  "clipboard_event_count": 3,
  "action_type_counts": {
    "mouse_left": 14,
    "mouse_right": 0,
    "mouse_middle": 0,
    "wheel": 2,
    "drag": 2,
    "typing": 5,
    "hotkey": 4
  }
}
```

**字段语义**：
- `uia_hit`：UIA `ElementFromPoint` 在 50ms 内成功返回控件的次数；
- `uia_total`：仅累加鼠标类动作（mouse_left / mouse_right / mouse_middle / wheel / drag）；typing / hotkey 不触发 UIA 查询且不计入分母（spec round 2 第 1 题）；
- `clip_success` / `clip_total`：clip 编码成功次数 / 触发 clip 编码的次数（即所有动作数当 `enable_clip=true`，0 当 `enable_clip=false`）；
- `clipboard_event_count`：所有 `WM_CLIPBOARDUPDATE` 触发次数（含 hook 触发瞬间未取的中间事件）；
- `action_type_counts`：按 `desktop_actions.type` 分组计数，键固定为 7 枚举值，缺失类型 = 0。

**颜色判定（FR-024 + spec round 5 第 6 题）**：
- 红：`sum(action_type_counts.values()) == 0`；
- 黄：`uia_total > 0 and uia_hit / uia_total < 0.5` **或** `clip_total > 0 and (clip_total - clip_success) / clip_total > 0.2`（任一触发；`uia_total = 0` 时 UIA 轴不参与判定，`enable_clip = false` 时 clip 轴不参与判定）；
- 绿：以上条件均不触发；
- 其余指标（帧总数 / 录制时长 / 剪贴板事件 / 各类型分布）仅展示数值，不参与颜色评级。

### 1.4 `uia_summary` JSON shape

```json
{
  "control_type": "Button",
  "name": "确定",
  "automation_id": "okBtn",
  "class_name": "TButton",
  "framework_id": "Win32",
  "is_enabled": true,
  "is_offscreen": false
}
```

**字段语义**：
- 仅取浅层字段（不递归子树），避免 JSON 体积爆炸；
- 字段映射 IUIAutomationElement.GetCurrent* 系列调用结果；
- 所有字段均可空（取不到时为 NULL，不展开为字符串 "None"）；
- `framework_id` 用于 Phase 2 区分 UIA 弱场景（Electron / Java Swing 等）。

---

## 2. 文件系统目录约定

```text
data/recordings/<recording_id>/
├── frames/
│   └── <action_id>/
│       ├── frame_001.png
│       ├── frame_002.png
│       └── ...                   # 约 45 帧（前 1s 后 2s × 15fps），原生屏幕分辨率，PNG compress_level=6
├── clips/
│   └── <action_id>.mp4           # opencv-python mp4v 编码，受 enable_clip 开关控制；编码失败时不落盘
└── clipboard/
    └── <recording_id>_<event_seq>.png    # 剪贴板图，event_seq 在本次 recording 内自增整数

data/trials/<trial_id>/
├── stdout.log                    # 试用子进程完整 stdout
└── stderr.log                    # 试用子进程完整 stderr
                                  # 保留 7 天，由 ensure_startup_recovery() 启动期 mtime > 7 天 rmtree cleanup
```

**约束**：
- `data/recordings/` 根目录与浏览器录制共用（spec round 1 第 4 题）；
- `clipboard/<recording_id>_<event_seq>.png` 文件名前缀含 recording_id 是冗余但无害的命名（保留绝对唯一性，便于跨 recording 移动）；
- `<action_id>.mp4` clip 命名按 action 维度（与 frames/<action_id>/ 同维度）；
- 录制中崩溃 → 目录残留，Phase 1 不清理（FR-027 + Edge Case "录制中崩溃"），用户手动 `rm -rf data/recordings/<recording_id>/`；
- Trial 目录 7 天保留期由启动期 cleanup 处理，运行期不动。

---

## 3. Large field 占位规则

复用既有 `recording.large_field.*` 配置（`threshold_chars` / `preview_chars` / `max_chunk_chars`，默认均 1000）。

**应用列**（桌面 mode）：
- `desktop_actions.text_content`
- `desktop_actions.clipboard_text`
- `desktop_actions.uia_summary`（如序列化后超阈值，少见）

**占位行为**：
- 入库即时占位：Recorder 在写 DuckDB 行前判断字段长度，超阈值时把原文写到独立 large_field 表（既有，与浏览器 mode 共用），列值替换为占位 token；
- `read_recording` / `list_desktop_actions` 输出经 ContextManager 自动占位替换（不在工具层重复处理）；
- `read_field_chunk(stable_locator)` 桌面侧 stable locator 形式：`desktop_actions.<column>.<action_id>`（与浏览器 `actions.<column>.<action_id>` 同形）。

---

## 4. State Transitions

### 4.1 `desktop_recordings.status`

```text
            ┌─────────────────┐
            │  (新行 INSERT)  │
            └────────┬────────┘
                     ↓
              ┌─────────────┐
              │ recording   │
              └──┬────────┬─┘
                 │        │
   sanity check  │        │  sanity check
   "继续分析"    │        │  "放弃录制" / "重新录制"
                 ↓        ↓
            ┌────────┐ ┌────────────┐
            │stopped │ │ abandoned  │
            └────────┘ └────────────┘
```

- `recording → stopped`：用户点 sanity check "继续分析"，UI 跳 intent 页，PM Agent 启动；
- `recording → abandoned`：用户点 sanity check "放弃录制" 或 "重新录制"——两按钮 status 终态完全一致，仅 UI 跳转目标差（FR-024 + spec round 6 第 1 题）：
  - "放弃录制" → 回录制页且**不预选 mode**；
  - "重新录制" → 回录制页且**默认预选桌面 mode**（不立即启动 hook）；
- 终态后无再次状态转移；用户手动清理对应行 + 目录（不通过 UI）。

### 4.2 `health_stats` 写入时机

- `status='recording'` 时 `health_stats` 列为 NULL（in-memory counter 累加中）；
- `status` 跃迁到 `stopped` / `abandoned` 时由 Recorder 一次性把 in-memory counter 序列化为 JSON UPDATE 写入；
- sanity check 直读该列，不扫 `desktop_actions` 表（FR-024 + spec round 1 第 1 题）。

---

## 5. 与浏览器录制的对称关系

| 维度 | 浏览器 mode | 桌面 mode |
|---|---|---|
| Session 表 | `recording_sessions`（5 列：recording_id / start_time / end_time / recording_mode / ...） | `desktop_recordings`（8 列：+ monitor_index + status + health_stats） |
| Action 表 | `actions`（DOM-driven，含 `selector` / `xpath` / `network_request_id`） | `desktop_actions`（GUI-driven，含 `coord_x` / `coord_y` / `monitor_index` / `uia_summary` / `text_content`） |
| 多媒体 | `recording_screenshots` / `network_requests` | 文件系统 `frames/` / `clips/` / `clipboard/`（不进 DB） |
| 5 通用工具 | 走 `recording_sessions` / `actions` / `network_requests` / `sibling_snapshots` / `recording_screenshots` 5 张表 | 走 `desktop_recordings` / `desktop_actions` 2 张表 |
| 多模态分析工具 | `analyze_image`（DOM 兼有文字描述） | `analyze_desktop_action`（仅画面，GUI 无 DOM） |
| Allowlist 隔离 | sqlglot security gate 屏蔽桌面 2 张表 | sqlglot security gate 屏蔽浏览器 5 张表（FR-012a） |

**对称约束**：
- 浏览器 / 桌面 mode 互斥（CC-006）；
- 5 通用工具 schema 完全相同（FR-011 同形输出，仅内部数据源不同）；
- PM / Programmer / Trial 三 Agent 工具集对称（FR-015）。
- mode 查询唯一入口：`RecordingRepository.get_recording_mode(recording_id)`；浏览器录制从 `recording_sessions.recording_mode` 读取，桌面录制从 `desktop_recordings.recording_mode` 读取，两表均未命中时返回标准化 `recording_not_found` 错误；桌面录制不需要额外写 `recording_sessions` 镜像行。

---

## 6. Migration 与兼容性

- **DuckDB schema 演进**：Phase 1 不引入 `schema_version` 列（spec round 4 第 5 题）；Phase 2 加列时旧数据视为 obsolete 由用户手动清理；DuckDB `ALTER TABLE ADD COLUMN` 默认 NULL 满足渐进加列；真正需要 schema 演进时引入数据库 migration 工具。
- **既有 SQLite 业务库**：零变更（无新表 / 列 / 触发器）。
- **既有 DuckDB 浏览器 5 张表**：零变更（schema / 数据均不动）；门卫不变量 1-7 由 SC-005 守住。
- **配置兼容**：新增 `recording.desktop.enable_clip` / `recording.desktop.vision_model` 两个字段，缺失时默认值生效（`enable_clip=True` / `vision_model=None`）。

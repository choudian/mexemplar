# Phase 1 Data Model: Process Event Push

> 本 feature 不涉及任何持久化数据(SQLite / DuckDB / 配置表均不动)。下面所有"实体"均为 sidecar 进程内存中的运行时结构,生命周期与 `ProcessManager` 单例及其 `ProcessRecord` 同。

## 实体 1: ProcessEvent

一条派生信号。三种 type,每种 type 的 payload 字段不同。

### 字段

| 字段 | 类型 | 含义 | 不变量 |
|---|---|---|---|
| `sequence` | `int` | per-process 单调递增编号 | 同一 `ProcessRecord` 上严格递增,不复用、不跳号 |
| `type` | `Literal["state_changed", "stalled", "log_chunked"]` | 事件分类 | 三选一,不可扩展(扩展走新 feature) |
| `status` | `str` 可选 | 仅 `state_changed`:新状态值 (`completed` / `failed` / `terminated`) | type=state_changed 时 MUST 非空 |
| `exitCode` | `int \| None` 可选 | 仅 `state_changed`:进程退出码,terminated 时可能为 None | type=state_changed 时按 `ProcessRecord.exit_code` 取值 |
| `idleMs` | `int` 可选 | 仅 `stalled`:静默时长(ms) | type=stalled 时 MUST ≥ stalled_threshold_ms |
| `totalChars` | `int` 可选 | 仅 `log_chunked`:累计写入字符数 | type=log_chunked 时 MUST > 0 |
| `deltaChars` | `int` 可选 | 仅 `log_chunked`:自上次通告至本次的增量字符数 | type=log_chunked 时 MUST ≥ chunk_threshold_chars |

### Python 表达

```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class ProcessEvent:
    sequence: int
    type: str        # "state_changed" | "stalled" | "log_chunked"
    payload: dict[str, Any]   # 上表 type 相关字段,扁平存放
```

> 实际编码细节(扁平字典 vs. 多个子类)在 implement 阶段确定;契约层只承诺 `sequence` + `type` 两个顶层字段以及 type-conditional payload。

### 不变量

- `sequence` 在 `ProcessRecord.event_sequence` 计数器上分配,**不**全局唯一;跨进程比较无意义。
- 事件**不携带原文**:不含任何 stdout/stderr 行、不含 stderr 关键词、不含命令字符串、不含工作目录(命令字符串与 cwd 仍可经 `process_poll` 拿到)。
- 一旦 append 进 deque,事件 **不可变**;不允许"修订" / "撤回"已发布事件。
- 三类事件在同一 deque 中按 `sequence` 严格升序;不允许 reorder。

## 实体 2: ProcessEventCursor

调用方 ↔ 服务端的契约游标。

### 字段

| 字段 | 类型 | 含义 |
|---|---|---|
| 值域 | `int` | 单值,**非负**;首次调用未传入等价于 `0` |

### 不变量

- subagent 第一次 `wait_for_process_event` 不带 cursor 等价于 `sinceCursor=0`,服务端返回 deque 中所有现存事件 + 当前状态。
- 之后每次响应都会返回新的 `cursor` 字段;subagent **MUST** 用这个 cursor 作为下一次的 `sinceCursor`。
- cursor 单调推进,即使本次响应是 `cursorTooOld=true`(参见 spec FR-008 / clarify Q1):cursor 取队列中最新事件 sequence,空队列取当前 `event_sequence`。
- cursor 仅在单个 `processId` 上下文中有效;跨 processId 比较无意义。

## 实体 3: ProcessRecord 扩展

既有 `src/execution/process_manager.py::ProcessRecord` dataclass 新增以下字段(全部带默认值,**不破坏**既有构造调用):

| 字段 | 类型 | 默认值 | 用途 |
|---|---|---|---|
| `events` | `deque[ProcessEvent]` | `field(default_factory=lambda: deque(maxlen=event_buffer_size))` | 有界事件队列;maxlen 在 `start()` 内按配置取值并传入 |
| `event_sequence` | `int` | `0` | 下一个待分配 sequence(emit 时先 `+= 1` 再赋给事件;首条事件 sequence=1) |
| `event_condition` | `threading.Condition` | `field(default_factory=lambda: threading.Condition(self._lock))` *(见实现说明)* | 阻塞等事件唤醒;复用 `ProcessManager._lock` 作为底层锁(同一 RLock) |
| `last_output_at` | `float` | `field(default_factory=time.time)`,但在 `start()` 内立刻覆盖为 `started_at`(进程启动时刻) | 累计输出最近时刻;stalled 判定基线 |
| `last_chunk_announce` | `int` | `0` | 上一次 `log_chunked` 通告时的累计字符值;复位基线 |
| `total_output_chars` | `int` | `0` | 累计写出字符数 |
| `last_stalled_announce_output_at` | `float \| None` | `None` | 上次 stalled 通告时的 `last_output_at` 快照,防刷屏 |

### 实现说明

- `threading.Condition` 不能跨 dataclass 自动绑定到外部 `_lock`(默认会自己创建一个 Lock)。实现时由 `ProcessManager.start()` 在构造 record 后显式 `record.event_condition = threading.Condition(self._lock)`,而不是依赖 dataclass 默认工厂。
- `events` 的 `maxlen` 也无法在 dataclass 默认工厂里读配置;同样在 `start()` 内显式构造 deque 并赋值。
- 既有字段(`stdout_chunks`, `stderr_chunks`, `status`, `exit_code`, ...)行为不变。

### 不变量

- 所有事件相关字段的读写 MUST 在 `ProcessManager._lock` 持有期间完成(`_emit_event_locked` 在持锁段内 append + notify_all)。
- `event_sequence` 单调递增,只增不减;不为已被环形覆盖的事件保留。
- `last_chunk_announce` 仅在 `log_chunked` 触发 + emit 完成后赋值;失败的 emit 不更新基线(避免漏报)。
- `last_stalled_announce_output_at` 在新 `last_output_at` 出现(有新输出)时随写入更新到新值的"前一帧" — 简化规则:每条 chunk reader append 之后,执行 `last_output_at = time.time()`,**不** 清空 `last_stalled_announce_output_at`;stalled 判定改用"`last_stalled_announce_output_at != last_output_at`"等价于"自上次 stalled 后有过新输出"。

## 状态机:ProcessEvent 触发关系

```text
                ┌─────────────────────────────────────┐
                │           ProcessRecord             │
                │  status: starting → running →       │
                │     completed | failed | terminated │
                └─────────────────────────────────────┘
                            │
                            ▼
        ┌──────────────────────────────────────┐
        │ _refresh_locked (状态收敛点)            │
        │  原 running → 终态 ⇒ emit state_changed │
        └──────────────────────────────────────┘
                            │
                            ▼
        ┌──────────────────────────────────────┐
        │ _start_reader.reader (chunk 入队)      │
        │  append chunk + 累加 total_output_chars │
        │  total - last_chunk_announce ≥ chunk_  │
        │     threshold_chars ⇒ emit log_chunked  │
        │  更新 last_output_at = now              │
        └──────────────────────────────────────┘
                            │
                            ▼
        ┌──────────────────────────────────────┐
        │ wait_for_event (调用入口,懒判定 stalled) │
        │  if status == running                 │
        │     and now - last_output_at ≥ thr    │
        │     and last_stalled_announce_output_  │
        │         at != last_output_at:         │
        │        emit stalled                   │
        │        last_stalled_announce_output_  │
        │            at = last_output_at        │
        └──────────────────────────────────────┘
```

## wait_for_event 返回 payload 结构

| 字段 | 类型 | 含义 |
|---|---|---|
| `events` | `list[dict]` | `since_cursor` 之后所有未消费事件,按 sequence 升序;空列表代表"无新事件" |
| `cursor` | `int` | 调用方下一次需传入的 `sinceCursor`(单调推进) |
| `status` | `str` | 当前进程状态(`running` / `completed` / `failed` / `terminated`) |
| `exitCode` | `int \| None` | 当前 exit code(仅终态有效) |
| `cursorTooOld` | `bool` | `since_cursor` 早于队列最旧 sequence 时为 true |

`events` 的元素 schema:`{"sequence": int, "type": str, **payload-fields}`(payload 字段按上表 type-conditional)。

## 数据生命周期

- **创建**:`ProcessManager.start()` 内,与 `ProcessRecord` 同时构造。
- **写入**:仅由 `_refresh_locked`(状态边界)、`_start_reader.reader`(累积字符)、`wait_for_event`(懒判定 stalled)写;均在持锁段内。
- **读取**:仅由 `wait_for_event` 读;同样在持锁段内。
- **覆盖**:`events` 是有界 deque(`maxlen=event_buffer_size`),append 超容量时旧事件自动被环形丢弃;`event_sequence` 仍单调递增,丢弃的事件 sequence 不复用。
- **销毁**:与 `ProcessRecord` 同——`ProcessManager.cleanup()` 在 atexit 触发时,或 `close()` 调用时,record 从 `_records` 字典移除,事件对象随之被 Python GC 回收。
- **不持久化**:无 SQLite / DuckDB 表;sidecar 进程重启后旧事件全部消失,旧 processId 同步失效(走既有 `process_missing` 路径)。

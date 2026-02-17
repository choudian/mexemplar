# 事件驱动架构文档

## 概述

项目采用基于 `blinker` 的事件驱动架构，实现模块间的松耦合通信。核心思想是：**发布-订阅模式**，录制器只需"说"我完成了，工作流编排器自动"听"到并处理。

## 核心优势

### 与回调模式对比

| 特性 | 回调模式 | 事件驱动模式 ✅ |
|------|---------|----------------|
| **耦合度** | 紧耦合 | 松耦合 |
| **扩展性** | 单一回调 | 多个监听器 |
| **职责** | Recorder 需知道 Orchestrator | Recorder 只管发事件 |
| **灵活性** | 静态绑定 | 动态订阅/取消 |
| **可测试性** | 较难 | 容易 mock |

### 实际收益

```python
# ❌ 回调模式 - 紧耦合
recorder.on_recording_complete = orchestrator.process_recording

# ✅ 事件驱动 - 松耦合
recorder.stop_recording()  # 发送事件
# ↓
# 所有监听器自动响应，无需 recorder 知道谁在监听
```

## 事件系统架构

### 事件总线

```
┌─────────────┐         ┌─────────────┐
│  Recorder   │         │ Orchestrator│
│             │         │             │
│ emit(...)   ├─────────┼→ on(...)    │
└─────────────┘         └─────────────┘
       │                       │
       │                       │
       ├───────────────────────┼──→ 其他监听器
       │   (Event Bus)         │      - 数据库日志
       │                       │      - 通知系统
       │                       │      - 统计分析
       └───────────────────────┴──→ 未来扩展
```

### 已定义的事件

| 事件名称 | 触发时机 | 主要参数 |
|---------|---------|---------|
| `recording_started` | 录制开始 | `event_data: RecordingEventData` |
| `recording_stopped` | 录制停止 | `event_data: RecordingEventData` |
| `recording_completed` | 录制完成（数据准备就绪） | `session: RecordingSession` ⭐ |
| `recording_failed` | 录制失败 | `error: str` |
| `workflow_processing_started` | 工作流处理开始 | `session_id: str` |
| `workflow_processing_progress` | 处理进度更新 | `percent, step_name, message` |
| `workflow_processing_completed` | 处理完成 | `tool_id, tool_name, ...` |
| `workflow_processing_failed` | 处理失败 | `session_id, error` |
| `tool_created` | 工具创建 | `tool_data` |
| `tool_updated` | 工具更新 | `tool_data` |
| `tool_executed` | 工具执行 | `execution_result` |

## 使用指南

### 1️⃣ 基础自动处理（推荐）

最简单的方式 - 启用 `auto_process`：

```python
from src.recording.recorder import Recorder
from src.business.ai.workflow_orchestrator import WorkflowOrchestrator

# 创建录制器
recorder = Recorder(recording_mode='desktop')

# 创建编排器，启用自动处理
orchestrator = WorkflowOrchestrator(
    auto_process=True,  # 关键配置
    enable_vision=True,
    auto_save=True
)

# 开始录制
recorder.start_recording()

# ... 用户操作 ...

# 停止录制 - 自动触发工作流处理！
recorder.stop_recording()

# 清理
recorder.close()
orchestrator.close()
```

### 2️⃣ 手动控制监听

动态控制何时监听：

```python
orchestrator = WorkflowOrchestrator(auto_process=False)

# 检查状态
print(orchestrator.is_listening())  # False

# 开始监听
orchestrator.start_listening()
print(orchestrator.is_listening())  # True

# 停止监听
orchestrator.stop_listening()
print(orchestrator.is_listening())  # False
```

### 3️⃣ 自定义事件监听器

添加额外的处理逻辑：

```python
from src.utils.events import recording_completed, workflow_processing_completed

# 定义处理函数
def log_to_database(sender, **kwargs):
    session = kwargs.get('session')
    # 保存到数据库
    print(f"保存会话 {session.recording_id} 到数据库")

def send_notification(sender, **kwargs):
    tool_name = kwargs.get('tool_name')
    # 发送通知
    print(f"工具 {tool_name} 已创建！")

# 连接监听器
recording_completed.connect(log_to_database)
workflow_processing_completed.connect(send_notification)

# ... 正常使用 ...

# 断开监听器
recording_completed.disconnect(log_to_database)
workflow_processing_completed.disconnect(send_notification)
```

### 4️⃣ 装饰器方式

更优雅的监听器定义：

```python
from src.utils.events import listen_to

@listen_to('recording_completed')
def handle_recording_completed(sender, **kwargs):
    session = kwargs.get('session')
    print(f"录制完成: {session.recording_id}")

# 函数已自动连接，无需手动 connect
```

### 5️⃣ 多录制器共享

一个编排器处理多个录制器：

```python
# 创建共享编排器
orchestrator = WorkflowOrchestrator(auto_process=True)

# 多个录制器
recorder1 = Recorder(recording_mode='desktop')
recorder2 = Recorder(recording_mode='browser')
recorder3 = Recorder(recording_mode='desktop')

# 任意录制器完成都会自动触发处理
recorder1.start_recording()
# ... 操作 ...
recorder1.stop_recording()  # 自动处理

recorder2.start_recording()
# ... 操作 ...
recorder2.stop_recording()  # 自动处理
```

## 高级用法

### 发送自定义事件

```python
from src.utils.events import emit

# 发送事件
emit('custom_event',
     sender=self,
     data1='value1',
     data2='value2'
)
```

### 检查事件系统状态

```python
from src.utils.events import list_signals

# 查看所有信号和监听器数量
signals = list_signals()
for name, count in signals.items():
    print(f"{name}: {count} 个监听器")
```

### 清除所有监听器（测试用）

```python
from src.utils.events import clear_all

clear_all()  # 清除所有事件的监听器
```

## 事件流程图

### 完整的录制到工作流流程

```
用户操作                Recorder               EventBus              Orchestrator
   |                      |                       |                      |
   |-- start_recording()-->|                       |                      |
   |                      |-- emit(recording_started) ----------------->|
   |                      |                       |                      |
   |  <-- 返回 session_id--|                       |                      |
   |                      |                       |                      |
   |   [用户执行操作]      |                       |                      |
   |                      |                       |                      |
   |-- stop_recording() -->|                       |                      |
   |                      |-- emit(recording_stopped) --------------->|
   |                      |                       |                      |
   |                      |-- emit(recording_completed) ------------>|
   |                      |                       |                      |
   |                                              |-- 自动触发 --------->|
   |                                              |  process_recording() |
   |                                              |                      |
   |                                              |<-- 返回 Tool -------|
   |                                              |                      |
   |                                              |-- emit(workflow_completed)
```

### 多监听器场景

```
Recorder                  EventBus
   |                         |
   |-- emit(completed) ------>|
   |                         |---> Orchestrator (生成工作流)
   |                         |---> DatabaseLogger (保存日志)
   |                         |---> Notifier (发送通知)
   |                         |---> Analytics (统计分析)
   |                         |---> Backup (导出备份)
```

## 最佳实践

### ✅ DO（推荐做法）

1. **使用 auto_process=True** 实现自动化
   ```python
   orchestrator = WorkflowOrchestrator(auto_process=True)
   ```

2. **及时清理资源**
   ```python
   try:
       # 使用
       recorder.start_recording()
       # ...
   finally:
       recorder.close()
       orchestrator.close()  # 自动断开监听
   ```

3. **添加自定义监听器时保存引用**
   ```python
   def handler(sender, **kwargs): pass

   recording_completed.connect(handler)
   # 保存 handler 引用以便后续断开
   ```

4. **使用上下文管理器**（如果实现了）
   ```python
   with Recorder() as recorder:
       recorder.start_recording()
       # 自动清理
   ```

### ❌ DON'T（不推荐做法）

1. **不要忘记 close()**
   ```python
   # ❌ 错误：忘记清理
   recorder = Recorder()
   orchestrator = WorkflowOrchestrator(auto_process=True)
   # 使用完直接退出，监听器未断开
   ```

2. **不要在监听器中执行长时间阻塞操作**
   ```python
   # ❌ 错误：阻塞事件处理
   def handler(sender, **kwargs):
       time.sleep(100)  # 会阻塞其他监听器

   # ✅ 正确：异步处理
   def handler(sender, **kwargs):
       threading.Thread(target=long_task).start()
   ```

3. **不要重复连接同一监听器**
   ```python
   # ❌ 错误：会重复调用
   recording_completed.connect(handler)
   recording_completed.connect(handler)

   # ✅ 正确：检查后再连接
   if not is_connected:
       recording_completed.connect(handler)
   ```

## 故障排查

### 问题1: 自动处理没有触发

**检查清单**：
```python
# 1. 确认 auto_process=True
orchestrator = WorkflowOrchestrator(auto_process=True)

# 2. 确认正在监听
print(orchestrator.is_listening())  # 应该是 True

# 3. 检查事件系统状态
from src.utils.events import list_signals
print(list_signals())

# 4. 启用 DEBUG 日志
import logging
logging.basicConfig(level=logging.DEBUG)
```

### 问题2: 监听器数量异常增长

**原因**: 可能重复连接了监听器

**解决**：
```python
# 使用前先断开
recording_completed.disconnect(handler)
recording_completed.connect(handler)
```

### 问题3: 事件处理顺序不对

**说明**: blinker 不保证监听器的执行顺序

**解决**: 使用优先级或合并处理逻辑
```python
# 在单个监听器中控制顺序
def combined_handler(sender, **kwargs):
    step1()
    step2()
    step3()
```

## 性能考虑

- **blinker 开销**: 极小（~微秒级）
- **监听器数量**: 建议 < 10 个
- **事件发送频率**: 录制相关事件低频（分钟级），无性能问题

## 迁移指南

### 从回调模式迁移

**旧代码**：
```python
recorder.on_recording_complete = orchestrator.process_recording
```

**新代码**：
```python
# 方式1：自动处理（推荐）
orchestrator = WorkflowOrchestrator(auto_process=True)

# 方式2：手动监听
orchestrator.start_listening()

# 方式3：自定义监听器
def handler(sender, **kwargs):
    orchestrator.process_recording(kwargs['session'])
recording_completed.connect(handler)
```

## 测试

运行完整示例：
```bash
uv run python scripts/dev/test_event_driven_workflow.py
```

测试特定场景：
- 示例1: 基础自动处理
- 示例2: 手动控制监听
- 示例3: 自定义监听器
- 示例4: 多录制器共享
- 示例5: 检查信号状态

## 总结

事件驱动架构带来了：
- ✅ **更清晰的模块职责**
- ✅ **更灵活的扩展性**
- ✅ **更好的可测试性**
- ✅ **更符合开闭原则**

通过 `blinker` 实现，零学习曲线，即插即用！

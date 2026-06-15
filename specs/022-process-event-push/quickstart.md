# Quickstart: Process Event Push 本地验证

> 面向 implement 阶段的开发者。在本机 sidecar 进程内端到端跑一遍 `wait_for_process_event` 的核心路径。无需启动 Tauri / 前端。

## 前置

- 在 worktree 内:`.worktrees/022-process-event-push/`,分支 `022-process-event-push`
- Python 环境就绪(`uv sync`)
- 已按 plan.md 完成:
  - `src/data/config_models.py::AgentToolsProcessConfig` 增加三字段
  - `src/data/unified_config.py` 三个 getter
  - `src/execution/process_manager.py` `ProcessRecord` 扩展 + `_emit_event_locked` + `wait_for_event`
  - `src/business/agents/tools/command_tools.py` 注册 `wait_for_process_event` handler 与工具描述

## 单元测试快速验证

```powershell
uv run python -m pytest tests/execution/test_process_manager_events.py -q
uv run python -m pytest tests/business/agents/tools/test_process_event_tool.py -q
```

预期:全部绿。如失败,优先看测试用例描述,与 `data-model.md` / `contracts/wait_for_process_event.md` 的不变量逐条对齐。

## 集成行为契约

```powershell
uv run python -m pytest tests/integration/test_process_event_flow.py -q
```

测试流程:
1. 用 `ProcessManager.start` 起一个会写 8192+ 字符然后 sleep 1s 再非零退出的 Python `-c` 命令。
2. subagent 视角调用 `wait_for_process_event` 工具(timeoutMs=5000);**断言** 返回 events 至少含一条 `log_chunked`,且 status=running。
3. 用 `process_logs` 读日志,**断言** 拉到非空日志。
4. 再调一次 `wait_for_process_event(sinceCursor=cursor)`;**断言** 返回 events 含 `state_changed: failed, exitCode=1`,status=failed,cursor 单调递增。

## 手动跑通(可选)

进入 worktree,用 Python REPL 直接调用底层 ProcessManager:

```python
import time
from src.execution.process_manager import get_process_manager
from src.business.runtime import set_runtime_session

set_runtime_session(session_id="dev-quickstart", workspace_path="E:/code/Exemplar/.worktrees/022-process-event-push")
pm = get_process_manager()

# 写 8192 字符再 sleep 再退出
cmd = '''python -c "import sys, time; sys.stdout.write('x'*8192); sys.stdout.flush(); time.sleep(1); sys.exit(1)"'''
record, _ = pm.start(
    session_id="dev-quickstart",
    command=cmd,
    cwd=".",
    cwd_display=".",
    command_summary="qs",
)

# 第一次 wait:预期 log_chunked
print(pm.wait_for_event(record.process_id, since_cursor=0, timeout_ms=5000))
# 第二次 wait:预期 state_changed
print(pm.wait_for_event(record.process_id, since_cursor=1, timeout_ms=5000))
```

## 常见故障排查

| 现象 | 可能原因 | 行动 |
|---|---|---|
| 第一次 wait 直接超时,无 log_chunked | `chunk_threshold_chars` 配置高于实际输出,或 reader 线程未启动 | 临时调低 `agent_tools.process.chunk_threshold_chars`;或检查 `_start_reader` 是否被调用 |
| state_changed 没出现 | `_refresh_locked` 内 emit 调用位置错(只在 None 退出后才走) | 对照 data-model 状态图,emit 必须在 status 真正转换那一行之后,且仍持 lock |
| 即使过了 stalled 阈值也不发 stalled | `last_output_at` 没初始化为 `started_at`,或懒判定的 wait 入口忘了在 lock 内调用 emit | 对照 R-004 与 data-model 实现说明 |
| cursorTooOld 时 cursor 字段缺失 | 未实现 R-003 决策 | 修 wait_for_event 实现,空队列时让 cursor=event_sequence |
| 跨会话调用居然成功 | `_process_for_current_session` 没在 handler 里调 | 对照 `process_poll_handler` 的模式 |

## 验证 spec / plan 不被绕过

```powershell
uv run python -m pytest tests/guardrails -q
```

注意:本 feature 不替换架构接线,**不**新增门卫测试。既有 guardrails 全绿即可。

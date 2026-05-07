# Exemplar Project Constraints

本文件记录开发约束、反模式和允许例外。长期治理原则仍以 `.specify/memory/constitution.md` 为准。

## Agent Tool Hook Boundaries

- pre_hook 只允许放行、拒绝和观测，不允许改写 handler 入参。
- `ToolCallContext.args` 必须是递归只读隔离视图；顶层和嵌套 dict/list 写入都应抛异常，handler 入参不受影响。
- `PreHookResult` 只表达拒绝结果，不携带替换参数。
- post_hook 不通过 `ToolCallContext` 获取结果；它只能通过第二个 `result` 参数读取 handler 原始字符串结果或普通 handler 异常转换出的标准化错误字符串。
- post_hook 不形成结果流水线；每个 post_hook 看到同一个原始结果，最后一个返回非空 `PostHookResult.result` 的 hook 决定最终文本。
- `ToolSignal` 是 AgentLoop 控制信号，合法中断型工具返回该信号时跳过 post_hook。

## Migrated Gate Ownership

- `builtin_general_tools.read_file`、`write_file`、`edit_file`、`list_dir`、`exec` 的路径存在性、系统目录拒绝、命令安全分类和用户确认属于 pre_hook。
- `edit_file` 的 `old_text` 查找与唯一性校验属于编辑执行准备，留在 handler。
- assistant 高危确认必须只展示和记录脱敏摘要：`write_file` 只含目标路径，`edit_file` 只含截断片段，`exec` 只含命令首行；不得记录完整文件内容、完整替换文本或多行命令体。
- assistant “全部允许/免确认”只允许是当前进程会话级内存状态，不得写入配置、keyring、SQLite 或 DuckDB；新对话入口必须复位该状态并收敛旧 pending 请求。
- `recording_data_tools.query_data` 的 SQL 拒绝策略属于 pre_hook，但 handler 仍可再次调用 `rewrite(sql)` 生成实际执行 SQL。
- `recording_data_tools.analyze_image` 的单次最多 5 个 action_index 限制属于 pre_hook。
- `trial_tools.run_command` 的单次 `AgentLoop.run()` 调用上限属于 `create_trial_tools()` 内创建的 pre_hook 闭包。

## Non-Migrated Boundaries

- `programmer_tools.syntax_check` 整个 handler 即校验本身，不迁移到 hook。
- `recording_data_tools.execute_code` 的受限 builtins、import 控制和超时属于执行内核，不迁移到 hook。
- `src/execution/tool_executor.py` 的 venv 隔离和命令白名单位于 handler 层之下，不迁移到 hook。
- `dynamic_tool_manager` 的发布状态、允许列表、技能发现和技能组合激活属于工具发现阶段，不迁移到 hook。

## Desktop Recording Boundaries

- UI 不直接实例化 `DesktopRecorder`，也不直接读写 Repository；桌面录制只能经 `DesktopRecordingService` / UI bridge 进入业务层。
- 桌面录制必须在主窗口完成 minimize 之后启动 hook，避免 UI 点击本身被写入 `desktop_actions`。
- `recording_data_tools` 根据 `RecordingRepository.get_recording_mode(recording_id)` 固定本次工具集 mode；浏览器 mode 只能访问浏览器录制表，桌面 mode 只能访问 `desktop_recordings` / `desktop_actions`，跨 mode 返回 `table_not_in_mode`。
- 浏览器 PM/Programmer/Trial 工具集保持 legacy 路径和 `analyze_image`；桌面 PM/Programmer/Trial 工具集注入桌面专属工具，且不得注入 `analyze_image`。
- `analyze_desktop_action` 只在 `recording.desktop.vision_model` 已配置时注入；缺失时自然降级为文本和结构化数据分析。
- 桌面 Programmer 输出代码先过 `ast.parse` syntax gate；连续重试失败通过 `desktop_syntax_gate_retry_failed` 和 agent error 终止，不进入 Trial 执行。
- 桌面 Trial 子进程由 `src/execution/desktop_trial_runner.py` 创建 `data/trials/<trial_id>/`、设置 cwd、应用 env 白名单、执行 120s 超时和 Windows `taskkill` 清理；business 层只负责编排调用和事件。
- 桌面录制跨模块通知只能走 `src/utils/events.py` blinker 事件；UI 侧通过本地 Qt signal 回到 UI 线程，不允许 recording / business / execution 层 import UI widget。
- 桌面 action 必须带 `monitor_index`；DPI awareness 在 QApplication 前应用，失败只降级记录日志。

## Review Guardrails

Reviewer 必须拒绝下列改动：

- 在 pre_hook 中加入参数改写或参数流水线语义。
- 在 `ToolCallContext` 中加入确认回调、结果字段或可写参数引用。
- 在 handler 中保留已经迁移到 pre_hook 的拒绝、确认、限流或安全策略分支。
- 将 assistant 高危确认改回模态 `QMessageBox.question`，或让普通 Toast 与 Auth Toast 复用同一个生命周期引用。
- 将自动放行状态持久化，或把未脱敏的文件内容、替换文本、命令体写入确认日志。
- 让 AgentLoop 内建注入的 `load_reference` 或 `talk_to_user` 进入 tool/global hook 链。
- 绕过 `src/recording/filtering/` 的 SQL 改写或 DuckDB 代理边界读取录制网络数据。
- 让桌面录制 UI 直接访问 Repository 或 Recorder，或绕过 `DesktopRecordingService`。
- 在桌面 mode 中注入 `analyze_image`，或允许桌面工具读取浏览器录制表。
- 让桌面 Trial 继承完整父进程环境、在任意 cwd 执行，或缺少超时清理。

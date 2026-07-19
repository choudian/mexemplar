"""调度中心（Scheduling Center）业务层。

调度中心是**时间维度触发中枢**：到点（立即 / 一次性 / 周期）唤醒一个标记为
``source=scheduled`` 的主助理会话，让它全权处理用户埋下的指令，跑完记账、喊用户。

命名区隔（三处「调度」词汇重叠，靠本模块文档点明，不改既有命名）：

- **调度中心（scheduling，本模块）= 时间维度触发中枢**——到点唤醒会话。
- ``task_collaboration.graph_scheduler`` = **依赖维度推进器**——任务图 DAG 按依赖
  就绪自动推进节点。本特性不改变其推进 / 通信 / 恢复决策；仅抽取公共终态函数，并在
  首次全终态时新增观察事件，且观察者失败不得阻断既有父侧回流。
- 「100% 调度」（dispatch）= **任务派发机制**——主助理把任务派给临时 subagent 或
  固定 specialist。

本特性**不另起新系统**：触发后复用既有任务协作内核（durable 执行 / lease 恢复 /
裁定回流 / 通信通道 / 任务图调度）推进执行，只在外层加「触发 + 完成判定 + 通知」。

子模块：

- ``models``：枚举（ScheduledTaskStatus / RunStatus / ScheduleKind / 来源类型）。
- ``scheduler_service``：CRUD + 触发时机判定 + ``compute_next_fire``。
- ``scheduler_worker``：值守线程（周期扫描 + 立即唤醒双 Event）+ misfire / reentry。
- ``session_launcher``：建 ``source=scheduled`` 会话 + 投递指令 + 无人值守提示。
- ``run_completion_monitor``：订阅 run / 图事件，三条件判静默，写 run 终态 + 通知。
- ``unattended_confirmation_manager``：per-task 免确认（独立于进程级 ``_auto_approve_enabled``）。
- ``scheduling_confirmation_manager``：创建确认卡（first-decision-wins + ``expires_at``）。
- ``task_collaboration.graph_terminal``：内核自有 ``compute_graph_terminal_state`` 公共函数，
  scheduling 单向调用（消除第三份 inline 复制）。
"""

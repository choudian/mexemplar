# 任务图 DAG 可视化设计

日期：2026-07-21
状态：待实现

## 背景

复杂任务在后端已经是一张有向无环图：`TaskGraphSnapshot` 同时携带 `tasks`、`edges`
和 `adjudications`（`src/business/task_collaboration/models.py:148-172`）。但前端
`TaskGraphPanel.tsx` 把它渲染成一个平铺的 `<ul>` 列表，遍历 `graph.tasks` 逐条输出，
**完全没有消费 `edges`**。

结果是依赖关系不可见：哪一步在等哪一步、卡住的节点堵住了谁、并行分支跑到了哪里，
用户都看不出来。

数据库现状印证了这个盲区的代价：`data/mexemplar.db` 里任务图共 2 张，各 1 个节点，
依赖边 0 条。无法判断这是"从未触发过复杂任务"还是"建图逻辑没生效"——因为没有任何
观察手段。

## 目标

让同一个任务图视图在两个场景下可用：

1. **实时盯进度**：在主助理会话里派了复杂任务，从任务卡片打开，看拆成了几步、
   现在卡在哪、哪一步在等审批。
2. **事后看细节**：定时任务夜里跑完，早上从调度中心的 run 记录点进去，看那一轮
   具体发生了什么。

## 非目标

- 不新增主屏。跨会话总览的需求已被调度中心覆盖，独立主屏是过度设计。
- 不引入图形库（reactflow / dagre / d3 / cytoscape）。前端当前零图形依赖，保持。
- 不处理孤儿 worktree 清理。那是独立问题，另行解决，不混入本设计。
- 不做迷你地图、不做连线交叉最小化优化。

## 架构

新增目录 `frontend/src/components/taskGraph/`，四个部件各司其职。放在 `components/`
而非 `screens/` 下，因为 Assistant 屏和 ScheduledScreen 都要用。

| 文件 | 职责 | 依赖 |
|---|---|---|
| `layoutDag.ts` | 纯函数。输入 tasks + edges，输出每个节点的层号与坐标、每条边的路径、回边标记 | 无（不 import React） |
| `DagCanvas.tsx` | 纯展示。接收布局结果画 SVG，管理选中态、平移、缩放 | `layoutDag.ts` |
| `TaskDetailPane.tsx` | 选中节点的详情与操作（描述、状态、执行人、PLAN/RESULT 预览、审批按钮） | 复用既有审批与 external coding 展示逻辑 |
| `TaskGraphDialog.tsx` | 弹窗外壳。加载、错误、实时刷新订阅、全屏切换。两个入口的差异全部收敛在这里 | 上面三个 |

把布局单独提成无 React 依赖的纯函数，是这个设计里最关键的一次切分：布局是唯一
含算法的部分，隔离后可以直接单测，且 `DagCanvas` 退化成"给什么画什么"的哑组件。

## 数据流

### 入口一：主助理会话

`assistantTaskStore` 已持有 graph snapshot，直接传入弹窗。前端本来就订阅
`assistant.task_graph.changed`，弹窗跟随刷新。

**不新增任何公开 UI 事件。**

### 入口二：调度中心 run 记录

链路已验证可行，无需新增数据库字段：

```
ScheduledRun.session_id + ScheduledRun.trigger_message_sequence
  → TaskCollaborationService.get_current_graph_id(session_id, user_message_sequence)
  → get_graph_snapshot(session_id, graph_id)
```

`trigger_message_sequence` 在 `src/business/scheduling/session_launcher.py:201` 写入；
按 message sequence 定位历史图的能力在
`src/business/task_collaboration/service.py:916` 已存在。

后端改动：ScheduledRun 的 DTO 增加 `graphId: string | null`，由 scheduling business
层计算后返回，前端不再多发一次请求。scheduling 已经依赖 task_collaboration
（`run_completion_monitor.py:21` 注明 "`get_graph_snapshot` 走 task_collaboration
既有 API"），不引入新的分层依赖。计算必须落在 business facade，不得在 router 内拼装。

## 布局算法

分层布局（Sugiyama 简化版），全部手写：

1. **层号**：节点层号 = 从任一根到它的最长路径长度。用最长路径而非最短，保证所有
   前驱严格位于更上层，连线永远向下。
2. **层内顺序**：按前驱节点的平均横向位置排序；无前驱的根节点按 `tasks` 数组原
   顺序排列。这是启发式，不追求交叉数最优。
3. **坐标**：`y = 层号 × 层距`，`x = 层内索引 × 节点间距`。
4. **回边处理**：DAG 理论上无环，但数据可能脏。拓扑排序后若仍有未定层节点，判定
   为环，将环上的边标记为回边——**计算层号时忽略回边，但仍然画出来**（虚线样式），
   同时在画布上给出提示。绝不允许布局函数陷入死循环。

## 交互

- **平移与缩放**：SVG 内容包在 `<g transform="translate(x,y) scale(s)">` 中，拖拽改
  translate，滚轮改 scale，双击复位。不需要图形库。
- **缩放锚点**：以鼠标指针位置为锚点，指针下方的图形位置在缩放前后保持不变（同地图
  交互）。锚点不跟随选中节点——用户放大时常常是要看别处。
- **全屏**：弹窗右上角切换按钮。
- **自动定位**：打开时不显示全图，而是自动滚动并高亮"最需要注意"的节点，按
  `display_phase` 优先级挑选：

  ```
  needs_attention > reviewing > paused > running > done
  ```

  同优先级存在多个节点时，取层号最小者；层号相同则取层内序号最小者。全部不存在时
  回落到全图适配。这条把"打开图去找问题"变成"打开图它告诉我问题在哪"。
- **选中**：点节点 → 下半部详情区展开该节点；不选中时详情区收起，图占满弹窗。

## 边界与失败处理

| 情况 | 行为 |
|---|---|
| 图只有 1 个节点 | 不显示"查看任务图"入口。单个方块无信息量（当前真实数据即为此状态） |
| 节点数很多 | 正常绘制。平移缩放足以应对，不降级成列表。200 个 SVG 节点对 React 无压力，不做虚拟化 |
| 边成环 | 忽略回边算层号，回边以虚线画出并提示，不崩溃、不死循环 |
| 该 run 没有产生任务图 | 显示"这一轮没有产生任务图"，不渲染空白画布 |
| snapshot 拉取失败 | 显示可行动的错误文案，保留上一次快照而非清空 |

节点上限由 `assistant_tasks.graph.max_tasks` 约束，默认 200
（`src/data/unified_config.py:858-861`）。

## 测试

**`layoutDag.ts`（重点，纯函数易覆盖）**
- 线性链：层号递增
- 分叉后汇合：汇合节点层号取最长路径
- 多个根节点
- 成环：不死循环，回边被标记
- 空图 / 单节点

**弹窗组件**
- 单节点时不暴露入口
- `assistant.task_graph.changed` 到达后刷新
- 切换选中节点，详情区跟随
- 自动定位挑中 needs_attention 节点

前端单测放 `frontend/tests/unit/`。后端 DTO 变更补 `tests/desktop_api/` 对应用例，
覆盖"run 有图"与"run 无图返回 null"两条路径。

## 已验证的事实

本设计基于以下实际验证，非推断：

- `TaskGraphSnapshot` 含 tasks / edges / adjudications — `models.py:148-172`
- `TaskGraphPanel.tsx` 为纯列表，未消费 edges — 全文 187 行无 SVG/连线代码
- 前端零图形库 — `frontend/package.json` 依赖清单
- 图规模上限 200，可配 — `unified_config.py:858-861`
- 真实数据：2 张图，各 1 节点，0 条边 — 查询 `data/mexemplar.db`
- run → graph 链路可达 — `session_launcher.py:201` + `service.py:916`
- scheduling → task_collaboration 依赖既有 — `run_completion_monitor.py:21,581`

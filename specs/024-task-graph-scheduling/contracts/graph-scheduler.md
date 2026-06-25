# Contract: DAG Scheduler（024 新增组件）

**Branch**: `024-task-graph-scheduling` | **Date**: 2026-06-24
**位置**：`src/business/task_collaboration/graph_scheduler.py`（新增）。
**性质**：确定性、非 LLM 的「按依赖推进器」。只负责「谁该跑了」；「结果行不行 / 失败咋办 / 高风险放不放行」由主助理裁定。不替代主助理裁定职责。

---

## 1. 组件接口

```python
class GraphScheduler:
    def __init__(
        self,
        *,
        dispatcher: TaskDispatcher,                          # start_attempt_async 派就绪节点
        reentry_sink: ParentReentrySink | None = None,       # 通知主助理（裁定/完成）；可后续 set_reentry_sink 注入
    ) -> None: ...
    # 注：不持有 service——每次 _run 临时构造 TaskCollaborationService（per-operation
    # session），避免长生命周期 service 的 identity-map stale，与 dispatcher/adjudication 一致。

    def start_graph(self, graph_id: str) -> None:
        """建图后触发；扫就绪节点开始推进。幂等。"""

    def on_attempt_outcome(self, graph_id: str, task_id: str) -> None:
        """节点 attempt 完成（done/stuck/failed_input）后调；
        重扫就绪、激活下游、判定全图完成。"""

    def on_adjudication_decided(self, graph_id: str, task_id: str, decision: str) -> None:
        """主助理裁定落定后调；
        accepted(需确认放行)→dispatch；returned→重派/改图后续；abandoned→取消下游。"""

    def on_executor_recovered(self, graph_id: str, task_id: str) -> None:
        """executor lease 过期/崩溃恢复后调（由 background_worker 触发）；
        节点已退回 pending_dispatch，重入就绪重派。"""
```

**触发来源**（复用 023 通道）：
- `start_graph`：`build_task_graph` handler 事务外调。
- `on_attempt_outcome`：dispatcher `_record_attempt_outcome` 内、`_notify_parent_reentry` 之前/之后 hook（或由 reentry 链路顺带通知 scheduler）。
- `on_adjudication_decided`：`adjudication.decide` 事务后调。
- `on_executor_recovered`：`background_worker._fence_expired_attempts` 恢复后调。

---

## 2. 核心循环（确定性）

```
advance(graph_id):
  snapshot = service.get_graph_snapshot(graph_id)
  if all_nodes_terminal(snapshot):              # 全图完成
      reentry_sink.notify_graph_complete(graph_id)   # 主助理向用户汇报（DEC-H briefing）
      return
  for node in snapshot.nodes where status==pending_dispatch:
      if not dependencies_satisfied(node, snapshot):
          continue                               # 就绪硬校验（双层之一）
      if node.requires_confirmation and not adjudication_accepted(node):
          ensure_pending_adjudication(node, kind="needs_confirmation")
          reentry_sink.notify_needs_review(node)    # DEC-D 暂停回流
          continue                               # 不 dispatch
      dispatcher.start_attempt_async(            # 复用 023 派发内核
          task_id=node.task_id,
          executor_type=node.assignee_type,
          executor_id=resolve_executor_id(node),
          lease_owner="graph_scheduler",
      )
```

**关键不变量**：
- 一个节点同时只有一个 active attempt（capacity=1，023 已强制）。
- `requires_confirmation` 节点在主助理 `accepted` 裁定前绝不 dispatch。
- 全图完成、需确认、失败 三态都经 reentry_sink 通知主助理（不直接对外发 UI 事件，UI 投影复用 023 task 事件）。

---

## 3. 就绪硬校验（新建，借鉴 claude-code claim）

```python
# assistant_task_repository.py（新增方法）
def _assert_dependencies_satisfied(self, graph_id: str, task_id: str) -> None:
    """派发/认领前在数据层强制校验：所有 edge_type='dependency' 且 propagation='blocking'
    的前置节点必须 status='completed'。前置未完成 → raise，派不出。
    这是 scheduler 就绪扫描的底层兜底：即便 scheduler 扫描有遗漏，claim 层也挡住乱序。"""
```

**双层校验**：scheduler.advance 内扫描（第一层）+ Repository `_assert_dependencies_satisfied`（第二层兜底）。两者都过才派发。

---

## 4. 暂停 / 恢复 / 取消（复用 023）

- **需确认暂停**：scheduler 建 pending adjudication（needs_confirmation）+ reentry 通知；主助理裁定 accepted → `on_adjudication_decided` → dispatch。
- **失败暂停**：023 已建 pending adjudication（stuck/failed_input）；scheduler 不重复建，只在 briefing 附自愈清单（DEC-C）。
- **executor 异常**：023 `background_worker._fence_expired_attempts` 已把过期 attempt fenced、节点回 pending_dispatch；scheduler `on_executor_recovered` 重入就绪。**不新建 unassign 机制**（CC-009，复用 023 lease 回收）。
- **用户取消/改主意**：复用 023 `cancel_graph`（`_bulk_transition` + `expected_graph_version` 围栏）+ 三层 cancel key（graph/task/attempt）。改主意 = cancel 旧图 + 重新走分解。

---

## 5. 单测锚点（constitution IV）

- 就绪激活顺序（串行链、并行 fan-out、串并混合）。
- `_assert_dependencies_satisfied` 拒乱序（前置未完成派不出）。
- 无环校验（建图/改图时环被拒）。
- `requires_confirmation` 节点裁定前不 dispatch、accepted 后才 dispatch。
- 全图完成触发汇报回流。
- executor lease 过期后节点退回 pending_dispatch、图不卡死（复用 023 恢复测试范式）。
- cancel 传播 + expected_graph_version 围栏（复用 023 测试范式）。

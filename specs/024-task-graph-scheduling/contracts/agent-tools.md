# Contract: Agent Tools（024）

**Branch**: `024-task-graph-scheduling` | **Date**: 2026-06-24
LLM function-calling 契约。工具按 023 既有模式（`make_tool_schema` + `create_xxx_handler` 工厂 + `tool_registry.build_assistant_tools()` 装配 `ToolDefinition`）实现，落 `src/business/agents/tools/assistant_tools.py` + `tool_registry.py`（**不碰 orchestrator.py 死代码**）。

---

## 1. `build_task_graph`（新增）— 分解者建图

**持有者**：主助理（中等任务自拆）+ 规划专员（超阈值任务，planner 变体）。

```jsonc
{
  "name": "build_task_graph",
  "description": "把一个复杂任务分解成一张带依赖关系的任务图并原子落库，交由 DAG 调度器按依赖自动推进。仅用于多步、有先后依赖或跨领域的复杂任务；1-2 步的简单任务直接用 delegate_to_subagent/specialist，不要建图。节点粒度=一个执行器（专员/子agent）的一次连贯执行；节点内部若≥3步，执行器会用 todo_update 自行分解子步骤。高风险/不可逆节点（发邮件、删数据、对外发送）必须标 needsConfirmation=true，调度器会在执行前暂停等主助理裁定。",
  "parameters": {
    "type": "object",
    "required": ["nodes"],
    "properties": {
      "nodes": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "required": ["nodeId", "title", "description"],
          "properties": {
            "nodeId":   { "type": "string", "description": "节点稳定标识，用于 dependencies 引用（如 n1）" },
            "title":    { "type": "string" },
            "description": { "type": "string", "description": "自包含的执行指令，执行器照此完成该节点" },
            "assigneeHint": { "type": "string", "enum": ["specialist", "ephemeral_subagent"], "description": "建议执行器类型（最终由调度器/裁定决定）" },
            "capabilityScope": { "type": "array", "items": {"type":"string"}, "description": "该节点允许的工具白名单（可选，复用 capability_scope）" },
            "needsConfirmation": { "type": "boolean", "default": false, "description": "高风险/不可逆节点标 true" }
          }
        }
      },
      "dependencies": {
        "type": "array",
        "description": "先后依赖；from 必须先于 to 完成。无依赖的节点可并行。",
        "items": {
          "type": "object",
          "required": ["from", "to"],
          "properties": {
            "from": { "type": "string", "description": "前置节点 nodeId" },
            "to":   { "type": "string", "description": "后继节点 nodeId" }
          }
        }
      }
    }
  }
}
```

**返回（统一 envelope）**：
```jsonc
{
  "graphId": "graph-...",
  "nodeTaskIds": { "n1": "task-...", "n2": "task-..." },
  "confirmationRequired": true,           // 任一节点 needsConfirmation=true
  "readyNodeCount": 2,                    // 建图即就绪可派的节点数
  "schedulingStarted": true               // scheduler 已启动该图
}
```

**handler 行为**（`create_build_task_graph_handler(session_id, *, dispatch_callback)`）：
1. 单个 `_atomic` 内：建根任务（`create_root_graph`）→ 逐节点 `create_task`（带 `requires_confirmation`、`capability_scope`）→ 逐依赖 `add_edge(edge_type="dependency", propagation="blocking")`（自动过 `_assert_no_cycle`）。
2. 复用 graph 预算校验（`get_assistant_tasks_graph_max_tasks()`）。
3. 事务外触发 DAG scheduler 启动该图（`graph_scheduler.start_graph(graph_id)`）。
4. graph_version 按 DEC-F 接受 per-edge 递增。

**门卫**（落库层校验，CC-006）：planner 变体 handler 拒绝任何执行器工具装配（由 tool_registry 分支保证，非 handler 内判断）。

---

## 2. `mutate_task_graph`（新增）— 自愈「改图」

**持有者**：主助理（自愈决策时）。仅对运行中、由 scheduler 驱动的图生效。

```jsonc
{
  "name": "mutate_task_graph",
  "description": "在任务图自愈时修改图结构：新增节点、跳过节点、增删依赖边。仅当回流建议「改图」且确有必要时使用；每次变更会 bump graph_version 并重新过无环校验。",
  "parameters": {
    "type": "object",
    "required": ["graphId", "changes"],
    "properties": {
      "graphId": { "type": "string" },
      "changes": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "op": { "type": "string", "enum": ["add_node", "skip_node", "add_dependency", "remove_dependency"] },
            "nodeId": { "type": "string" },
            "title": { "type": "string" },
            "description": { "type": "string" },
            "from": { "type": "string" },
            "to": { "type": "string" }
          }
        }
      },
      "reason": { "type": "string", "description": "自愈理由（落 graph_version 变更记录，可追溯）" }
    }
  }
}
```

**返回**：`{ "applied": [...], "rejected": [...], "graphVersion": N, "rescanned": true }`。skip_node 的下游处理规则见 data-model.md §3。

---

## 3. `todo_update`（扩 description，既有工具）

**注入点不变**（`tool_registry.py:140-151`，specialist + ephemeral 均注入）。**仅扩 description**，按 claude-code TodoWrite 结构引导节点内分解（DEC 见 research.md §3，主体放工具描述、不放 agent prompt）：

```
description（扩充要点）：
- 何时用：当前节点内部 ≥3 个子步骤、或非平凡的多步执行时，开工前先用本工具列出 todo。
- 何时不用：1-2 步的简单节点直接做；纯信息查询不必列 todo。
- 三态流转：todo（待办）→ doing（进行中，同一时刻尽量一件）→ done（真正完成）/ skipped（有意跳过）。
- 实时更新：每完成一个子步骤立即标 done 再推进下一个，不要全做完一次性更新。
- 完成判定红线：未真正完成的子步骤绝不标 done；拿不准就先列 todo 再动手。
- 范围：todo 是你当前节点的私人 checklist，不委派、不裁定、不进入任务图依赖。
```

schema（properties: taskId/items[{todoId,text,status,sorOrder}]）不变。

---

## 4. 复用工具（无改动）

- `delegate_to_subagent` / `delegate_to_specialist`（超阈值委派 planner 用后者）。
- `decide_task_adjudication`（accepted/returned/abandoned，需确认裁定 + 自愈落定）。
- `ask_user_question`（自愈兜不住升级用户）。
- `inspect_subagent` / `continue_subagent`（既有，节点执行器可唤回）。

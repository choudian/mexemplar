# Contract: Reentry Briefing 扩展（024）

**Branch**: `024-task-graph-scheduling` | **Date**: 2026-06-24
**位置**：`src/business/task_collaboration/reentry_briefing.py`（既有纯文本 briefing）+ `src/desktop_api/assistant_runtime.py`（drain 后查 snapshot 传入）。
**性质**：briefing 保持**纯文本 prompt**（非结构化对象），024 以文本段注入结构化引导（DEC-H）。briefing 归 business 层组装，UI adapter 只转发预构造字符串。

---

## 1. 签名变更

```python
# reentry_briefing.py（扩参数，保持纯函数可单测）
def build_reentry_briefing(
    entries: list[dict],
    *,
    snapshot: TaskGraphSnapshot | None = None,   # 新增：由 runtime drain 后查一次传入
) -> str: ...
```

- 不做 IO（snapshot 由调用方传入，保持可单测）。
- `snapshot is None` 时退化为现状行为（向后兼容现有非图任务回流）。

## 2. 调用点变更

```python
# assistant_runtime.py:_run_assistant_reentry（drain 后）
entries = sink.drain(session_id)
entries = self._drop_decided_entries(graph_id, entries)
snapshot = self._load_graph_snapshot_for_briefing(graph_id)   # 新增：一次只读查询
summary = build_reentry_briefing(entries, snapshot=snapshot)
orchestrator.run_agent(ASSISTANT, {"role": "program", "content": summary}, ...)
```

## 3. 文本段扩展（在现有 result/question 段基础上追加）

### 3.1 下一步建议段（确定性，由 snapshot 计算）
```
【任务图进度】
- 图 graph-... 共 N 节点：completed=A, running=B, pending=C, 需裁定=D, failed=E
- 就绪可派节点：[n3(整理周报), n5(校对)]
- 待你裁定：n4(发送周报邮件)【需确认，高风险：对外发送】、n2(失败，可自愈)
- 全图状态：进行中 / 已全部完成（若完成，请向用户汇报最终结果）
```

### 3.2 自愈动作清单段（失败 entry 携带，advisory）
```
【节点 n2 失败自愈选项】（选一个，用 decide_task_adjudication 落定）
- 重试该节点        → decide(decision="returned")
- 换执行器重试      → 改 assignee 后 decide(decision="returned")
- 调整输入后重做    → decide(decision="returned", instruction="…")
- 跳过该节点        → mutate_task_graph(skip_node)（若可容忍，下游继续）
- 改图绕过          → mutate_task_graph(add_node/remove_dependency)
- 放弃该分支        → decide(decision="abandoned")
- 兜不住/需用户定方向 → ask_user_question 升级用户
```

### 3.3 节点 todo 概览段（snapshot 聚合，供裁定）
```
【进行中节点子步骤】
- n3(整理周报)：[done]拉取纪要 [doing]去噪归类 [todo]输出周报
- n5(校对)：[todo]全文校对 [todo]格式检查
```

## 4. 失败 entry 携带字段（dispatcher/service 计算，供 §3.2 拼装）

`_record_attempt_outcome` payload（失败分支）新增 advisory 字段：
```python
{
  ...existing...,
  "healingActions": ["retry", "swap_executor", "adjust_input", "skip", "replan", "abandon"],
  "safeRecoveryHint": "节点执行超时，可重试或换执行器",   # 安全脱敏，不泄漏原始诊断
}
```
- `healingActions` 是确定性候选集（按 failure 分类生成），非 LLM 生成。
- `safeRecoveryHint` 遵循 023 安全投影（不泄漏 provider 原始错误，CC 安全规则）。

## 5. 不变量

- briefing 永远是 business 层组装的纯文本；`assistant_runtime` 只查 snapshot + 转发，不下沉业务逻辑。
- 结构化引导是 advisory（CC-008）：主助理最终用既有工具（decide_task_adjudication / mutate_task_graph / ask_user_question）落定，briefing 不替它决策。
- todo 概览只读聚合（`TaskTodoService.list_todos` 不持写锁，跨 service 读安全）。

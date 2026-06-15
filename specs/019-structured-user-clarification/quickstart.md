# Quickstart: 结构化多选澄清

## 端到端流程（happy path）

1. 主助理在执行任务时遇到无法可靠推断的关键决策，**单独**调用 `ask_user_question`，传入 1–4 道结构化问题。
2. handler 校验入参 → 生成稳定 `questionId/optionId` → 创建内存 `PendingClarification` → 发出 `assistant.clarification_requested` 事件 → 阻塞在 `event.wait(300s)`。
3. 前端收到事件，在输入框上方渲染 `ClarificationCard`（fieldset + radio/checkbox + "其他" + 倒计时）。
4. 用户勾选并提交 → `POST .../clarifications/{requestId}/decision`（`decision=submit`）。
5. manager 校验归属与答案 → first-decision-wins 设结果 → `event.set()` → 发出 `assistant.clarification_resolved(answered)`。
6. handler 唤醒，把 `selectedOptionIds → selectedLabels` 组装为 tool result string 返回。
7. AgentLoop 在**同一 loop** 内把结果写入上下文，主助理据答案继续调度。

## 本地验证命令

后端（在 worktree 根目录）：

```powershell
uv run python -m pytest tests/business/test_clarification_manager.py -q
uv run python -m pytest tests/business/test_agent_loop_exclusive_tool.py -q
uv run python -m pytest tests/desktop_api/test_clarification_api.py -q
uv run python -m pytest tests/integration/test_clarification_flow.py -q
uv run python -m pytest tests/test_auth_toast_confirmation.py -q
# 回归：高危确认 / 停止 / 排队 / UI event
uv run python -m pytest tests/desktop_api tests/guardrails -q
uv run python -m py_compile src/desktop_api/app.py
```

前端：

```powershell
cd frontend
npm run test
npm run lint
npm run build
```

## 手动冒烟检查清单

- [ ] 单选题：选"其他"自动取消普通选项；提交后 tool result 含 `otherText`。
- [ ] 多选题：普通选项与"其他"可并存。
- [ ] 暂不回答：卡片消失，`status=cancelled`，主助理不在同回合再问。
- [ ] 5 分钟不动：`status=timeout`，worker 被唤醒。
- [ ] 提交期间全部控件 disabled，不可重复提交。
- [ ] 同批多工具调用：全部 `invalid_model_output`，零执行。
- [ ] 停止当前回合：`status=stopped`；关闭应用：`status=shutdown`。
- [ ] SSE 断线重连：卡片仍在（经 `GET pending` 恢复），可继续作答。
- [ ] 切换会话：草稿保留；回到原会话草稿还在。
- [ ] 卡片预览按纯文本展示，不渲染 HTML/Markdown。
- [ ] `assistant.clarification_resolved` 事件与普通 DTO 不含任何答案。
- [ ] 不显示"全部允许"，不复用高危确认 Toast。

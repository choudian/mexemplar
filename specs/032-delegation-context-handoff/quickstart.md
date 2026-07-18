# Quickstart: 委派上下文交接验证

**Feature**: 032-delegation-context-handoff

## 自动化验证(主路径)

```powershell
# resolver 单元测试(合法展开/越界/超限/无快照/重复拒绝)
uv run python -m pytest tests/business/agents/test_delegation_context.py -q

# 委派链路行为测试(同步注入原文、异步落库全文、专员对齐、fail-closed)
uv run python -m pytest tests/business -k "delegat" -q

# 集成:异步任务快照消亡后执行仍含全文
uv run python -m pytest tests/integration -k "delegation_context or task_dispatch" -q

# 回归:既有委派与任务协作
uv run python -m pytest tests/business tests/integration -k "subagent or specialist or task" -q
```

## 手工验证(桌面应用)

1. 启动 Tauri 应用,进入 AI Assistant 屏。
2. 让主助理"给我出一个 XX 方案"(产生一条含方案全文的助理消息)。
3. 下一轮:"把这个方案写到 `<某路径>` 文件里"。
4. 预期:主助理委派时带 `context_message_indexes`;在 Debug Inspector(/debug)查看子会话首条 user 消息,应含"【主对话相关原文】"块且方案原文逐字一致;落盘文件内容与方案一致,非编造。
5. 复杂任务变体:诱导 complex 路由(多步任务),在任务落库后检查 task detail 的 description 已是展开全文(无下标残留);重启 sidecar 后让任务继续执行,执行体仍拿到全文。

## 关键断言点(实现自检清单)

- [x] 快照仅在 AgentLoop LLM 路径设置;恢复/initial 路径带下标委派报"快照不可用"。
- [x] 下标按完整可见数组 1-based 计数,但引用 system 消息会因能力目录隔离而整体拒绝。
- [x] 展开块逐字等于原消息 content;超限报错不截断。
- [x] `delegate_to_specialist` 的 execution_context 进入 `_format_delegated_task_input` 第二参数。
- [x] `TaskExecutorAdapter._run_specialist` 传递 `task.description`(修复静默丢弃)。
- [x] 未带 `context_message_indexes` 的既有委派测试全绿;异步 specialist 的
  description/checkpoint 交接属于已记录、已有专门测试的兼容性例外。
- [x] 配置键经 `get_unified_config()` 读取,config 模板含默认值。

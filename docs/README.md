# 文档管理规范

## 文档分类与规则

### 活文档（随代码持续更新）

描述系统**当前是什么**，读者是"现在想理解这个系统的人"。

| 文件 | 内容 | 更新触发条件 |
|------|------|------------|
| `../.specify/memory/constitution.md` | 项目治理、不可协商原则、Speckit 门禁 | 原则、门禁或交付流程变化时更新 |
| `ARCHITECTURE.md` | 整体架构、Agent 分工、数据流、设计原则 | 架构变更时必须同步更新 |
| `PROJECT_CONSTRAINTS.md` | 开发约束、规范、禁止模式 | 引入新约束或发现新反模式时更新 |
| `../AGENTS.md` / `../CLAUDE.md` | AI 开发指南（核心约束摘要） | 与 constitution / PROJECT_CONSTRAINTS.md 同步 |

**更新规则**：直接改，不留旧内容，不写"原来是X，现在是Y"。历史在 git 里。

---

### 设计文档（写完即归档，不再修改）

描述**为什么这样决定**，是不可变的决策记录。代码与设计文档有出入时，**以代码为准**。

位于 `design/` 目录：

| 文件 | 内容 |
|------|------|
| `design/data_layer_design.md` | 消息存储结构、会话表设计 |
| `design/memory_mechanism_design.md` | 引用替换机制、压缩策略 |
| `design/agent_loop_design.md` | AgentLoop 循环引擎设计 |
| `design/event_system_design.md` | 事件系统与流程编排 |
| `design/pm_agent_design.md` | PM Agent 工具集与 Prompt 设计 |
| `design/programmer_agent_design.md` | 程序员 Agent 工具集与代码规范 |
| `design/trial_agent_design.md` | 试用 Agent 设计 |
| `design/llm_review_design.md` | LLM Review 机制 |
| `design/recording_tools_redesign_todo.md` | 录制数据工具重设计 |

**更新规则**：不修改原文档。设计被推翻时：
1. 在原文档头部加 `> ⚠️ 此设计已被 [新文档名] 取代`
2. 新建文档，说明原设计哪里不够用、为什么、新方案是什么

---

### 过程文档（不进版本库）

开发过程中的临时产物（计划、报告、会话记录等）放在 `docs/local/`，已加入 `.gitignore`。

---

## 架构重大变更时的操作流程

1. 先在 `design/` 下写设计文档，说明原架构的问题和新方案
2. 再更新 `ARCHITECTURE.md` 到新状态
3. 同步更新 `PROJECT_CONSTRAINTS.md` 中受影响的约束

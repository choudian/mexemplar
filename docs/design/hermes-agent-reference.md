# Hermes Agent 参考调研

> 源码位置：`E:\work\taiji\code\opensource\hermes-agent`
> 调研目的：梳理 hermes-agent 相比 Exemplar 多出的工具和 skill，评估哪些值得引入。

---

## 背景：Skill vs Tool vs Specialist 的概念对齐

| 概念 | hermes | Exemplar |
|------|--------|----------|
| Tool | 可执行代码单元，直接调用 | 同，已有若干内置工具 |
| Skill | `SKILL.md` markdown 文档（Prompt 为主体），可选附 `scripts/`；`/skill-name` 触发时整体注入为 user message | 目前无 skill 系统 |
| Agent/Specialist | 拥有独立 system prompt + 工具子集的执行单元 | Specialist（专员），100% 调度模式 |

**Skill 的核心特征**（hermes 设计）：
- 本质是 Prompt，不是代码
- `SKILL.md` frontmatter：`name / description / version / tags / related_skills`
- 可选子目录：`references/`（知识库）、`templates/`（模板）、`scripts/`（辅助脚本）
- 专员可以"装备"多个 skill，skill 组合成专员的 system prompt

**Skill 的自动归纳机制**（hermes）：
- 每轮对话结束后，后台 fork 一个独立 AIAgent（只有 `skill_manage` 权限）
- 该 agent 审查本轮对话，判断是否新建/更新 skill
- 优先级：更新已加载的 skill → 更新已有同类 → 添加 support file → 新建 class-level skill
- 产出标记为 `background_review` 来源；Curator（每 7 天）负责合并/归档低频 skill
- 用户指派 agent 创建的 skill 标记为 `foreground`，Curator 永不触碰

---

## 工具（Tools）— Hermes 有、Exemplar 没有

### 高相关（办公助理场景）

| 工具 | 做什么 | 引入价值 |
|------|--------|---------|
| `clarify_tool` | 结构化多选问题向用户确认，最多 4 选项 + "Other" 自由输入 | 比当前模态确认更轻量，适合助理收集用户意图 |
| `checkpoint_manager` | 每轮操作前对工作目录做 shadow git 快照，支持回滚；单一 bare repo 去重存储 | 桌面自动化前快照文件状态，操作失败时回滚 |
| `session_search_tool` | FTS5 全文检索历史对话 session，支持按 session 上下文滚动 | 补充大脑 archive zone，提供跨 session 的对话级检索 |
| `todo_tool` | 任务清单管理（类 TodoWrite） | 助理跟踪多步任务进度 |
| `browser_tool` + `browser_cdp_tool` | 浏览器自动化（CDP 协议） | 补充桌面录制之外的 Web 操作能力 |
| `kanban_tools` | 任务看板管理（agent 可读写任务状态） | 专员调度的任务状态管理 |
| `cronjob_tools` | 定时任务创建和管理 | 助理定时执行任务（周报、提醒等） |
| `feishu_doc_tool` + `feishu_drive_tool` | 飞书文档/云盘读写 | 国内办公场景高频，直接可用 |
| `microsoft_graph_client` | Office 365 / Teams / SharePoint 集成 | 企业办公场景 |
| `skill_manager_tool` + `skills_tool` | Skill 的创建、编辑、删除、检索 | Exemplar 建立 skill 系统的基础设施 |
| `tts_tool` | 文字转语音 | 语音播报能力 |
| `transcription_tools` | 音频转文字 | 会议记录、语音指令 |

### 中相关

| 工具 | 做什么 | 备注 |
|------|--------|------|
| `image_generation_tool` | 图片生成（fal.ai） | 需要外部服务 |
| `send_message_tool` | 跨平台发消息（Telegram/Slack/邮件等） | 助理主动通知用户 |
| `mixture_of_agents_tool` | 多模型并行回答 + 聚合（MoA） | 重，需 OpenRouter；复杂推理场景 |
| `osv_check` | 依赖包安全漏洞检查（OSV 数据库） | 代码相关任务的安全检查 |

### 低相关（Exemplar 有自己方案）

| 工具 | 备注 |
|------|------|
| `computer_use_tool` | Exemplar 有自己的录制/执行系统 |
| `code_execution_tool` | Exemplar 已有 `execute_code` |
| `discord_tool` / `homeassistant_tool` / `x_search_tool` | 特定平台，当前场景不符 |

---

## Skill — Hermes 有、Exemplar 完全没有

Exemplar 目前无 skill 系统，以下是 hermes 所有 skill 按相关度分类。

### 高相关

| Skill | 分类 | 做什么 |
|-------|------|--------|
| `spike` | software-development | 正式建模"探索性实验"：分解可行性问题 → 研究 → 构建 → 出 VALIDATED/PARTIAL/INVALIDATED 裁定 |
| `systematic-debugging` | software-development | 调试方法论，结构化排查流程 |
| `subagent-driven-development` | software-development | 多 agent 并行开发方法论 |
| `kanban-orchestrator` + `kanban-worker` | devops | 任务看板调度 + worker 拉单执行，含状态机设计 |
| `ocr-and-documents` | productivity | 文档 OCR 和处理方法论 |
| `nano-pdf` | productivity | PDF 读取和分析 |
| `powerpoint` | productivity | PPT 处理 |
| `google-workspace` | productivity | Google 文档/表格/日历 操作 |
| `teams-meeting-pipeline` | productivity | Teams 会议全流程 |
| `notion` | productivity | Notion 操作方法论 |
| `linear` | productivity | Linear issue 管理（附 `scripts/linear_api.py`） |
| `airtable` | productivity | Airtable 操作 |

### 中相关

| Skill | 分类 | 做什么 |
|-------|------|--------|
| `github-code-review` | github | PR 代码审查流程 |
| `github-pr-workflow` | github | PR 创建和管理流程 |
| `github-issues` | github | Issue 管理 |
| `github-repo-management` | github | 仓库管理 |
| `codebase-inspection` | github | 代码库探查方法论 |
| `arxiv` | research | 论文检索（无需 API key，纯 curl） |
| `research-paper-writing` | research | 研究写作方法论 |
| `jupyter-live-kernel` | data-science | Jupyter notebook 操作 |
| `writing-plans` + `plan` | software-development | 规划方法论 |
| `requesting-code-review` | software-development | 发起代码审查的方法论 |
| `maps` | productivity | 地图/路线查询 |

### 低相关

Creative（作图/动画/像素画）、gaming、smart-home、social-media、MLOps（模型训练/评估）——Exemplar 当前场景不涉及。

---

## Delegate Tool 的关键设计细节

hermes `delegate_tool` 的 `BLOCKED_TOOLS` 硬编码值得借鉴：

```python
DELEGATE_BLOCKED_TOOLS = frozenset([
    "delegate_task",   # 禁止递归调度
    "clarify",         # 子 agent 不能向用户提问
    "memory",          # 子 agent 不能写共享 memory
    "send_message",    # 禁止跨平台副作用
    "execute_code",    # 子 agent 应逐步推理而非写脚本
])
```

Exemplar 专员调度目前是否有类似硬约束？建议对照检查。

---

## 后续待评估

- [ ] `clarify_tool` → 助理确认流程改造
- [ ] `checkpoint_manager` → 桌面操作前文件快照
- [ ] `session_search_tool` → 跨 session 检索补充大脑
- [ ] `feishu_doc_tool` + `feishu_drive_tool` → 飞书集成
- [ ] Skill 系统设计（参考 hermes skill_manager_tool + background_review 机制）
- [ ] `spike` skill → 引入探索性实验方法论
- [ ] `kanban-orchestrator` → 专员任务调度状态机参考

---

# OpenClaw 参考调研

> 源码位置：`E:\work\taiji\code\opensource\openclaw`
> 调研目的：梳理 OpenClaw 的 skill / extension 设计，补充 Exemplar skill 系统的参考依据。

---

## Skill 系统设计要点

**目录结构**（每个 skill 一个目录）：
```
skill-name/
  SKILL.md         ← 主体：frontmatter + 方法论正文
  scripts/         ← 可选，确定性辅助脚本
  references/      ← 可选，长文档/示例，按需加载
  assets/          ← 可选，模板/媒体
```

**SKILL.md frontmatter**：`name` + `description`（触发条件，必须简短） + 可选 `metadata`（依赖工具、安装指令、emoji）

**关键设计原则**：
- `description` 是路由信号——LLM 靠它判断是否加载，必须是名词短语触发条件
- body 按需加载，frontmatter 永远可见，保持上下文 lean
- 只保留脆性知识（命令语法、认证注意、安全规则），不写 LLM 本来就懂的东西
- scripts/ 放确定性脚本，不塞进 SKILL.md

---

## Skill 自动归纳机制（skill-workshop 扩展）

OpenClaw 通过 `skill-workshop` 插件实现自动 skill 捕获，每轮 `agent_end` 后触发：

**两种检测模式**（可组合为 `hybrid`）：
- **heuristic**：基于用户纠正行为、重复指令等信号，低成本快速捕获
- **llm**：满足阈值（每 N 轮或 M 次 tool call）后用 LLM 分析整段对话，提取可复用 workflow

**审批策略**（`approvalPolicy`）：
- `pending`（默认）：存为待审建议，用户手动确认才写入
- `auto`：直接写入 skill 文件

**可配置项**：
```json
{
  "autoCapture": true,
  "reviewMode": "hybrid",
  "reviewInterval": 15,
  "reviewMinToolCalls": 8,
  "approvalPolicy": "pending"
}
```

与 Hermes 的 `background_review` 对比：OpenClaw 走插件系统（可关闭），Hermes 是内置 fork agent；两者都是"自动发现 + 用户把关"模式，OpenClaw 的 pending 队列更显式。

---

## Skills 清单（57 个）

### 高相关（办公助理 / Exemplar 场景）

| Skill | 分类 | 做什么 |
|-------|------|--------|
| `skill-creator` | 元技能 | 创建/编辑/校验 SKILL.md 文件，是 skill 工厂的基础 |
| `coding-agent` | 开发 | 派发编码任务给 Claude Code / Codex / OpenCode / Pi 后台执行 |
| `taskflow` | 任务编排 | 多步骤持久化任务：owner session、等待/恢复、子任务链接 |
| `taskflow-inbox-triage` | 任务编排 | 收件箱分类路由的 TaskFlow 具体模式（示例） |
| `github` | 开发 | GitHub CLI：issue / PR / CI / 评论 / 审查 / 发布 |
| `gh-issues` | 开发 | 拉 issue → 派后台修复 agent → 开 PR 闭环 |
| `session-logs` | 大脑/检索 | 用 jq 搜索分析自身历史对话日志（跨 session 检索） |
| `oracle` | 开发 | 第二模型对指定文件做代码审查/重构/设计 |
| `summarize` | 内容处理 | 摘要/转写 URL / YouTube / 播客 / PDF / 本地文件 |
| `notion` | 生产力 | Notion 页面/数据库/文件/评论 |
| `obsidian` | 生产力 | Obsidian vault 读写搜索笔记 |
| `trello` | 生产力 | Trello 看板/列表/卡片管理 |
| `gog` | Google | Gmail / Calendar / Drive / Contacts / Sheets / Docs |
| `nano-pdf` | 文件 | 自然语言指令编辑 PDF |
| `tmux` | 系统 | tmux 会话/窗格控制（交互 CLI 场景） |
| `mcporter` | 平台 | 列出/配置/调用 MCP 服务器工具 |
| `clawhub` | 平台 | ClawHub skill 市场搜索/安装/发布 |

### 中相关

| Skill | 分类 | 做什么 |
|-------|------|--------|
| `slack` | 通讯 | 发/读/编辑/删除消息、反应、置顶 |
| `discord` | 通讯 | 消息、投票、线程、媒体 |
| `imsg` | 通讯 | iMessage/SMS 收发（macOS） |
| `xurl` | 通讯 | X（Twitter）发帖/回复/DM/搜索 |
| `gemini` | AI | Gemini CLI 单次提示/摘要/生成 |
| `openai-whisper` | 语音 | 本地 Whisper 语音转文字（无需 API key） |
| `openai-whisper-api` | 语音 | OpenAI Audio Transcriptions API |
| `sag` | 语音 | ElevenLabs 文字转语音 |
| `sherpa-onnx-tts` | 语音 | 本地离线 TTS |
| `weather` | 信息 | 天气查询（wttr.in） |
| `blogwatcher` | 信息 | 监控博客/RSS 更新 |
| `goplaces` | 信息 | Google Places 搜索/详情/评价 |
| `1password` | 安全 | 1Password CLI 读取/注入密钥 |
| `healthcheck` | 运维 | 审计/加固主机安全 |
| `node-connect` | 系统 | 诊断 Android/iOS/macOS 节点配对 |

### 低相关（当前场景不涉及）

`blucli` / `sonoscli` / `spotify-player`（音响控制）、`openhue` / `eightctl`（智能家居）、`camsnap` / `video-frames` / `gifgrep` / `meme-maker` / `songsee`（媒体生成）、`wacli`（WhatsApp）、`ordercli`（外卖）、`peekaboo`（macOS UI 截图）

---

## Extensions 清单（28 个有描述）

### 高相关

| 扩展 | 做什么 | 对 Exemplar 的价值 |
|------|--------|-------------------|
| `Skill Workshop` | 自动捕获可复用 workflow 为 skill（heuristic + LLM，pending 审批） | **Exemplar skill 自动归纳机制的直接参考** |
| `Active Memory` | 对话前运行记忆 sub-agent，把相关记忆注入上下文 | brain context_builder 的参考设计 |
| `Memory Wiki` | 持久化 wiki 编译器 + Obsidian 知识库 | brain persistent zone 的知识沉淀参考 |
| `LLM Task` | 可从工作流调用的结构化 JSON LLM 工具 | 专员派发子任务的轻量工具参考 |
| `Lobster` | 带可恢复审批的类型化工作流工具 | 助理高危确认协议的参考实现 |
| `tokenjuice` | 压缩 exec/bash 工具结果节省 token | 工具输出压缩，降低上下文消耗 |
| `Web Readability Extraction` | 从 HTML 提取可读文章内容 | 网页摘要工具的预处理层 |
| `Document Extraction` | 本地文档附件文字提取 | 文件处理工具的基础能力 |
| `Webhooks` | 外部自动化绑定到 TaskFlow 的入站 webhook | 外部触发助理任务的入口设计 |
| `Meeting Notes` | 从频道录制自动生成会议摘要 | 录制层 → 文字摘要的管道参考 |

### 中相关

| 扩展 | 做什么 |
|------|--------|
| `Diffs` | 只读 diff 查看器和文件渲染 |
| `File Transfer` | 节点间文件读写（base64，最大 16MB） |
| `Claude Migration` | 从 Claude Code 迁移配置/记忆/skill |
| `ACPX Runtime` | 内嵌 ACP 运行时，管理 session 和 transport |
| `OC Path` | `oc://` 工作区文件寻址 |
| `Thread Ownership` | 防止多 agent 同时回复同一 Slack 线程 |
| `Phone Control` | 高危命令开关（含自动过期），防止误操作 |

### 低相关

`Azure Speech` / `Inworld` / `Talk Voice`（语音 TTS）、`Canvas`（实验性 UI 渲染）、`Google Meet`（视频会议）、`Bonjour`（mDNS 广播）、`Device Pairing`（设备配对）、`OpenShell Sandbox`（NVIDIA 沙箱）、`Codex`（GPT 模型目录）、`QA Matrix`（测试 transport）

---

## OpenClaw vs Hermes Skill 设计对比

| 维度 | Hermes | OpenClaw |
|------|--------|----------|
| 自动归纳 | 内置 fork agent，每轮对话后运行 | 插件（skill-workshop），可关闭 |
| 审批流 | `background_review` 标记，Curator 每 7 天合并 | pending 队列，用户随时审批 |
| 用户创建 | 指派 agent 创建，标记 `foreground` | skill-creator skill + `skill_workshop` 工具 |
| Skill 结构 | `SKILL.md` + `references/` + `templates/` + `scripts/` | 同，外加 `assets/` + `agents/` |
| 专员装备 skill | 专员 prompt 可引用多个 skill | 同（description 做路由信号） |
| 市场/分发 | 无内置市场 | ClawHub（`clawhub` skill） |

---

## OpenClaw 后续待评估

- [ ] `skill-workshop` 的 heuristic + LLM hybrid 检测逻辑 → Exemplar skill 自动归纳参考实现
- [ ] `taskflow` 的持久化任务状态机 → 专员长任务编排参考
- [ ] `Active Memory` 的 sub-agent 注入模式 → brain context_builder 改进参考
- [ ] `Lobster` 带审批工作流 → 高危确认协议对标
- [ ] `clawhub` skill 市场机制 → Exemplar skill 分发/共享方案参考
- [ ] `coding-agent` 的 notification route 协议 → 后台任务完成通知设计参考

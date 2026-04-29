# Implementation Plan: 聊天界面体验完善（Chat UI Polish）

**Branch**: `006-chat-ui-polish` | **Date**: 2026-04-28 | **Spec**: `specs/006-chat-ui-polish/spec.md` | **Status**: Completed
**Input**: Feature specification from `specs/006-chat-ui-polish/spec.md`

## Summary

本 feature 同时修复三类聊天界面体验问题：AI 回复以 Markdown 富文本展示、压缩前旧聊天记录按同一时间线可回看、欢迎页/新对话起始态隐藏“免确认” Toggle。实现策略是保持现有 `ChatWidget -> ChatService -> MessageRepository` 分层：UI 仅消费业务层提供的展示消息分页；Markdown 由 PyQt6/Qt 内建 `QTextDocument.setMarkdown()` 渲染并在 UI 层做安全降级；Toggle 只新增可见性状态，不改 004-auth-toast 的同步确认协议。

## Technical Context

**Language/Version**: Python >=3.11；本地 `.venv` PyQt6/Qt 为 6.11.0  
**Primary Dependencies**: PyQt6, SQLAlchemy, SQLite Repository, pytest；不新增 Markdown 解析依赖，优先使用 Qt `QTextDocument.setMarkdown(... MarkdownDialectGitHub)`  
**Storage**: SQLite `sessions` / `messages`；不新增表、列、迁移；不触碰 DuckDB  
**Testing**: pytest；UI 测试使用 PyQt6 offscreen/QTest；业务读取使用 Repository/Service 单元测试  
**Target Platform**: Windows 桌面 GUI（PyQt6）  
**Project Type**: desktop-app  
**Performance Goals**: 极长会话（>=1000 条旧消息）首屏加载 <=2s；滚动分页和输入期间单次 UI 阻塞 <=100ms；初始仅展示最近 10 条用户/助手展示消息  
**Constraints**: UI 不直接访问 Repository；完整历史回看不得改变压缩契约、LLM 上下文读取或 SQLite schema；Markdown 链接/图片不得触发外部导航、本地文件访问或脚本执行；“免确认”仍只保留进程会话级内存语义  
**Scale/Scope**: 单个 assistant 会话最多按 1000+ 条历史消息验证；改动集中在聊天 UI、聊天业务 Service、消息 Repository 查询和相关测试

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required |
|-----------|---------------|-------------------|
| I. Layered Boundaries & Event Coordination | PASS. 依赖方向保持 `UI -> business -> data`；不新增跨模块 blinker 事件；Toggle 继续复用现有 `ChatWidget` 信号和 `AgentHandlerMixin` 同步入口。 | 触达层：`src/ui/widgets/chat_widget.py`、`src/business/services/chat_service.py`、`src/data/repos/message_repository.py`；事件：无新增 |
| II. Data Boundary & Persistence Discipline | PASS. 历史展示通过 Repository 查询 SQLite `messages`，业务层包装后给 UI；不写业务直连 SQL；不触碰 DuckDB 或录制过滤边界。 | SQLite 只读查询；无 schema/migration；DuckDB N/A |
| III. Unified Config & Secret Handling | PASS. Markdown 渲染和完整历史回看默认启用，不新增配置；远程图片只按安全白名单显示，不新增密钥。 | Config N/A；Secrets N/A |
| IV. Verifiable Delivery | PASS. 计划包含 Markdown 渲染、安全降级、历史分页、Toggle 可见性和分层门卫测试。 | `tests/ui/test_chat_widget_markdown.py`、`tests/ui/test_chat_widget_history.py`、扩展 `tests/ui/test_chat_widget_auth_toggle.py`、`tests/data/test_message_repository.py` 或 Service 等价测试 |
| V. Living Docs & Spec-Driven Delivery | PASS. 受版本控制的 spec/plan/research/data-model/contracts/quickstart 将同步；当前运行结构若实现后出现新业务接口，最终按需更新 `docs/ARCHITECTURE.md` 或 `docs/PROJECT_CONSTRAINTS.md`。 | 本 feature 文档位于 `specs/006-chat-ui-polish/`；暂无 `docs/local/` 输出 |

## Project Structure

### Documentation (this feature)

```text
specs/006-chat-ui-polish/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── chat-ui-contract.md
└── tasks.md              # 由 /speckit.tasks 生成
```

### Source Code (repository root)

```text
src/
├── business/
│   └── services/
│       └── chat_service.py          # 暴露聊天展示消息分页，不让 UI 直连 Repository
├── data/
│   └── repos/
│       └── message_repository.py    # 增加只读分页查询，过滤 tool/summary/compressed
└── ui/
    ├── resources/
    │   └── styles.qss               # Markdown 内容、表格、代码块、Toggle 隐藏态样式
    └── widgets/
        └── chat_widget.py           # Markdown 气泡、历史分页、Toggle 可见性

tests/
├── data/
│   └── test_message_repository.py   # 或等价 Service 测试：分页/过滤/排序
└── ui/
    ├── test_chat_widget_auth_toggle.py
    ├── test_chat_widget_history.py
    └── test_chat_widget_markdown.py
```

**Structure Decision**: 选用现有聊天分层落点。`ChatWidget` 继续只负责界面和信号；`ChatService` 负责将用户可见聊天历史转换成展示用分页；`MessageRepository` 只提供 SQLAlchemy 只读查询。Markdown 渲染属于聊天气泡 UI 能力，不进入 Agent、ContextManager、压缩器或存储层。

## Complexity Tracking

无 constitution 例外。当前方案不新增项目、迁移、配置项或跨模块事件。

## Phase 0: Research

已生成 `specs/006-chat-ui-polish/research.md`，结论如下：

- Markdown 渲染使用 Qt 内建 Markdown 文档能力，避免引入新解析依赖；UI 渲染前统一安全降级 raw HTML / script。
- 历史回看新增展示专用分页接口，不能复用 `ContextManager.get_context()`，因为后者服务 LLM 上下文并过滤 archived。
- Toggle 只增加可见性状态机，不能改变 004-auth-toast 的 `request_id + threading.Event + pyqtSignal(str, str)` 同步确认协议。

## Phase 1: Design & Contracts

已生成：

- `specs/006-chat-ui-polish/data-model.md`
- `specs/006-chat-ui-polish/contracts/chat-ui-contract.md`
- `specs/006-chat-ui-polish/quickstart.md`

关键设计：

- `DisplayChatMessage` 为业务层返回给 UI 的展示 DTO：仅包含 `sequence`、`role`、`content`、`created_at` 等 UI 所需字段，不暴露 `is_archived` / `message_type` 给用户界面。
- `ChatHistoryPage` 为分页结果：`messages` 始终按升序展示，`has_more_before` 标识是否还能向上加载。
- Markdown AI 回复走 `MarkdownMessageView`（可作为 `ChatWidget` 内部 helper 或独立 widget），用户消息仍用纯文本路径。
- 合同文档定义 ChatService 历史分页、Markdown 渲染、安全降级和 Toggle 可见性行为。

## Constitution Check (Post-Design)

| Principle | Status | Post-design evidence |
|-----------|--------|----------------------|
| I. Layered Boundaries & Event Coordination | PASS | UI 仅调用 `ChatService`；不新增 blinker；现有 MainWindow/AgentHandlerMixin 信号协议不变 |
| II. Data Boundary & Persistence Discipline | PASS | 新查询限制在 `MessageRepository`；无 raw SQL、无 DuckDB、无 schema 变更 |
| III. Unified Config & Secret Handling | PASS | 不新增配置/密钥；远程图片不使用凭据 |
| IV. Verifiable Delivery | PASS | 已列出 UI、Service/Repository、分层门卫和安全降级测试 |
| V. Living Docs & Spec-Driven Delivery | PASS | 计划和 Phase 0/1 产物已在 `specs/006-chat-ui-polish/` 中生成 |

## Validation Commands

```powershell
uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py -q
uv run python -m pytest tests/ui/test_chat_widget_markdown.py tests/ui/test_chat_widget_history.py -q
uv run python -m pytest tests/data/test_message_repository.py -q
uv run python -m pytest tests/integration/test_assistant_new_session.py -q
uv run python -m py_compile src/ui/widgets/chat_widget.py src/business/services/chat_service.py src/data/repos/message_repository.py
git diff --check
```

若 `uv run` 在当前 Windows 环境继续因本机缓存权限失败，可使用 `.venv\Scripts\python.exe -m pytest ...` 和 `.venv\Scripts\python.exe -m py_compile ...` 作为等价本地验证入口，并在最终实现说明中记录原因。

## Phase 2 Preview

`/speckit.tasks` 应按 P1/P2/P3 独立切分任务：

1. Markdown 渲染 widget/helper 与安全降级测试。
2. 展示历史分页 Service/Repository 与 UI 向上滚动加载。
3. “免确认” Toggle 可见性状态机和既有同步语义回归。
4. 集成/门卫测试与最终验证命令。

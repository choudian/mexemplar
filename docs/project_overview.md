# Mexemplar 项目架构与功能概览

> 探索日期：2026-03-04

---

## 项目简介

**Mexemplar** 是一个桌面端智能办公助理，通过观察和学习用户的操作示例来理解工作流程，然后自动完成重复性任务。

**核心优势**：
- 🔒 默认本地存储，完全离线，数据安全可控
- 💰 极低成本：只在教学时消耗 Token，后续执行 0 成本
- ⚡ 一次学习，终身使用

---

## 整体架构设计

### 分层架构

```
应用层 (UI) → 业务层 → 抽象层 (接口) → 驱动层 → 数据层
```

**上层可调用下层，下层不能调用上层**（严格分层原则）

```
┌─────────────────────────────────────────────────────────────┐
│                    应用层 (Application Layer)                   │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 主窗口 (PyQt6) │  │ 工具管理界面 │  │ 录制控制界面 │    │
│  └────────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                    业务层 (Business Layer)                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │              LangGraph Agent 系统                        │   │
│  │  - 意图分析节点                                          │   │
│  │  - 意图确认节点                                          │   │
│  │  - 代码生成节点                                          │   │
│  │  - 工具匹配/执行节点                                     │   │
│  └────────────────────────────────────────────────────────┘   │
│  ┌────────────────────────────────────────────────────────┐   │
│  │              AI 处理模块                                │   │
│  │  - LLM 客户端 (多提供商支持)                             │   │
│  │  - 网络请求分析器                                        │   │
│  │  - 列表操作分析器                                        │   │
│  │  - 语义分析器                                            │   │
│  │  - 智能请求过滤 (规则引擎 + 模型)                         │   │
│  └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                   抽象层 (Abstraction Layer)                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │              IAutomationDriver (接口)                    │   │
│  │              IBrowserDriver (接口)                       │   │
│  │              IOfficeDriver (接口)                        │   │
│  └────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                    驱动层 (Driver Layer)                       │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │ Playwright Driver │  │ pywinauto Driver │                   │
│  │  (浏览器自动化)  │  │  (桌面自动化)   │                   │
│  └──────────────────┘  └──────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                    数据层 (Data Layer)                         │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │ SQLite Database  │  │   DuckDB         │                   │
│  │  (业务数据)       │  │  (录制数据)       │                   │
│  └──────────────────┘  └──────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

### 事件驱动架构

- 基于 `blinker` 信号系统
- 用于跨模块通信，避免紧耦合

**已定义事件**：
- `recording_started` / `recording_stopped` / `recording_completed`
- `workflow_processing_started` / `progress` / `completed`
- `tool_created` / `tool_updated` / `tool_executed`

---

## 目录结构

```
src/
├── main.py                      # 主入口点
├── abstraction/                 # 抽象层（接口定义）
├── application/                 # 应用层（PyQt6 UI）
├── business/                    # 业务逻辑层
│   ├── agent/                   # LangGraph Agent 系统
│   │   ├── graph.py             # 状态机定义
│   │   ├── state.py             # 状态定义
│   │   ├── nodes/               # 各节点实现
│   │   ├── prompts/             # 提示词
│   │   ├── checkpointer/        # 状态持久化
│   │   └── tools/               # Agent 工具
│   ├── ai/                      # AI 处理模块
│   │   ├── llm_client.py        # LLM 客户端
│   │   ├── semantic_analyzer.py # 语义分析器
│   │   ├── vision_analyzer.py   # 视觉分析器
│   │   ├── workflow_generator.py # 工作流生成器
│   │   └── preprocessing/       # 数据预处理
│   │       ├── analyzers/       # 各分析器
│   │       └── models.py        # 数据模型
│   ├── intent/                  # 意图分析模块
│   ├── tool_trial/              # 工具试验/修复模块
│   └── workflow/                # 工作流模块
├── drivers/                     # 驱动层
│   ├── locator/                 # 元素定位器
│   └── windows/                 # Windows 平台驱动
├── recording/                   # 录制模块
│   ├── recorder.py              # 录制器主逻辑
│   ├── websocket_server.py      # WebSocket 服务器
│   └── browser_extension/       # 浏览器扩展
├── execution/                   # 执行引擎
│   ├── executor.py              # 执行器
│   ├── action_executor.py       # 动作执行器
│   ├── code_executor.py         # 代码执行器
│   ├── parameter_resolver.py    # 参数解析器
│   └── retry_handler.py         # 重试处理
├── communication/               # 通信模块
│   └── websocket_manager.py     # WebSocket 管理
├── ui/                          # UI 层
│   ├── pending_tools_ui.py      # 待处理工具界面
│   └── resources/               # 资源文件
├── data/                        # 数据层
│   ├── sqlalchemy_manager.py    # SQLAlchemy 管理
│   ├── duckdb_manager.py        # DuckDB 管理
│   ├── models_duckdb.py         # 数据模型
│   └── unified_config.py        # 统一配置管理
└── utils/                       # 工具函数
    ├── events.py                # 事件系统
    ├── logger.py                # 日志系统
    └── debug_log.py             # 调试日志

config/                          # 配置文件
docs/                            # 文档
tests/                           # 测试文件
```

---

## 核心模块详解

### 1. LangGraph Agent 系统

**位置**: `src/business/agent/`

#### 图定义 (graph.py)
支持 3 种对话类型的状态机：

1. **工具生成流程**
   ```
   intent_analysis → intent_confirmation → code_generation → END
   ```

2. **任务执行流程**
   ```
   intent_understanding → tool_matching → tool_confirmation → tool_execution → END
   ```

3. **普通对话**
   ```
   chat → END
   ```

#### 状态定义 (state.py)
继承 `MessagesState`，包含自定义字段：

- `recording_data`: 录制数据（输入）
- `current_intent`: 意图分析结果
- `tool_draft`: 工具草稿
- `execution_result`: 执行结果
- `error_info`: 错误信息
- `requires_user_confirmation`: 是否需要用户确认
- `confirmation_progress`: 分页确认进度状态

#### 节点实现 (nodes/)
- `intent_analysis.py`: 意图分析节点
- `intent_confirmation.py`: 意图确认节点
- `code_generation.py`: 代码生成节点
- `code_repair.py`: 代码修复节点
- `tool_matching.py`: 工具匹配节点
- `tool_execution.py`: 工具执行节点
- `chat.py`: 聊天节点

#### 状态持久化 (checkpointer/)
- SQLite checkpointer 用于持久化 Agent 状态

---

### 2. 事件系统

**位置**: `src/utils/events.py`

基于 `blinker` 的事件总线，提供解耦的事件驱动架构。

**使用示例**：
```python
# 发送事件
from src.utils.events import recording_completed
recording_completed.send(sender=self, session_id="123")

# 监听事件
from src.utils.events import listen_to

@listen_to('recording_completed')
def handle_recording(sender, **kwargs):
    session_id = kwargs.get('session_id')
    # 处理逻辑
```

---

### 3. 录制系统

**位置**: `src/recording/`

- WebSocket 服务器 (`websocket_server.py`)
- 录制器主逻辑 (`recorder.py`)
- 浏览器扩展通信

**核心流程**：
1. 启动 WebSocket 服务器
2. 启动 Playwright 浏览器（加载扩展）
3. 扩展自动连接 WebSocket
4. 用户操作 → 扩展捕获 → WebSocket → 队列文件
5. 停止录制 → 保存到 DuckDB
6. 发送 `recording_completed` 事件

---

### 4. AI 处理模块

**位置**: `src/business/ai/`

#### LLM 客户端 (llm_client.py)
- 支持多提供商：Anthropic Claude、OpenAI
- LangChain 统一接口

#### 分析器 (preprocessing/analyzers/)
- `intelligence_analyzer.py`: 智能分析器
- `network_analyzer.py`: 网络请求分析器
- `list_analyzer.py`: 列表操作分析器

#### 语义分析器 (semantic_analyzer.py)
- 5 步 Chain-of-Thought 深度分析
- 理解操作意图和业务逻辑

---

### 5. 执行引擎

**位置**: `src/execution/`

- `executor.py`: 主执行器
- `action_executor.py`: 动作执行器
- `code_executor.py`: 代码执行器
- `parameter_resolver.py`: 参数解析器
- `retry_handler.py`: 重试处理

---

### 6. 数据层

**位置**: `src/data/`

#### 双数据库架构

**SQLite** (业务数据)：
- 工具定义
- 执行记录
- 对话历史
- 全局设置

**DuckDB** (录制数据)：
- 录制会话
- 操作序列
- 网络请求
- 兄弟元素快照
- 列表上下文

**优势**：
- SQLite：适合事务、查询、持久化
- DuckDB：列式存储，分析查询快 10-100 倍

#### 统一配置管理 (unified_config.py)
- 配置优先级：Database > File > Code
- 敏感信息使用 keyring 加密存储
- 支持配置热更新

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| UI 框架 | PyQt6 |
| 浏览器自动化 | Playwright |
| 桌面自动化 | pywinauto |
| AI 框架 | LangGraph, LangChain |
| AI 模型 | Claude Sonnet 4.5, Claude Haiku |
| 事件系统 | blinker |
| 数据库 | SQLite, DuckDB |
| 数据库 ORM | SQLAlchemy |
| 包管理 | uv |
| 测试 | pytest |

---

## 核心约束（必须遵守）

### 1. 严格分层架构
```
应用层 → 业务层 → 抽象层 → 驱动层 → 数据层
```
上层可调用下层，下层不能调用上层

### 2. 事件驱动用于跨模块通知
- 适用：录制完成 → 触发 AI 处理
- 不适用：同一模块内方法调用、需要同步返回结果

### 3. 数据库访问必须通过 Repository
不要在业务代码中直接执行 SQL

### 4. 配置通过 UnifiedConfigManager 管理
不要硬编码配置，不要直接读取 config.json

### 5. 敏感信息必须用 keyring
API Key 等敏感信息不能硬编码或放在配置文件中

---

## 开发状态

### 已完成 ✅
- 项目架构和目录结构
- LangGraph Agent 系统（3 种对话类型）
- 事件驱动架构
- 浏览器录制（基于扩展 + WebSocket）
- AI 工作流生成系统
- 网络请求智能过滤
- PyQt6 图形用户界面
- 执行引擎基础框架

### 开发中 🚧
- 执行引擎完整实现（约 40% 完成）

### 计划中 ⏳
- AI 对话交互
- 定时任务调度
- 工具分享和导入导出
- 条件分支和循环支持

---

## 相关文档

- `CLAUDE.md` - 项目开发指南和核心约束
- `docs/PROJECT_CONSTRAINTS.md` - 详细约束文档
- `docs/architecture.md` - 架构文档
- `docs/event_driven_architecture.md` - 事件驱动架构
- `docs/feature_plans.md` - 功能开发计划
- `README.md` - 项目说明

---

## 关键文件路径

| 功能 | 文件路径 |
|------|----------|
| Agent 图定义 | `src/business/agent/graph.py` |
| Agent 状态 | `src/business/agent/state.py` |
| 事件系统 | `src/utils/events.py` |
| LLM 客户端 | `src/business/ai/llm_client.py` |
| 数据库管理 | `src/data/sqlalchemy_manager.py` |
| 统一配置 | `src/data/unified_config.py` |
| 主入口 | `src/main.py` |
| 主窗口 | `src/ui/main_window.py` |
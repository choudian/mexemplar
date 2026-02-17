# Mexemplar 架构文档

**最后更新**: 2026-01-23
**架构版本**: v2.0（事件驱动 + WebSocket）

---

## 📋 目录

- [架构概览](#架构概览)
- [分层架构](#分层架构)
- [模块关系图](#模块关系图)
- [核心模块详解](#核心模块详解)
- [数据流架构](#数据流架构)
- [事件驱动架构](#事件驱动架构)
- [技术选型](#技术选型)

---

## 架构概览

Mexemplar 采用**分层架构** + **事件驱动**的设计模式，确保模块间松耦合，易于扩展和维护。

```
┌─────────────────────────────────────────────────────────────┐
│                    应用层 (Application Layer)                   │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 主窗口 (PyQt6) │  │ 工具管理界面 │  │ 录制控制界面 │    │
│  └────────────────┘  └──────────────┘  └──────────────┘    │
│                        ↓                                     │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                    业务层 (Business Layer)                     │
│  ┌────────────────────────────────────────────────────────┐   │
│  │                  WorkflowOrchestrator                      │   │
│  │  - 数据预处理（DataPreprocessorV2）                      │   │
│  │  - 智能过滤（RequestIntelligenceAnalyzer）               │   │
│  │  - 网络分析（NetworkAnalyzer、ListOperationAnalyzer）      │   │
│  │  - 代码生成（SemanticAnalyzer + PromptsV2）              │   │
│  │  - 保存工具（Repository）                                  │   │
│  └────────────────────────────────────────────────────────┘   │
│                        ↓                                     │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                   抽象层 (Abstraction Layer)                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │              IAutomationDriver (接口)                    │   │
│  │              IBrowserDriver (接口)                       │   │
│  └────────────────────────────────────────────────────────┘   │
│                        ↓                                     │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                    驱动层 (Driver Layer)                       │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │ Playwright Driver │  │ pywin32 Driver   │                   │
│  │  (浏览器自动化)  │  │  (桌面自动化)   │                   │
│  └──────────────────┘  └──────────────────┘                   │
│                        ↓                                     │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                    数据层 (Data Layer)                         │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │ SQLite Database  │  │   DuckDB         │                   │
│  │  (业务数据)       │  │  (录制数据)       │                   │
│  └──────────────────┘  └──────────────────┘                   │
│                        ↓                                     │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│                    工具层 (Utility Layer)                      │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │ Config Manager   │  │ Event System     │                   │
│  │ (配置管理)       │  │  (blinker)        │                   │
│  └──────────────────┘  └──────────────────┘                   │
│  ┌──────────────────┐  ┌──────────────────┐                   │
│  │ Logger          │  │ Debug Log        │                   │
│  │  (日志系统)      │  │  (调试日志)       │                   │
│  └──────────────────┘  └──────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 分层架构

### 应用层（Application Layer）

**职责**：提供用户界面和交互

**组件**：
- PyQt6 主窗口
- 工具管理界面
- 录制控制界面
- 对话交互界面

**状态**：🚧 开发中

---

### 业务层（Business Layer）

**职责**：核心业务逻辑，跨平台通用

**核心模块**：

#### 1. WorkflowOrchestrator（工作流编排器）

**位置**: `src/business/ai/workflow_orchestrator.py`

**职责**：
- 协调录制后处理流程
- 事件驱动处理（监听 `recording_completed` 事件）
- 集成各个分析器

**处理流程**：
```
录制完成事件
  ↓
1. 数据预处理（DataPreprocessorV2）
   - 操作合并、去重、过滤
   - 根据压缩级别决定是否使用数据压缩模型
  ↓
2. 智能网络请求过滤（RequestIntelligenceAnalyzer）
   - 规则引擎：30+ 条规则
   - 数据压缩模型：边缘案例分析
   - 加密检测、依赖分析
  ↓
3. 网络请求分析（NetworkAnalyzer）
   - 判断 API 可复现性
   - 提取响应结构
  ↓
4. 列表操作分析（ListOperationAnalyzer）
   - 识别列表操作
   - 关联网络请求
   - 生成匹配策略
  ↓
5. LLM 代码生成（SemanticAnalyzer + PromptsV2）
   - 5步 Chain-of-Thought
   - 生成 Python 执行代码
  ↓
6. 保存工具定义（ToolRepository）
```

#### 2. 数据预处理器（DataPreprocessorV2）

**位置**: `src/business/ai/data_preprocessor.py`

**职责**：
- 数据压缩（4级压缩策略）
- 操作合并（中文输入法优化）
- 过滤重复和无效操作

**压缩级别**：
- `NONE`: 0% 压缩
- `CONSERVATIVE`: 60-70% 压缩（仅规则引擎）
- `MODERATE`: 70-80% 压缩（规则引擎 + 模型）
- `AGGRESSIVE`: 80-90% 压缩（规则引擎 + 模型）

#### 3. 智能分析器模块

**网络请求分析器** (`network_analyzer.py`):
- API 可复现性判断
- 响应结构提取（list、dict_with_list、object）

**列表操作分析器** (`list_operation_analyzer.py`):
- 列表操作识别
- API vs DOM 匹配策略

**请求智能分析器** (`request_intelligence_analyzer.py`):
- 规则引擎（域名、URL、内容类型）
- 数据压缩模型集成
- 加密检测、依赖分析

#### 4. LLM 客户端和代码生成

**通用 LLM 客户端** (`llm_client.py`):
- 支持 Anthropic、OpenAI
- LangChain 统一接口

**代码生成提示词 V2** (`prompts/code_generation_prompt_v2.py`):
- 5步 Chain-of-Thought
- 4个 Few-Shot 示例（API、列表匹配、浏览器、混合）
- 约 11,000 tokens

**代码执行器** (`execution/code_executor.py`):
- 沙箱执行环境
- 模块白名单限制

---

### 抽象层（Abstraction Layer）

**职责**：定义接口契约，隔离平台差异

**接口定义**：
- `IAutomationDriver` - 自动化驱动接口
- `IBrowserDriver` - 浏览器驱动接口
- `IOfficeDriver` - Office 应用驱动接口

**状态**：✅ 接口已定义

---

### 驱动层（Driver Layer）

**职责**：平台特定实现，可替换

**浏览器驱动**：
- Playwright：Chrome/Edge 自动化
- 事件捕获：浏览器扩展（WebSocket 通信）

**桌面应用驱动**：
- pywinauto：Windows UI 自动化
- 多层次定位器：DOM → 坐标 → 图像识别

**状态**：✅ 浏览器驱动已完成，🚧 桌面驱动部分完成

---

### 数据层（Data Layer）

**职责**：统一数据访问接口，数据持久化

**双数据库架构**：

#### SQLite（业务数据）

**位置**: `~/.exemplar/exemplar.db` 或 `%APPDATA%/Mexemplar/data/exemplar.db`

**表结构**：
- `tools` - 工具定义（包含 execution_code）
- `task_executions` - 任务执行记录
- `conversations` - 对话历史
- `app_settings` - 全局设置
- `user_preferences` - 用户偏好

#### DuckDB（录制数据）

**位置**: `data/mexemplar.duckdb`

**表结构**：
- `recording_sessions` - 录制会话
- `actions` - 操作序列
- `network_requests` - 网络请求
- `sibling_snapshots` - 兄弟元素快照

**优势**：
- 列式存储，分析查询快 10-100 倍
- 支持复杂 SQL 分析
- 适合大规模录制数据

---

## 模块关系图

### 核心业务流程

```
用户操作
  ↓
BrowserRecorder.start_recording()
  ↓
WebSocket 连接 + 浏览器扩展
  ↓
用户在浏览器中操作
  ↓
插件捕获事件 → WebSocket → 队列文件
  ↓
BrowserRecorder.stop_recording()
  ↓
emit('recording_completed', session)
  ↓
WorkflowOrchestrator 监听事件
  ↓
process_recording_v2(session)
  ├─→ DataPreprocessorV2.preprocess_with_analysis()
  │    ├─→ 规则过滤
  │    └─→ RequestIntelligenceAnalyzer.analyze_requests()
  │         ├─→ 规则引擎
  │         └─→ 数据压缩模型（可选）
  ├─→ NetworkAnalyzer + ListOperationAnalyzer
  ├─→ SemanticAnalyzer.generate_workflow()
  │    └─→ 使用 PromptsV2
  └─→ ToolRepository.save()
  ↓
生成工具定义（包含 execution_code）
```

### 模块依赖关系

```
WorkflowOrchestrator
  ├─→ DataPreprocessorV2
  ├─→ RequestIntelligenceAnalyzer
  │    └─→ LangChainLLMClient
  ├─→ NetworkAnalyzer
  ├─→ ListOperationAnalyzer
  ├─→ SemanticAnalyzer
  │    └─→ ClaudeClient (Anthropic)
  └─→ CodeExecutor
       └─→ ToolRepository
            ├─→ SQLite DatabaseManager
            └─→ DuckDBManager
```

---

## 数据流架构

### 录制到工具生成的完整数据流

```
┌─────────────────────────────────────────────────────────────┐
│                      录制阶段                              │
└─────────────────────────────────────────────────────────────┘
                        ↓
用户在浏览器操作
  ↓
浏览器扩展捕获事件（8种事件类型）
  ├─ click, input, submit, change, dblclick, contextmenu
  ├─ keydown (特殊键), navigate (前进/后退)
  └─ 增强数据（DOM树、兄弟元素、视觉特征）
  ↓
WebSocket 实时传输
  ↓
队列文件 (JSONL 格式)
  ↓
┌─────────────────────────────────────────────────────────────┐
│                    保存到 DuckDB                           │
│  recording_sessions ← actions ← network_requests           │
│  sibling_snapshots                                          │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│              停止录制，emit('recording_completed')          │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│                  智能分析阶段                              │
└─────────────────────────────────────────────────────────────┘
                        ↓
1. 数据预处理（压缩 70-90%）
2. 智能网络请求过滤
3. 网络请求分析（可复现性、结构）
4. 列表操作分析（API vs DOM）
  ↓
┌─────────────────────────────────────────────────────────────┐
│                   LLM 代码生成                              │
│  PromptsV2 + Claude API → Python 执行代码                      │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│                  保存到 SQLite                              │
│  tools 表（包含 execution_code）                                  │
└─────────────────────────────────────────────────────────────┘
```

---

## 事件驱动架构

### 事件发布-订阅模式

```
┌────────────────┐
│  Recorder       │  emit('recording_completed')
│  (录制器)       │  ───────────────────────┐
└────────────────┘                          │
                                               ↓
┌────────────────────────────────────────────────┐
│            EventBus (blinker)                  │
│  ┌────────────────────────────────────────┐ │
│  │                                        │ │
│  │  ←─ WorkflowOrchestrator (监听器1)      │ │
│  │  ←─ DatabaseLogger (监听器2)           │ │
│  │  ←─ Notifier (监听器3)                 │ │
│  │                                        │ │
│  └────────────────────────────────────────┘ │
└────────────────────────────────────────────┘
```

### 已定义事件

| 事件 | 触发时机 | 数据 |
|------|---------|------|
| `recording_started` | 录制开始 | `RecordingEventData` |
| `recording_stopped` | 录制停止 | `RecordingEventData` |
| `recording_completed` | 录制完成（数据准备就绪） | `session: RecordingSession` |
| `recording_failed` | 录制失败 | `error: str` |
| `workflow_processing_started` | 工作流处理开始 | `session_id: str` |
| `workflow_processing_progress` | 处理进度更新 | `percent, step_name, message` |
| `workflow_processing_completed` | 处理完成 | `tool_id, tool_name, ...` |
| `tool_created` | 工具创建 | `tool_data` |
| `tool_executed` | 工具执行 | `execution_result` |

**优势**：
- ✅ 松耦合：录制器无需知道谁在处理
- ✅ 可扩展：可以添加多个监听器
- ✅ 灵活：动态订阅/取消订阅

详见：[事件驱动架构详细说明](docs/event_driven_architecture.md)

---

## 核心模块详解

### 1. 浏览器录制模块

**架构**：WebSocket + 浏览器扩展

**流程**：
```
BrowserRecorder.start_recording()
  ↓
启动 WebSocket 服务器 (ws://127.0.0.1:8765)
  ↓
启动 Playwright 浏览器（加载扩展）
  ↓
扩展自动连接 WebSocket
  ↓
发送 START_RECORDING 命令
  ↓
用户操作 → 扩展捕获 → WebSocket → 队列文件
  ↓
stop_recording() → 读取队列 → 保存到 DuckDB
```

**关键文件**：
- `src/recording/browser_recorder.py` - 录制器主逻辑
- `src/recording/websocket_server.py` - WebSocket 服务器
- `src/recording/browser_extension/` - 浏览器扩展

### 2. AI 代码生成模块

**架构**：分析器 + 提示词 + LLM

**分析器链**：
```
NetworkAnalyzer → 识别可复现 API
    ↓
ListOperationAnalyzer → 识别列表操作
    ↓
PromptsV2 → 构建提示词
    ↓
Claude API → 生成 Python 代码
    ↓
CodeExecutor → 安全执行
```

**关键文件**：
- `src/business/ai/network_analyzer.py`
- `src/business/ai/list_operation_analyzer.py`
- `src/business/ai/prompts/code_generation_prompt_v2.py`
- `src/business/ai/llm_client.py`

### 3. 数据压缩模型集成

**多提供商支持**：
- Anthropic Claude (Haiku, Sonnet)
- OpenAI (GPT-4o, GPT-3.5)
- Azure OpenAI
- 本地模型（Ollama 等）

**配置层级**：
```
Database (运行时) > File (用户配置) > Code (默认值)
```

**关键文件**：
- `src/data/unified_config.py` - 统一配置管理器
- `src/business/ai/request_intelligence_analyzer.py` - 集成数据压缩模型

---

## 技术选型

### 编程语言和框架

| 类别 | 选择 | 理由 |
|------|------|------|
| 语言 | Python 3.11+ | 丰富的 AI/自动化 库 |
| UI 框架 | PyQt6 | 跨平台，功能强大 |
| 异步框架 | asyncio | WebSocket 服务器 |
| 事件系统 | blinker | 轻量级，解耦合 |

### AI 集成

| 类别 | 选择 | 理由 |
|------|------|------|
| 主模型 | Claude Sonnet 4.5 | 准确性高，支持长上下文 |
| 压缩模型 | Claude Haiku | 快速、便宜，适合边缘分析 |
| 通用客户端 | LangChain | 统一接口，易于扩展 |

### 数据存储

| 用途 | 技术 | 理由 |
|------|------|------|
| 业务数据 | SQLite | 轻量级，关系型 |
| 录制数据 | DuckDB | 列式存储，分析快 10-100 倍 |
| 配置文件 | JSON | 简单直观，易编辑 |

### 浏览器自动化

| 技术 | 用途 | 理由 |
|------|------|------|
| Playwright | 浏览器自动化 | 功能强大，跨平台，API 友好 |
| Chrome Extension | 事件捕获 | 直接在页面上下文运行，可靠性高 |
| WebSocket | 进程间通信 | 跨平台，无需平台特定配置 |

---

## 架构优势

### 1. 松耦合设计

- **分层架构**：每层只依赖接口，便于测试和替换
- **事件驱动**：模块间通过事件通信，降低耦合度
- **依赖注入**：使用接口和工厂模式，灵活配置

### 2. 可扩展性

- **新事件类型**：只需扩展 content script
- **新 LLM 提供商**：只需实现 LLM 客户端接口
- **新驱动**：实现接口即可插入
- **新分析器**：模块化设计，易于添加

### 3. 性能优化

- **数据压缩**：70-90% 压缩率
- **智能过滤**：规则引擎 + 模型混合模式
- **高性能存储**：DuckDB 列式存储
- **批量处理**：减少数据库往返

### 4. 开发效率

- **事件驱动**：自动处理，无需手动协调
- **配置外置**：易于调试和修改
- **日志完善**：分级日志，便于排查问题
- **测试友好**：模块化设计，易于单元测试

---

## 相关文档

- [功能开发计划](docs/feature_plans.md) - 各功能详细计划
- [事件驱动架构详细说明](docs/event_driven_architecture.md)

---

**文档维护**: 架构变更时及时更新本文档

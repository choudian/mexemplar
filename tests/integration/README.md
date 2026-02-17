# Intent 确认集成测试

## 概述

本目录包含 Intent 确认功能的集成测试，覆盖完整的端到端流程、WebSocket 通信、多轮对话和状态管理等。

## 测试文件

### 1. `test_intent_confirmation_integration.py`

Intent 确认完整流程的集成测试，包含：

- **测试场景 1：简单意图确认**
  - 完整的确认流程测试
  - WebSocket 消息确认测试

- **测试场景 2：多轮对话优化**
  - 多轮对话测试
  - 最大轮数限制测试

- **测试场景 3：取消确认**
  - 取消确认测试
  - WebSocket 取消消息测试

- **WebSocket 通信测试**
  - 广播确认请求
  - 广播意图更新
  - 广播确认成功

- **状态机测试**
  - 状态转换测试
  - 最大轮数强制执行

- **异常处理测试**
  - 不存在的意图
  - 无效的消息动作
  - 缺少必要字段

- **数据持久化测试**
  - 保存和加载意图
  - 更新意图状态

- **会话管理测试**
  - 活跃会话计数
  - 清理超时会话

### 2. `test_websocket_e2e.py`

WebSocket 端到端通信测试，包含：

- **连接测试**
  - 服务器启动和停止
  - 客户端连接和断开
  - 多客户端连接

- **消息通信测试**
  - 心跳机制（PING/PONG）
  - 广播消息
  - 请求-响应模式

- **消息处理器测试**
  - 自定义处理器注册
  - 处理器异常处理

- **意图确认 E2E 测试**
  - 完整确认流程
  - 多轮优化流程

- **错误处理测试**
  - 无效 JSON
  - 未知消息类型
  - 缺少必要数据

- **性能测试**
  - 并发消息处理
  - 消息延迟测试

## 运行测试

### 运行所有集成测试

```bash
# 使用 uv
uv run pytest tests/integration/

# 或使用 pytest
pytest tests/integration/
```

### 运行特定测试文件

```bash
# Intent 确认集成测试
uv run pytest tests/integration/test_intent_confirmation_integration.py

# WebSocket E2E 测试
uv run pytest tests/integration/test_websocket_e2e.py
```

### 运行特定测试场景

```bash
# 场景 1：简单确认
uv run pytest tests/integration/test_intent_confirmation_integration.py::TestScenario1_SimpleConfirmation

# 场景 2：多轮对话
uv run pytest tests/integration/test_intent_confirmation_integration.py::TestScenario2_MultiTurnRefinement

# 场景 3：取消确认
uv run pytest tests/integration/test_intent_confirmation_integration.py::TestScenario3_Cancellation
```

### 运行特定测试用例

```bash
# 运行单个测试
uv run pytest tests/integration/test_intent_confirmation_integration.py::TestScenario1_SimpleConfirmation::test_simple_confirmation_flow -v
```

## 测试选项

### 显示详细输出

```bash
uv run pytest tests/integration/ -v
```

### 显示打印输出

```bash
uv run pytest tests/integration/ -s
```

### 显示测试覆盖率

```bash
uv run pytest tests/integration/ --cov=src/business/intent --cov=src/communication --cov-report=html
```

### 并行运行测试（加快速度）

```bash
uv run pytest tests/integration/ -n auto
```

## 测试前置条件

### 1. 数据库

集成测试使用内存数据库 (`:memory:`)，不需要外部数据库。

### 2. 端口

- WebSocket 服务器测试使用端口 `8766` 和 `8767`
- 确保这些端口未被占用

### 3. 依赖

```bash
# 安装测试依赖
uv sync --dev
```

## 测试架构

### 测试层次

```
┌─────────────────────────────────────┐
│      集成测试层      │
├─────────────────────────────────────┤
│  • 端到端流程测试                    │
│  • WebSocket 通信测试               │
│  • 多模块协作测试                    │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│      业务逻辑层      │
├─────────────────────────────────────┤
│  • IntentConfirmer                  │
│  • IntentAnalyzer                   │
│  • IntentRepository                 │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│      通信层       │
├─────────────────────────────────────┤
│  • WebSocketHandler                 │
│  • WebSocketClient                  │
│  • Message Types                    │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│      数据层          │
├─────────────────────────────────────┤
│  • DatabaseManager                  │
│  • Intent Models                    │
└─────────────────────────────────────┘
```

### 测试覆盖范围

#### 功能测试

- ✅ 简单意图确认
- ✅ 多轮对话优化
- ✅ 取消确认
- ✅ 状态机转换
- ✅ 会话管理

#### 通信测试

- ✅ WebSocket 连接管理
- ✅ 消息发送和接收
- ✅ 广播机制
- ✅ 心跳机制
- ✅ 错误处理

#### 数据测试

- ✅ 数据持久化
- ✅ 数据加载
- ✅ 数据更新
- ✅ 事务处理

#### 性能测试

- ✅ 并发消息处理
- ✅ 消息延迟
- ✅ 多客户端连接

## 测试场景示例

### 场景 1：简单确认流程

```python
# 1. 录制完成
recording_id = "test-recording-001"

# 2. 启动意图分析
intent = await confirmer.start_confirmation(recording_id)

# 3. 发送确认请求到 UI
await confirmer._send_confirmation_request(intent)

# 4. 用户确认
confirmed_operations = ["操作1", "操作2", "操作3"]
result = await confirmer.confirm_intent(intent.intent_id, confirmed_operations)

# 5. 验证
assert result.status == "confirmed"
```

### 场景 2：多轮对话

```python
# 1. 意图分析完成
intent = await confirmer.start_confirmation(recording_id)

# 2. 用户反馈
feedback = "请把'输入用户名'改为'输入邮箱'"
result = await confirmer.process_user_feedback(intent.intent_id, feedback)

# 3. 验证优化
assert result.analysis_result.core_operations[1].operation == "输入邮箱"

# 4. 继续优化
feedback2 = "请添加'验证邮箱格式'"
result2 = await confirmer.process_user_feedback(intent.intent_id, feedback2)

# 5. 最终确认
await confirmer.confirm_intent(intent.intent_id, confirmed_operations)
```

### 场景 3：取消确认

```python
# 1. 意图分析完成
intent = await confirmer.start_confirmation(recording_id)

# 2. 用户取消
result = await confirmer.cancel_confirmation(intent.intent_id)

# 3. 验证
assert result.status == "cancelled"
```

## 已知问题

### 1. WebSocket 端口冲突

如果端口 `8766` 或 `8767` 被占用，测试会失败。

**解决方案**：
```bash
# 查找占用进程
lsof -i :8766
lsof -i :8767

# 或在 Windows 上
netstat -ano | findstr :8766
```

### 2. 异步测试超时

某些异步测试可能超时。

**解决方案**：
- 增加超时时间
- 检查是否有阻塞操作
- 确保事件循环正常运行

## 下一步

- [ ] 添加 UI 集成测试（需要 PyQt6 测试框架）
- [ ] 添加性能基准测试
- [ ] 添加压力测试
- [ ] 添加更多边界条件测试

## 贡献指南

### 添加新的集成测试

1. 在对应的测试文件中添加新的测试类
2. 使用清晰的命名约定（如 `TestScenario4_*`）
3. 添加完整的文档字符串
4. 确保测试独立运行
5. 清理测试资源

### 测试命名约定

- 测试类：`Test<Feature><Component>`
- 测试方法：`test_<scenario>_<condition>_<expected_result>`

示例：
```python
class TestScenario4_MultiUser:
    """测试场景 4：多用户并发"""

    async def test_multiple_users_concurrent_confirmation(self):
        """测试多用户并发确认"""
        pass
```

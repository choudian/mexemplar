# Quickstart: MCP Management

**Feature**: 027-mcp-management
**Date**: 2026-07-04

## 30 秒上手

1. 添加 MCP server 配置
2. AI 自动发现并调用 MCP 工具

## 最简配置示例

### 文件系统 MCP server（无需凭证）

```json
// 粘贴到前端 MCP 工具 tab 的"粘贴配置"框
{
  "mcpServers": {
    "filesystem": {
      "command": "cmd",
      "args": ["/c", "npx", "-y", "@modelcontextprotocol/server-filesystem", "C:\\Users\\username\\Desktop"]
    }
  }
}
```

### GitHub MCP server（需 API key）

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxxxxxxxxxxx"
      }
    }
  }
}
```

## 添加步骤

1. 打开工具列表屏，切换到"MCP 工具"tab
2. 点击 ➕ 添加 server
3. 选择"粘贴配置"，输入上述 JSON
4. 点击"解析"→ 表单自动回填
5. 确认 secret 值已填入 → 点击"测试连接"
6. 看到 "✓ 连通, 暴露 N 个工具" → 点击"保存"

## 使用方式

配置保存后，在 AI 助手对话中直接提及相关任务：

> "帮我看看最新的 PR"

AI 会自动发现并调用 `mcp__github__list_prs`，将结果呈现给用户。

## 常用命令

```powershell
# 后端测试
uv run python -m pytest tests/business/mcp -q
uv run python -m pytest tests/data/test_mcp_server_repository.py -q
uv run python -m pytest tests/desktop_api/test_mcp_servers_router.py -q

# 门卫测试
uv run python -m pytest tests/guardrails/test_mcp_guardrails.py -q

# 前端测试
cd frontend
npm run test -- --grep="mcp"

# 数据库迁移检查
uv run python -c "from src.data.migrations import get_schema_version; from src.data.sqlalchemy_manager import get_sqlalchemy_manager; mgr = get_sqlalchemy_manager(); mgr.initialize(); print(get_schema_version(mgr.engine))"
```

## 验证要点

| 验证项 | 方法 |
|--------|------|
| v24 迁移成功 | 检查 `mcp_servers` 表存在 |
| 文件系统 server 连通 | POST `/api/mcp-servers/{id}/test-connection` |
| AI 调用 MCP 工具 | 对话中说"列出目录文件"，观察 AI 调用 `mcp__filesystem__list_directory` |
| 凭证不泄漏 | GET `/api/mcp-servers` 不返回 secret 值 |
| 高危确认穿透 | 对话中触发写操作（如 "创建 PR"），观察确认浮层出现 |
| 断连标灰 | 停止 MCP server 子进程，UI 卡片标灰 |

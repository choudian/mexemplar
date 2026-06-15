# Quickstart: 工具目录渐进式延迟加载

## Scenario 1: 小目录兼容

1. 创建 2 个已发布技能和 1 个可用组合。
2. 构建主助理、子代理和专员 Prompt。
3. 验证目录完整显示名称与描述，并提示先调用 `get_tool_detail`。

## Scenario 2: 大目录延迟

1. 创建 100 个已授权能力。
2. 构建三类 Agent Prompt。
3. 验证目录区段只含总数和发现说明，不含任一能力名称，长度不超过 1000 字符。

## Scenario 3: 浏览和搜索

1. 连续调用 `search_tools(query="", offset=N, limit=25)`。
2. 验证四页覆盖全部 100 项且无重复。
3. 按关键词和 kind 搜索，验证稳定相关度排序。
4. 将结果 selector 传给 `get_tool_detail`，验证下一轮出现已激活 FC schema。

## Scenario 4: 运行时变化

1. 激活一个技能后将其状态改为不可用。
2. 验证下一次搜索不再返回该技能，详情加载拒绝，激活列表刷新后移除。
3. 运行时修改目录阈值，验证下一次 Prompt 构建切换模式。

## Validation commands

```powershell
uv run pytest tests/business/agents/test_capability_catalog.py -q
uv run pytest tests/test_skill_composition_regressions.py -q
uv run pytest tests/integration/test_agent_orchestrator_architecture.py -q
uv run pytest tests/data/test_unified_config.py -q
uv run black --check src/business/agents/tools/capability_catalog.py src/business/agents/tools/dynamic_tool_manager.py src/business/orchestration/agent/assistant_prompt_builder.py src/business/orchestration/agent/orchestrator.py src/data/config_models.py src/data/unified_config.py tests/business/agents/test_capability_catalog.py
uv run flake8 src/business/agents/tools/capability_catalog.py src/business/agents/tools/dynamic_tool_manager.py src/business/orchestration/agent/assistant_prompt_builder.py
```

## Validation result

- 功能相关测试全部通过。
- Black check、Flake8、`git diff --check` 全部通过。
- 全量测试的 5 个失败已在主工作树复现，确认属于现有基线问题。

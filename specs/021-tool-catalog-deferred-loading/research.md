# Research: 工具目录渐进式延迟加载

## Decision 1: 延迟对象

**Decision**: 延迟的是用户能力摘要目录；FC schema 继续沿用现有 `get_tool_detail` 动态激活。  
**Rationale**: 当前 FC schema 已按需加载并有 LRU，上下文增长来自 Prompt Builder 全量注入名称和描述。  
**Alternatives considered**: 重写 AgentLoop 工具注册；会重复现有能力并扩大回归面。

## Decision 2: 双阈值

**Decision**: 默认同时使用 20 项和 6000 字符阈值，严格超过任一阈值进入 deferred。  
**Rationale**: 单纯按数量无法约束超长描述；字符阈值直接限制实际 Prompt 体积。等于阈值保持兼容。  
**Alternatives considered**: token 精确计数；当前目录无需引入 tokenizer 依赖，字符上限更确定。

## Decision 3: 发现契约

**Decision**: 扩展既有 `search_tools`，支持空 query 浏览、kind、offset、limit，并返回结构化 JSON。  
**Rationale**: 延迟模式下必须能发现未知关键词的长尾能力；复用既有工具避免新增重叠工具。  
**Alternatives considered**: 新增 `list_tools`；增加工具数量且与 search 职责重叠。

## Decision 4: 授权与新鲜度

**Decision**: Prompt 在构建时按当前授权生成，搜索和详情在每次调用时重查发布状态、组合状态和白名单。  
**Rationale**: UI event 不是业务事实；调用时重校验可阻止旧 Prompt 或旧激活缓存越权。  
**Alternatives considered**: 持久目录快照；需要迁移并引入失效同步问题。

## Decision 5: 配置暴露

**Decision**: 新增 `agent_tools.discovery.*` 统一配置，但不进入 Settings UI。  
**Rationale**: 这些是工程调优参数，和现有 file/search/process 限额一致；运行时覆盖仍可用于测试和部署调优。  
**Alternatives considered**: 新增 Settings 分区；扩大前端/API 范围且没有明确用户价值。

## Decision 6: 三类 Agent

**Decision**: 主助理、临时子代理和固定专员统一使用目录策略。  
**Rationale**: 专员白名单可能增长，临时子代理可能继承完整池；只修主助理会留下上下文膨胀旁路。  
**Alternatives considered**: 仅主助理；实现不完整且规则继续分散。

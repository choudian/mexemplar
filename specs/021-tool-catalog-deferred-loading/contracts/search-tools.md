# Tool Contract: `search_tools`

## Input schema

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "可选关键词；留空时浏览授权能力目录"
    },
    "kind": {
      "type": "string",
      "enum": ["all", "tool", "composition"],
      "default": "all"
    },
    "offset": {
      "type": "integer",
      "minimum": 0,
      "default": 0
    },
    "limit": {
      "type": "integer",
      "minimum": 1,
      "description": "省略时使用统一配置默认值，超过最大值时截断"
    }
  }
}
```

## Success result

工具结果为 JSON 字符串：

```json
{
  "query": "报告",
  "kind": "all",
  "offset": 0,
  "limit": 10,
  "total": 2,
  "items": [
    {
      "kind": "tool",
      "name": "生成报告",
      "selector": "技能:生成报告",
      "description": "根据输入生成报告"
    }
  ],
  "nextOffset": null
}
```

## Behavior

- 省略全部参数等价于浏览第一页。
- 旧调用 `{"query": "..."}` 保持有效。
- 空 query 时返回全部授权能力的稳定分页。
- 非空 query 排序：名称精确、名称前缀、名称包含、描述/适用场景包含。
- `kind` 先过滤再计算 total 和分页。
- `offset >= total` 返回空 items 和 `nextOffset: null`。
- `limit` 超过配置最大值时截断，不扩大输出。
- 返回项必须已通过当前发布状态、组合状态、成员授权和 Agent 白名单校验。

## Error behavior

模型绕过 schema 传入非法 kind、负 offset 或不可转换的数字时，handler 返回不含目录内容的结构化错误文本；不激活任何能力。

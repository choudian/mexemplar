# Data Model: 工具目录渐进式延迟加载

本功能不新增持久化实体或数据库迁移。

## CapabilityCatalogItem

| Field | Type | Rules |
|-------|------|-------|
| kind | `tool` or `composition` | 封闭枚举 |
| name | string | 当前已发布能力名称 |
| selector | string | `技能:<name>` 或 `技能组合:<name>` |
| description | string | 技能描述；组合描述为空时使用 applicability |
| search_text | string | 名称、描述和组合 applicability 的规范化检索文本 |

## CapabilityDiscoveryPolicy

| Field | Default | Bounds |
|-------|---------|--------|
| full_catalog_max_items | 20 | 1..1000 |
| full_catalog_max_chars | 6000 | 500..100000 |
| search_default_limit | 10 | 1..search_max_limit |
| search_max_limit | 25 | 1..100 |
| result_description_max_chars | 500 | 50..5000 |

`search_default_limit` 在读取时不得超过 `search_max_limit`。

## CapabilityCatalogRender

| Field | Meaning |
|-------|---------|
| mode | `empty`, `full`, `deferred` |
| content | 可直接注入 system prompt 的目录区段 |
| item_count | 授权能力总数 |
| rendered_chars | 完整目录候选文本长度，用于模式判断和日志 |

## CapabilitySearchPage

| Field | Meaning |
|-------|---------|
| query | 规范化关键词 |
| kind | 应用后的类型过滤 |
| offset / limit | 当前页参数 |
| total | 过滤后的总数 |
| items | 当前页能力 |
| nextOffset | 有下一页时的偏移，否则 null |

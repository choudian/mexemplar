# 如何创建方法论

当用户明确要求把某次已经发生的工作流程"做成方法论"、"沉淀成步骤"、"以后遇到类似场景照这个做"时，才考虑调用 `create_skill_methodology`。不要因为一次普通任务完成就自动产出新方法论。

## 调用前义务

1. 先检查当前 system prompt 中的方法论装备清单，按 name、description 和 trigger_conditions 判断是否已经有同类方法论。
2. 如果名称相同或触发场景高度重合，先向用户确认是要合并、更新旧方法论，还是创建全新方法论。
3. 只有 archive 或 failure 分区里的 segment 可以作为素材来源，且 `source_segments` 至少 1 条。
4. 不要无差别调用 `load_skill_methodology` 读取全部方法论正文。先读装备清单里的 trigger_conditions，确认当前场景命中后再按需 load。

## 字段填写

- `mode`: 新建用 `create`；更新已有方法论用 `supersede` 并提供 `target_skill_id`。
- `name`: 人类可读、稳定、短而具体。
- `description`: 一句话说明方法论解决什么问题。
- `trigger_conditions`: 必须至少 1 条，每条是自然语言触发条件，不写关键词匹配规则。
- `required_tools`: 执行该方法论通常需要的工具名列表；没有也要传空列表。
- `body_markdown`: 写完整步骤、检查点、常见失败和输出要求。
- `source_segments`: 必须引用 archive 或 failure 素材，并标明 `segment_id` 与 `source_zone`。
- `change_reason`: 说明为什么新增或更新这条方法论。

## 回复用户

工具成功产出新 active 方法论或新版本后，应在同轮回复中给用户可见反馈，例如："已新增方法论：X" 或 "已更新方法论：X"。

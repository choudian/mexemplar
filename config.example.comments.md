# `config.example.json` Notes

## `ai`

设置页展示的 AI 配置均通过 `get_unified_config()` 读写。`ai.api_key` 只用于迁移兼容，运行时写入密钥必须走 keyring，不应把明文密钥保存在配置文件或数据库。

## `ui`

- `theme`: 设置页可选 `light`、`dark`、`system`。
- `density`: 设置页可选 `comfy`、`compact`，默认 `comfy`。

## `recording.large_field`

大字段占位与分段读取配置。Agent 查询录制数据时，文本字段值达到阈值后以结构化占位对象交付，Agent 通过 `read_field_chunk` 按需分段续读原始内容。通用录制数据工具为 5 工具模型：`describe_data`、`query_data`、`execute_code`、`read_recording`、`read_field_chunk`。浏览器路径额外保留 `analyze_image`，桌面路径改用桌面专属工具。大字段占位与续读涉及其中 `query_data`（占位触发）和 `read_field_chunk`（分段续读）两个工具。

- `threshold_chars`: 占位触发阈值（字符数，按 Python `len()` Unicode 码点计）。任意文本结果列值 `>=` 此值时触发占位替换，取代原 12KB 无差别截断。默认 1000。
- `preview_chars`: 占位对象 `preview` 字段的最大长度（字符数）。默认 1000。
- `max_chunk_chars`: `read_field_chunk` 单次返回 `content` 的最大长度（字符数），同时也是省略 `length` 参数时的默认值。默认 1000。

运行时修改以上三个值立即影响后续工具调用，但不使已返回的 `locator` 失效。

## `recording.desktop`

桌面录制配置。

- `enable_clip`: 是否为桌面动作额外生成 mp4 clip。默认 `true`。关闭后仍保存 PNG 帧和动作元数据。
- `vision_model`: 桌面动作多模态分析使用的模型名。留空或 `null` 时不注入 `analyze_desktop_action`，但 `list_desktop_actions` / `read_action_clip` 等元数据工具仍可用。

## `recording.noise_filter`

- `enabled`: 关闭时只停用入库侧规则判定与 `filter_decisions` 写入；Agent 查询侧的隐藏字段、隐藏表、只读 SQL 和错误脱敏契约仍然保留。
- `blacklist_domains`: 广告 / 埋点域名黑名单关键字，命中后优先于泛化的跨域规则。
- `first_party_whitelist`: 额外视为 first-party 的站点键列表，填写 registrable domain / eTLD+1，例如 `example.com`、`example.co.uk`。
- `static_extensions`: 通过 URL 后缀识别静态资源的扩展名白名单。
- `static_content_type_prefixes`: 通过响应 `Content-Type` 识别静态资源的前缀白名单。

## `brain.skill`

方法论资产层配置。运行时读取必须走 `get_unified_config()`；Settings UI 本期不暴露这些 tuning knob。

- `token_budget.warn_threshold`: 方法论装备清单 token 计量条黄色阈值，默认 4096。
- `token_budget.danger_threshold`: 方法论装备清单 token 计量条红色阈值，默认 8192。
- `seed_file_path`: "如何创建方法论"内置 seed 文件路径，默认 `src/business/brain/seed/how_to_create_skill_methodology.md`。

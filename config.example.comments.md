# `config.example.json` Notes

## 读取优先级与生效时机

所有配置统一由 `get_unified_config()` / `UnifiedConfigManager` 读取，优先级从高到低为：仅当前 sidecar 进程有效的 runtime 覆盖、SQLite `app_settings`、`config.json` 文件默认值、代码默认值。Settings 修改会写入 `app_settings`，因此会覆盖同名文件值；runtime 覆盖不会持久化，sidecar 重启后自动消失。

`config.json` 只在 `UnifiedConfigManager` 创建时加载。手工编辑该文件后需要重启 sidecar（通常重启桌面应用）才会重新读取；已经启动的录制浏览器也必须停止并重新启动，才会获得新的启动期扩展配置。示例文件是严格 JSON，说明保留在本文件，不能写进 JSON 注释。

`debug.trace.*` 仅允许当前 sidecar 进程内的 runtime 控制，不属于文件或 Settings 持久化配置；动态 MCP server 的 `mcp.servers.*.env.*` / `headers.*` 凭据仅可由统一配置层写入 SQLite。二者都不会出现在模板。加载器遇到 runtime-only、DB-only、弃用或未知的文件键时只记录键路径并忽略其值。

## `ai`

设置页展示的 AI 配置和 API Key 均通过 `get_unified_config()` / `UnifiedConfigManager` 读写。密钥保存在统一配置层，可由 `config.json` 提供默认值，也可由 Settings 写入 `app_settings` 覆盖；Settings 和 API 响应只返回遮罩状态，不返回密钥明文。普通日志必须对密钥字段脱敏。

当前密钥字段包括 `ai.api_key`、`ai.vision_api_key`、`ai.embedding_api_key`、`web.brave_api_key`、`skill_store.skills_sh_api_key`、`agent_tools.output.semantic_summary.api_key` 和 `self_improvement.execution_review.model.api_key`。会话压缩的 provider、model、API key 和 base URL 始终继承主 `ai.*` 配置；只有 `ai.compression_model_temperature` 与 `ai.compression_model_max_tokens` 是压缩专属调优项，不应再新增独立的压缩凭据块。

记忆/压缩阈值的 canonical 文件命名空间是 `ai.memory_*`。历史顶层 `memory.*` 键在读取时会临时兼容并记录弃用提示，后续请迁移到 `ai.memory_*`；模板只保留 canonical 键。

### `ai.failure_routing.quota_markers`

用于识别“模型账户额度已经耗尽、只有用户充值才能继续”的 provider 错误文本。系统会先跨完整异常链匹配这组标记；未命中时仍调用既有可恢复性判断，因此该配置只决定可恢复失败中的第一档路由，不会把认证、400 或其他不可恢复错误改成可恢复。

每个元素必须是非空字符串，匹配前会对配置项和异常文本同时执行 `strip().casefold()`；非法元素会被忽略并记录不含原值的 warning。配置为空数组表示关闭额度专属分类，所有失败逐字退回既有路由。默认值刻意不包含裸 `quota` 或 `billing`，避免把自动恢复的 rate quota 或 billing 服务故障误判成需要用户充值。

当前不提供 Settings/API 编辑入口，只支持在 `config.json` 中配置；手工修改后必须重启 sidecar 才会重新加载。标记本身不是 secret，provider 异常原文不会进入 DTO、UI event 或前端持久化状态。

## `ui`

- `theme`: 设置页可选 `light`、`dark`、`system`。
- `density`: 设置页可选 `comfy`、`compact`，默认 `comfy`。

## `recording.large_field`

大字段占位与分段读取配置。Agent 查询录制数据时，文本字段值达到阈值后以结构化占位对象交付，Agent 通过 `read_field_chunk` 按需分段续读原始内容。通用录制数据工具为 5 工具模型：`describe_data`、`query_data`、`execute_code`、`read_recording`、`read_field_chunk`。浏览器路径额外保留 `analyze_image`，桌面路径改用桌面专属工具。大字段占位与续读涉及其中 `query_data`（占位触发）和 `read_field_chunk`（分段续读）两个工具。

- `threshold_chars`: 占位触发阈值（字符数，按 Python `len()` Unicode 码点计）。任意文本结果列值 `>=` 此值时触发占位替换，取代原 12KB 无差别截断。默认 1000。
- `preview_chars`: 占位对象 `preview` 字段的最大长度（字符数）。默认 1000。
- `max_chunk_chars`: `read_field_chunk` 单次返回 `content` 的最大长度（字符数），同时也是省略 `length` 参数时的默认值。默认 1000。

运行时修改以上三个值立即影响后续工具调用，但不使已返回的 `locator` 失效。

## `recording.browser_start_url`

浏览器录制的可选启动页。调用方显式传入 `start_url` 时（包括空字符串）优先使用该值；仅未传入（`None`）时才回退到本配置。空白或无效值不会导航，浏览器保留在空白页。该字段只在下一次浏览器录制启动时生效。

## `recording.websocket`

`host`、`port`、`max_message_size` 和 `max_response_body_size` 是浏览器录制扩展与本地 sidecar 的传输边界。文件配置中的 `port` 必须为 1–65535；端口 0 的自动分配无法在扩展启动前传递实际地址，因此不支持。每次 Playwright 浏览器录制启动时，驱动会复制一份扩展并写入 `launch_context.js`；其中的 `websocket_url` 供 MV3 background service worker 在首个页面出现前建立连接。页面侧的 `MEXEMPLAR_CONFIG` 则由 `PlaywrightRecordingDriver._build_page_init_script()` 经 Playwright 的 `BrowserContext.add_init_script()` 注入，供内容脚本读取。

已有扩展 service worker 不会回读文件配置；修改 host 或 port 后，请停止当前浏览器录制并重新启动。不要把已废弃的“是否采集网络请求”“网络请求过滤”“视频帧率”“浏览器类型/无头模式”等伪设置重新写回模板或 Settings；网络采集能力仍由现有录制链路负责。

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

## `agent_tools.discovery`

用户技能与技能组合目录的渐进式延迟加载参数。运行时读取必须走
`get_unified_config()`；这些工程调优项不在 Settings UI 中展示。

- `full_catalog_max_items`: 完整目录允许的最大能力数，默认 20。
- `full_catalog_max_chars`: 完整目录区段允许的最大字符数，默认 6000。
- `search_default_limit`: `search_tools` 默认页大小，默认 10。
- `search_max_limit`: `search_tools` 最大页大小，默认 25。
- `result_description_max_chars`: 单条搜索结果描述字符上限，默认 500。

`agent_tools.max_parallel_workers` 是并发安全只读工具的最大并行 worker 数；`agent_tools.output.load_max_bytes` 是单次恢复原始工具输出的最大字节窗口。二者都是工程保护阈值，超出范围会由统一配置访问器收敛。

## `self_improvement.execution_review.model`

执行复盘可选专用模型 profile。全部留为 `null` 时继承主 `ai.*` 模型；可单独指定 provider、model、base URL、temperature、max_tokens、thinking_level 和 timeout。`api_key` 仍是 secret，不能提交到版本库或写入日志。

# `config.example.json` Notes

## `recording.noise_filter`

- `enabled`: 关闭时只停用入库侧规则判定与 `filter_decisions` 写入；Agent 查询侧的隐藏字段、隐藏表、只读 SQL 和错误脱敏契约仍然保留。
- `blacklist_domains`: 广告 / 埋点域名黑名单关键字，命中后优先于泛化的跨域规则。
- `first_party_whitelist`: 额外视为 first-party 的站点键列表，填写 registrable domain / eTLD+1，例如 `example.com`、`example.co.uk`。
- `static_extensions`: 通过 URL 后缀识别静态资源的扩展名白名单。
- `static_content_type_prefixes`: 通过响应 `Content-Type` 识别静态资源的前缀白名单。

## Why

浏览器录制数据里掺杂大量业务无关的请求（广告埋点、三方推荐、重定向、静态资源等）。这些请求进入 DuckDB 后被 Agent 通过 `query_data` 工具读取时会污染其上下文、稀释业务信号、浪费 LLM token。`network_requests` 表的 schema 中早已预留 `filtered` / `filter_reason` / `is_recommendation` / `importance_level` 等字段，`filter_decisions` 表也建好，但从未有生产代码写入——是半成品。本次把这条链路接上。

## What Changes

- 新增噪声过滤能力：在录制入库阶段（`DuckDBRecordingPersister.save_to_duckdb` 链路）对每条 `network_request` 运行规则判定并持久化决策；**`recording_recovery` 的恢复入库路径同样接入**，防止崩溃恢复场景绕过过滤。恢复路径以**单个 recovered recording/session 为事务边界**：先保留队列解析出的原始 action dict 列表，再按整条 recording 扁平化 network requests、一次性入库 requests、一次性入库 decisions，不做“每 action 单独 COMMIT”
- 规则覆盖五类噪声（**评估顺序先廉价字段检查、后昂贵域名归一化**，以 design 决策 3 为准）：
  1. OPTIONS 预检请求
  2. 3xx 重定向响应
  3. 静态资源（由 URL 扩展名 / Content-Type 识别：image / font / stylesheet / favicon / octet-stream 非业务类）
  4. 广告 / 埋点域名黑名单（初版内建清单统一为：doubleclick、googletagmanager、google-analytics、sentry、hotjar、baidu-tongji 等）
  5. 第三方请求（按 registrable domain / eTLD+1 判定 first-party；同站多子域视为业务流量，白名单只做补充）
- `filter_decisions` 表首次投入使用，作为多源决策记录（首版只有 `source="rule"`，`decision` 枚举沿用既有 schema 的 `"filter" | "keep"` 语义，为 `llm` / `human` 源预留扩展位）；`filter_decisions.request_id` 继续沿用现有 `TEXT` schema，写入时保存 `network_requests.request_id` 的字符串化值
- `network_requests.filtered` 继续作为聚合结果；`network_requests.filter_reason` 明确定义为最终生效决策的精简 JSON 摘要（如 `{"decision":"filter","source":"rule","reason":"static_asset","pattern_matched":".png"}`），未命中过滤规则时保持 `NULL`；`filtered_at` 仅在 `filtered=true` 时写入。Repository 层按现有 JSON 字段惯例负责 `json.dumps(..., ensure_ascii=False)` 序列化，不要求调用方预先手工编码
- Agent 查询侧对噪声**完全不可见**：
  - `query_data` 内部把每一处 `network_requests` 引用改写为“`filtered = false` + 允许列白名单投影”的派生表；**改写失败时直接拒绝查询并返回错误**（不静默放行原 SQL），避免违反"Agent 只能看见业务数据"契约
  - `execute_code` 注入给 Agent 的 `conn` 必须是经过包装的受限连接，所有 `.execute()` / `.sql()` / `.cursor().execute()` 调用走同一条 SQL 改写链路；**代理层**把 rewriter 拒绝类异常包装成泛化错误后再抛给 Agent 代码（避免 `try/except print(e)` 看到过滤设施内部细节）；duckdb 执行期异常和 Agent 代码运行时异常正常透传（不含过滤设施信息，帮助 Agent 定位问题）；Relation API 物化仅承诺 `.fetchall()` / `.fetchone()` / `.fetchmany()`，`.view()` / `.df()` / `.pl()` / `.arrow()` / `.fetchdf()` / `.fetch_df()` / `.to_df()` / `.query(alias, sql)` 等高风险或依赖可选库的路径一律拒绝
  - `describe_data` 输出中**完全移除** `filter_decisions` 表以及 `network_requests` 的 `filtered` / `filter_reason` / `filtered_at` / `is_recommendation` / `importance_level` 五个字段；`network_requests.row_count` 也只统计 Agent 可见的 `filtered=false` 行
  - `query_data` / `execute_code` 异常提示中的表名清单也同步剔除 `filter_decisions`，防止错误信息泄漏过滤设施的存在
  - 上述 Agent 侧只读 / 隐藏 / 脱敏防护**不受** `recording.noise_filter.enabled` 开关影响；即使关闭入库规则判定，Agent 仍看不到过滤设施本身
- 噪声请求的 `response_body` 原样保留（不做物理删除，保留反悔空间）
- LLM 判断保留空接口（`LLMNoiseJudge.judge(request) -> FilterDecision | None` 始终返 `None`），首版不实现
- `is_recommendation` / `importance_level` 字段**保持 schema 默认值**（`FALSE` / `'unknown'`），规则不主动写入，语义留给 P2.1 LLM 判断使用；`describe_data` 对 Agent 隐藏这两个字段
- `compression_model_*` 配置字段**暂不处理**——昨天的 commit 已让 getter fallback 到主模型，本提案不涉及该配置语义的重新定义（若未来 LLM 判断接入，再单独评估复用还是删除）

## Capabilities

### New Capabilities

- `recording-noise-filter`: 对浏览器录制产生的网络请求进行噪声识别与打标。定义规则集、决策记录格式、查询端默认过滤行为、以及 LLM / 人工决策源的扩展契约。

### Modified Capabilities

无。本次新增独立能力，不修改现有 capability 的 spec。（注：`recording_data_tools` 的默认查询行为变更是能力内部事项，其对外契约——"给 Agent 返回业务相关数据"——未变。）

## Impact

- **代码**：
  - `src/recording/browser/duckdb_recording_persister.py`：入库前插入规则判定
  - `src/data/recording_recovery.py`：恢复入库路径同样接入规则判定（避免成为过滤旁路）
  - `src/data/recording_repository.py`：新增 `save_filter_decisions`，并扩展 `save_network_requests` 接收聚合后的 `filtered / filter_reason / filtered_at`；去掉"写死 filtered=False / filter_reason=None"
  - 新增 `src/recording/filtering/` 模块（驱动层）：规则实现、决策记录、LLM 接口占位、**SQL 改写核心**（`sql_rewriter.py`）、**受限连接代理**（`filtered_conn.py`，同时代理 DuckDBPyConnection 与 DuckDBPyRelation 两层）、入库 hook
  - `src/business/agents/tools/recording_data_tools.py`（业务层适配，只做装配，不持有过滤策略）：
    - `query_data` 执行前调用 `filtering.sql_rewriter`；**改写失败或检测到 `filter_decisions` 引用、非只读语句时直接拒绝查询**
    - **删除现有的正则护栏**：`_SELECT_RE.match` / 分号拒绝 / `--` / `/*` 注释拒绝 / `SELECT INTO` 拒绝——四组都要删，由 sqlglot AST 统一负责，否则错误脱敏契约会分化、"注释中的名字不改写"等 scenario 会变成不可达
    - `execute_code` 注入给 Agent 的 `conn` 改为 `filtering.filtered_conn.FilteredDuckDBConnection`，并收缩为**只读 SELECT 白名单**（显式拒绝 `SHOW / PRAGMA / DESCRIBE / EXPLAIN / ATTACH / COPY / CREATE / CREATE TEMP VIEW / INSERT / UPDATE / DELETE` 以及引用 `information_schema.*` / 任何 `duckdb_*` 或 `pragma_*` 开头的系统函数 / 系统表）；`Relation` 物化仅承诺 `.fetchall()` / `.fetchone()` / `.fetchmany()`，`.view()` / `.df()` / `.pl()` / `.arrow()` / `.fetchdf()` / `.fetch_df()` / `.to_df()` / `.query(alias, sql)` 直接拒绝
    - `describe_data` 移除 `filter_decisions` 表以及 `network_requests` 的 5 个过滤相关字段，并让 `network_requests` 的 `row_count` 只统计可见行
    - 清洗异常提示中的表名清单（`_ALL_TABLE_NAMES`），剔除 `filter_decisions`
    - `execute_code` 沙箱导入白名单**继续禁止** `pandas` / `polars` / `pyarrow`（防止 `pandas.read_sql` 等旁路）
  - `src/data/duckdb_manager.py`：把 `network_requests` CREATE TABLE 的 `importance_level TEXT` 改为 `importance_level VARCHAR DEFAULT 'unknown'`，与 `_migrate_network_requests_table` 的 ALTER ADD COLUMN 默认值对齐（避免新装机取 NULL、老库取 'unknown' 的漂移）
- **数据**：现有 `network_requests` 和 `filter_decisions` 表 schema 不变；历史数据 `filtered` 保持 `false`（不追溯标注，因为规则判定依赖域名归属信息，历史记录不重跑）；`is_recommendation` / `importance_level` 继续保持 schema 默认值 `FALSE` / `'unknown'`，不被规则主动修改；`filter_decisions.request_id` 保存字符串化后的请求 ID，`network_requests.filter_reason` 保存最终聚合决策的 JSON 摘要
- **配置**：新增少量过滤规则配置项（如黑名单域、first-party 白名单、是否启用入库侧规则判定）；`recording.noise_filter.enabled` 只控制入库侧判定与决策写入，不关闭 Agent 侧隐藏 / 只读防护；即使回滚到 `enabled=false`，`describe_data` 仍持续隐藏过滤字段 / 表，作为长期查询侧契约；`compression_model_*` 不动
- **依赖**：`pyproject.toml` `dependencies` 中新增：
  - `sqlglot>=23.0.0,<30.0.0`（纯 Python，用于 SQL 改写的 AST 解析与替换；决策 10）
  - `tldextract>=5.0.0,<6.0.0`（eTLD+1 归一化依赖 Public Suffix List；决策 16）
  - 通过门卫测试约束 `import sqlglot` / `import tldextract` 只出现在 `src/recording/filtering/`
- **测试**：新增规则判定单元测试、入库链路集成测试、Agent 工具默认过滤行为冒烟测试
- **不涉及**：P1（大字段分层访问）、`compression_handler` 会话摘要逻辑、UI 层

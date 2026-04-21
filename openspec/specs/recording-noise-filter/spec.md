## ADDED Requirements

### Requirement: 入库时对网络请求运行规则判定

系统 SHALL 在 `DuckDBRecordingPersister.save_to_duckdb` 流程以及 `recording_recovery` 的崩溃恢复入库路径中，对每条待入库的 `network_request` 同步运行噪声规则判定，并在返回前完成所有决策写入。两条入库路径 MUST 共享同一规则判定实现，保证行为一致。

#### Scenario: 录制结束时自动判定噪声

- **WHEN** 录制结束并触发入库
- **THEN** 每条 `network_request` 的 `filtered` 字段必须被写入为 `true` 或 `false`
- **AND** `filtered=true` 的请求必须在 `filter_decisions` 表中有至少一条 `decision="filter"` 的记录
- **AND** 入库总耗时相对当前实现的增量保持在可接受量级（规则判定对 1000 条请求的预估开销约 50–100ms；本提案不设硬验收阈值）

#### Scenario: 规则判定未命中任何噪声

- **WHEN** 某条请求不匹配任何噪声规则
- **THEN** `filtered` 写入为 `false`
- **AND** `filter_decisions` 表中不产生该请求的记录

#### Scenario: 崩溃恢复场景同样被过滤

- **WHEN** 录制过程崩溃后通过 `recording_recovery` 恢复入库
- **THEN** 恢复路径写入的每条 `network_request` 也必须被规则判定
- **AND** 行为与正常 `save_to_duckdb` 路径完全一致（相同输入产生相同 `filtered` 值）

#### Scenario: 入库与决策在同一事务内提交

- **WHEN** 任一入库路径（正常 `save_to_duckdb` 或 `recording_recovery`）写入 `network_requests.filtered / filter_reason / filtered_at` 以及 `filter_decisions`
- **THEN** 两份写入必须在同一个 DuckDB 事务内提交
- **AND** 任一步骤失败时整个事务回滚，不允许出现"请求已入库但决策未入库"或"决策已入库但请求 filtered 未写"的不一致状态
- **AND** 回滚后，正常 `save_to_duckdb` 路径下该 `recording_id` 对应的 `network_requests` 与 `filter_decisions` 行数必须回到事务开始前的状态；`recording_recovery` 路径还必须额外保证 `actions` 行数同样回到事务开始前的状态（DuckDB ACID 保证）
- **AND** 上层若重试 recovery 入库，按"全新事务、全新 request_id"的语义处理，本 spec 不要求 upsert 幂等

#### Scenario: recovery 以单个 recording 为事务单元

- **WHEN** `recording_recovery` 恢复一个 queue file / recording_id
- **THEN** 该 recording 的 `actions`、`network_requests`、`filter_decisions` 写入必须共享同一个外层 DuckDB 事务
- **AND** 实现不得对同一 recording 采用“每 action 单独 COMMIT”的事务粒度

### Requirement: 五类规则的判定覆盖

系统 SHALL 按以下顺序评估规则，任一命中即判为 `decision="filter"`，不再评估后续规则：

1. OPTIONS 预检请求
2. 3xx 重定向响应
3. 静态资源（image / font / stylesheet / favicon 等非业务资源）
4. 广告 / 埋点域名黑名单
5. 第三方请求（按 registrable domain / eTLD+1 判定 first-party；同站多子域默认保留）

#### Scenario: OPTIONS 预检请求被判噪声

- **WHEN** 请求的 `method` 为 `OPTIONS`
- **THEN** `filtered=true`
- **AND** `filter_decisions.reason` 标注为 `"options_preflight"`

#### Scenario: 3xx 重定向被判噪声

- **WHEN** 响应的 `response_status` 在 300-399 范围
- **THEN** `filtered=true`
- **AND** `filter_decisions.reason` 标注为 `"redirect_3xx"`

#### Scenario: 静态资源被判噪声

- **WHEN** 请求的 URL 扩展名在静态资源白名单中（如 `.png / .jpg / .css / .woff / .ico`），或 `Content-Type` 匹配静态资源类型
- **THEN** `filtered=true`
- **AND** `filter_decisions.reason` 标注为 `"static_asset"`
- **AND** `filter_decisions.pattern_matched` 记录命中的扩展名或 Content-Type

#### Scenario: 跨域三方请求被判噪声

- **WHEN** 系统能从当前录制中识别出主域
- **AND** 请求 host 归一化后的 registrable domain / eTLD+1 不属于当前录制的 first-party 集合（`primary_site` 加配置白名单）
- **THEN** `filtered=true`
- **AND** `filter_decisions.reason` 标注为 `"third_party_cross_origin"`

#### Scenario: 同站多子域请求不被当成第三方

- **WHEN** 当前录制的主站为 `www.example.com`
- **AND** 请求发往 `api.example.com` 或 `static.example.com`
- **THEN** 只要这些 host 归一化后的 registrable domain / eTLD+1 仍为 `example.com`，系统就**不得**仅因 host 不同而产生 `third_party_cross_origin` 决策

#### Scenario: ccTLD 场景下同站子域正确识别

- **WHEN** 当前录制的主站为 `www.example.co.uk`
- **AND** 请求发往 `api.example.co.uk`
- **THEN** 系统依赖 Public Suffix List 正确识别 `co.uk` 为公共后缀，归一化结果为 `example.co.uk`
- **AND** 不得把请求判定为 `third_party_cross_origin`
- **AND** 实现不得采用"简单取末两段 domain"的近似策略，避免把 `co.uk` 当成 registrable domain

#### Scenario: 主域识别失败时跨域规则不生效

- **WHEN** 无法从录制中识别主域（如 actions 中没有 http/https URL）
- **THEN** 跨域规则跳过，不对任何请求产生 `third_party_cross_origin` 决策
- **AND** 其他四类规则照常评估

#### Scenario: 广告埋点黑名单命中

- **WHEN** 请求的 host 匹配配置的广告/埋点域名黑名单（如 `doubleclick.net / google-analytics.com / sentry.io`）
- **THEN** `filtered=true`
- **AND** `filter_decisions.reason` 标注为 `"ad_tracking_blacklist"`
- **AND** `filter_decisions.pattern_matched` 记录命中的 host 规则

#### Scenario: 黑名单命中优先于泛化跨域规则

- **WHEN** 某请求既命中广告/埋点黑名单，又满足跨域三方规则
- **THEN** 系统产生的决策 reason 必须是 `"ad_tracking_blacklist"`
- **AND** 不得再为同一请求产生 `third_party_cross_origin` 决策

### Requirement: 多源决策记录的数据格式

系统 SHALL 将每次决策写入 `filter_decisions` 表，字段语义如下：
- `source`: 决策来源，当前版本仅 `"rule"`；未来扩展 `"llm"` / `"human"`
- `decision`: `"filter"` 或 `"keep"`（**首版规则只产生 `"filter"`，不产生 `"keep"`，也不实现 keep 覆盖聚合；`keep` 值仅为未来扩展预留**；沿用 `duckdb_manager.py:377` 现有 schema 注释的枚举值）
- `reason`: 决策原因代号（如 `"options_preflight"`）
- `pattern_matched`: 命中的具体模式（如 URL 扩展名、黑名单 host）
- `confidence`: 置信度（规则源固定为 `1.0`）
- `request_id`: 关联的 `network_requests.request_id`；由于 `filter_decisions.request_id` 当前 schema 为 `TEXT`，写入时保存字符串化后的请求 ID

#### Scenario: 规则决策写入

- **WHEN** 任一规则对请求给出决策
- **THEN** 在 `filter_decisions` 表插入一条记录
- **AND** `source="rule"`，`decision="filter"`，`confidence=1.0`
- **AND** `request_id=str(network_requests.request_id)`，并与对应请求的 `action_id` / `recording_id` 正确关联

#### Scenario: 首版规则不产生 keep 决策（负向）

- **WHEN** 任意批量输入走完本次入库与规则流水线
- **THEN** `filter_decisions` 表中**不存在** `decision="keep"` 的行
- **AND** `decision="keep"` 枚举值仅为未来 `source="human"` 人工覆盖等扩展预留，首版规则不产出该值、也不实现相关的聚合覆盖逻辑

### Requirement: network_requests 聚合字段保存最终过滤结论

系统 SHALL 将最终聚合后的过滤结论写入 `network_requests.filtered` / `filter_reason` / `filtered_at` 三个字段，其中 `filter_reason` 保存最终生效决策的精简 JSON 摘要，`filtered_at` 仅在最终结果为 `filtered=true` 时写入。

#### Scenario: 被过滤的请求写入聚合摘要

- **WHEN** 某请求至少命中一条 `decision="filter"` 的决策
- **THEN** `network_requests.filtered=true`
- **AND** `network_requests.filter_reason` 写入 JSON 对象，至少包含 `decision` / `source` / `reason` 三个键；若有具体命中模式，则包含 `pattern_matched`
- **AND** `network_requests.filtered_at` 写入该最终决策落库时间

#### Scenario: filter_reason 的 JSON 编码由 Repository 统一处理

- **WHEN** 业务/驱动层把最终聚合决策传给 Repository 持久化
- **THEN** 调用方传递的是逻辑 JSON 对象（Python `dict`）或 `NULL`
- **AND** Repository 负责按项目现有 JSON 字段惯例统一序列化（`json.dumps(..., ensure_ascii=False)`）后写入 DuckDB JSON 列

#### Scenario: 未被过滤的请求保持空聚合字段

- **WHEN** 某请求未命中任何噪声规则
- **THEN** `network_requests.filtered=false`
- **AND** `network_requests.filter_reason IS NULL`
- **AND** `network_requests.filtered_at IS NULL`

### Requirement: Agent 查询侧默认过滤噪声且对 Agent 透明

系统 SHALL 确保 Agent 通过 `recording_data_tools` 的所有数据访问入口（`query_data` / `execute_code` / `describe_data`）都只能看到 `filtered=false` 的行，且 Agent 无法感知过滤机制、过滤字段、`filter_decisions` 表的存在。

#### Scenario: Agent 执行 SELECT 查询时自动过滤行与列

- **WHEN** Agent 通过 `query_data` 工具对 `network_requests` 执行 SELECT
- **THEN** 系统在执行前将 SQL AST 中每一处 `network_requests` 引用**替换为已过滤且已做列投影的派生表**（`SELECT <允许列白名单> FROM network_requests WHERE filtered = false`）
- **AND** 返回给 Agent 的结果中不包含 `filtered=true` 的行
- **AND** Agent 写 `SELECT *` 时，返回的列中**不包含** `filtered / filter_reason / filtered_at / is_recommendation / importance_level` 这五个隐藏列（派生表的列投影白名单已把它们剥掉）
- **AND** Agent 写 `SELECT filtered FROM network_requests` 时，**rewriter 不拒绝该 SQL**（语句类型合法、表名合法），但 duckdb 执行期会因列投影白名单找不到 `filtered` 而报正常 SQL 错误（`column does not exist`）；该错误不泄漏过滤设施（`filtered` 在派生表中确实不存在，与查任意不存在列名无异），正常返回给 Agent 帮助其修正 SQL

#### Scenario: Agent 通过 JOIN 访问网络请求时保留 JOIN 语义

- **WHEN** Agent 的 SQL 中以 `INNER / LEFT / RIGHT / FULL JOIN`、子查询或 CTE 方式引用 `network_requests`
- **THEN** 改写逻辑**始终把 `network_requests` 表节点替换为派生表**（不使用"往 ON 追加条件"策略），保证任意 JOIN 类型语义都正确
- **AND** 对于 `RIGHT/FULL JOIN network_requests`，替换为派生表后 filtered=true 的行在 JOIN 前就已被过滤，不会以 unmatched 行的形式残留在结果里
- **AND** 对于 `actions LEFT JOIN network_requests`，左表中原本没有对应网络请求的行**仍被保留**（派生表替换不影响外连接对左表的保留语义）

#### Scenario: Agent 通过 query_data 直接查询 filter_decisions 被拒绝

- **WHEN** Agent 的 SQL 中以 `FROM filter_decisions` / `JOIN filter_decisions` 等形式引用 `filter_decisions` 表
- **THEN** 系统拒绝执行该查询，返回不泄漏过滤机制的错误（如 "SQL 解析失败，请简化查询后重试"）
- **AND** 在日志中记录被拒绝的原始 SQL

#### Scenario: Agent 通过 execute_code 的 conn 查询时同样被过滤

- **WHEN** Agent 通过 `execute_code` 注入的 `conn` 调用 `.execute()` / `.sql()` 等方法访问 `network_requests`
- **THEN** 这些调用必须经过与 `query_data` 相同的 SQL 改写链路
- **AND** Agent 无法通过绕道 `conn.execute("SELECT * FROM network_requests")` 读到 `filtered=true` 的行

#### Scenario: Agent 查询 describe_data 时看不到过滤字段与过滤表

- **WHEN** Agent 调用 `describe_data` 查看录制数据库的字段文档
- **THEN** `network_requests` 表的字段描述中**不**包含 `filtered` / `filter_reason` / `filtered_at` / `is_recommendation` / `importance_level` 这五个字段
- **AND** 返回结果中**不**包含 `filter_decisions` 表的任何信息（表名、字段、描述均不可见）

#### Scenario: Agent 查询 describe_data 时看不到隐藏行数量

- **WHEN** Agent 调用 `describe_data` 查看表概览或 `network_requests` 的详情
- **THEN** 返回的 `network_requests.row_count` 只统计 `filtered=false` 的可见行
- **AND** Agent 不能通过 `describe_data` 的计数结果反推出被隐藏的噪声请求数量

#### Scenario: 错误提示不泄漏过滤设施

- **WHEN** Agent 的 SQL 执行失败，`query_data` / `execute_code` 在错误信息中返回"可用表"清单
- **THEN** 清单中**不**包含 `filter_decisions`
- **AND** 错误信息中不出现 `filtered` / `filter_reason` 等过滤相关字段名

#### Scenario: SQL 改写失败时拒绝查询

- **WHEN** SQL 解析或改写过程中发生异常（如 Agent 写了语法错误的 SQL、或改写器未覆盖的嵌套模式）
- **THEN** 系统**拒绝执行该查询**，向 Agent 返回一条不提及过滤机制的错误（如 "SQL 解析失败，请简化查询后重试"）
- **AND** 在日志中记录改写失败的原始 SQL 与异常信息，以便后续补测
- **AND** 绝不允许放行原 SQL 执行，防止噪声数据穿透契约

#### Scenario: query_data 的 duckdb 执行期异常正常返回

- **WHEN** Agent 通过 `query_data` 提交 `SELECT filtered FROM network_requests`，rewriter 不拒绝（语句类型合法），但 duckdb 因列投影白名单执行时抛 `BinderException: column "filtered" does not exist`
- **THEN** 业务工具层将该 duckdb 错误信息正常返回给 Agent（含可用表清单，清单中不含 `filter_decisions`）
- **AND** 该错误不泄漏过滤设施——`filtered` 在派生表中确实不存在，与查询任意不存在的列名报同样的错

#### Scenario: execute_code 中 rewriter 拒绝类异常被代理层脱敏

- **WHEN** Agent 在 `execute_code` 中运行 `try: conn.execute("SELECT * FROM filter_decisions") except Exception as e: print(e)`
- **THEN** `FilteredDuckDBConnection` / `FilteredDuckDBCursor` / `FilteredDuckDBRelation` 必须在代理层把 rewriter 拒绝类异常包装成泛化错误，再抛给 Agent 代码
- **AND** Agent 捕获并打印出来的异常文本为泛化文案（"SQL 解析失败，请简化查询后重试" 或 "数据访问受限"）
- **AND** duckdb 执行期异常和 Agent 代码运行时异常正常透传，帮助 Agent 定位问题

#### Scenario: CTE 名称遮蔽 network_requests 时不触发改写

- **WHEN** Agent 提交 `WITH network_requests AS (SELECT 1 AS x) SELECT * FROM network_requests`
- **THEN** rewriter 基于 AST 识别 `FROM network_requests` 指向 CTE 本地名而非物理表，**不**触发派生表替换
- **AND** 查询正常执行，结果为 CTE 定义的内容

#### Scenario: CTE 内部引用物理 network_requests 时仍被改写

- **WHEN** Agent 提交 `WITH decoy AS (SELECT * FROM network_requests) SELECT * FROM decoy`
- **THEN** CTE 内部的 `FROM network_requests` 指向物理表，**必须**被改写为带 `filtered = false` 的派生表
- **AND** 外层 `SELECT * FROM decoy` 通过 CTE 间接访问时，结果仍只含 `filtered=false` 行

#### Scenario: 标识符大小写变体被识别

- **WHEN** Agent 提交 `SELECT * FROM NETWORK_REQUESTS` / `SELECT * FROM Network_Requests` / `SELECT * FROM "NETWORK_REQUESTS"`
- **THEN** rewriter 均识别为 `network_requests` 物理表引用并就地改写（DuckDB 标识符默认大小写不敏感）

#### Scenario: 注释或字符串字面量中的名字不触发改写

- **WHEN** Agent 提交 `SELECT 'network_requests' AS name, 'filter_decisions' AS name2` 或 `SELECT 1 -- FROM network_requests` 或 `SELECT 1 /* FROM network_requests */`
- **THEN** rewriter **不**因字符串字面量或 SQL 注释中出现 `network_requests` / `filter_decisions` 而触发改写或拒绝（由 sqlglot AST 天然保证）
- **AND** 查询按原语义正常执行
- **AND** 现有 `_query_data` 中基于正则硬拒绝 `--` / `/*` 等注释符号的护栏**必须在本次变更中同步删除**，由 AST 校验统一负责，否则本 scenario 不可达

#### Scenario: 参数化查询的占位符顺序不被改写破坏

- **WHEN** 调用方通过 `conn.execute(sql, parameters=[...])` 提交带 `?` 占位符的 SQL（例如 `SELECT * FROM network_requests WHERE method = ? AND response_status = ?`）
- **THEN** rewriter 将 `network_requests` 就地替换为派生表时**不得**新增 / 删除 / 改变 `?` 占位符的数量和相对顺序
- **AND** 改写后的 SQL 与原 `parameters` 列表一一对应，DuckDB 绑定语义不变
- **AND** 派生表 WHERE 子句使用字面量 `filtered = false`，不引入新的占位符

### Requirement: 噪声请求的 response_body 保留

系统 SHALL 对被判为噪声的请求也原样保留其 `response_body` 字段值，不做任何物理删除或截断。

#### Scenario: 噪声请求的原始数据可恢复

- **WHEN** 请求被判为 `filtered=true`
- **THEN** `network_requests.response_body` 字段仍包含完整的原始响应体
- **AND** 通过数据库直接查询（非 Agent 路径）时可读到原始内容

#### Scenario: 入库后 response_body 不被噪声打标逻辑修改

- **WHEN** `NoiseFilterPipeline` 对请求给出 `decision="filter"` 决策
- **THEN** 入库代码**不修改** `response_body` 的值（不截断、不置空、不 base64 编码）
- **AND** 回归测试断言：`filtered=true` 行的 `response_body` 与入库前原始值完全相同

### Requirement: LLM 判断接口的扩展占位

系统 SHALL 在过滤模块中定义 LLM 判断接口，但首版始终返回 `None`，不产生 `filter_decisions` 记录。

#### Scenario: 首版 LLM 接口不产生任何决策

- **WHEN** 入库规则流水线调用 LLM 判断接口
- **THEN** 接口返回 `None`
- **AND** `filter_decisions` 表中不出现 `source="llm"` 的记录

### Requirement: ingest_hook 接口标准化输入输出与 request_id 映射

系统 SHALL 通过标准化 `IngestBatch` 数据类统一两条入库路径的输入，保证 `filter_decisions` 行的 `request_id` 正确关联。

**`IngestBatch.actions` 字段约定**：列表中的每个 dict 对应一次录制 action，URL 从 `action["url"]` 键读取（与 `duckdb_recording_persister.convert_event_to_action_dict` 的现有约定一致）；若 dict 缺少 `url` 键、或 `url` 非 `http(s)://` 开头、或 URL 无法被 `urllib.parse.urlsplit` 正常拆分，该 action 不参与 `primary_host` 推断。`IngestBatch.network_requests` 列表中每个 dict 必须包含 `url` / `method` / `response_status` 以及可选 `request_headers` / `response_headers`（Content-Type 从 `response_headers` 大小写不敏感查找）。

#### Scenario: recovery 复用队列解析得到的 action dict 作为 IngestBatch.actions

- **WHEN** `recording_recovery` 为某个 recording 构造 `IngestBatch`
- **THEN** `IngestBatch.actions` 必须来自恢复阶段已解析并保留在内存中的 action dict 列表
- **AND** 不得通过回查 `actions` 表或其他已入库结果来重建该列表

#### Scenario: save_network_requests 返回 batch_index→request_id 映射供决策组装

- **WHEN** `ingest_hook` 打标返回带 `batch_index` 的 `FilteredRequestResult` 列表
- **AND** `save_network_requests` 完成入库
- **THEN** `save_network_requests` 必须返回 `{batch_index: request_id}` 的映射（与入参列表序号一一对应）
- **AND** 用该映射组装 `FilterDecision` 行后，`filter_decisions.request_id` 必须等于 `CAST(network_requests.request_id AS VARCHAR)`

#### Scenario: recovery 路径的 IngestBatch 与 persister 路径产生相同决策

- **WHEN** 相同的一批 `network_requests` 分别通过正常入库路径和恢复路径入库
- **THEN** 两条路径产生的 `filtered` 值与 `filter_decisions.reason` 完全一致（相同输入产生相同输出）

### Requirement: is_recommendation 和 importance_level 字段保持 schema 默认值

系统 SHALL 在首版实现中**不主动写入** `network_requests.is_recommendation` 和 `network_requests.importance_level` 字段，让 DuckDB 按 schema 默认值填充（`is_recommendation=FALSE`、`importance_level='unknown'`），并在 `describe_data` 中对 Agent 隐藏这两个字段。

#### Scenario: 入库时两个字段取 schema 默认值

- **WHEN** 任意请求入库
- **THEN** `is_recommendation` 字段值为 `FALSE`（schema 默认）
- **AND** `importance_level` 字段值为 `'unknown'`（schema 默认）
- **AND** 规则判定代码不显式 SET 这两个字段

### Requirement: 入库侧规则判定可通过配置关闭

系统 SHALL 提供配置开关 `recording.noise_filter.enabled`，允许禁用**入库侧**规则判定与决策写入以便回滚；该开关不得放松 Agent 查询侧的只读 / 隐藏 / 脱敏契约。

#### Scenario: 配置关闭时行为等同当前实现

- **WHEN** `recording.noise_filter.enabled=false`
- **THEN** 入库时所有请求的 `filtered` 字段写入 `false`
- **AND** `filter_decisions` 表不产生任何记录
- **AND** `filter_reason` / `filtered_at` 保持 `NULL`
- **AND** Agent 查询侧仍保持现有只读 / 隐藏 / 脱敏防护；由于所有行均为 `filtered=false`，Agent 可见的数据行集合与当前全量视图一致

#### Scenario: 配置关闭时不得实例化过滤链路

- **WHEN** `recording.noise_filter.enabled=false`
- **THEN** 系统**不得**在入库链路实例化 `NoiseFilterPipeline` / `LLMNoiseJudge`
- **AND** `ingest_hook` 在入口处短路返回（所有请求标记 `filtered=False`，且 `filter_reason` / `filtered_at` 为空），不进入规则判定流程
- **AND** `sql_rewriter` / `FilteredDuckDBConnection` 若在 Agent 查询链路中被使用，仍只用于维持查询侧契约，而不是重新开启入库规则判定
- **AND** 开关关闭的状态不引入额外启动耗时或日志误报

### Requirement: execute_code 注入的 conn 必须是受限代理（连接 + Relation 双层，方法级 allow/deny）

系统 SHALL 为 `execute_code` 工具注入给 Agent 的 `conn` 变量提供一个**两层受限代理**，连接层与 Relation 层方法分级如下：

**连接层**：
- `.execute / .executemany / .sql / .from_query / .query`：走 `sql_rewriter`，允许只读 SELECT；若底层 DuckDB 执行抛异常，代理必须先把异常文本脱敏后再抛出
- `.cursor()`：返回 `FilteredDuckDBCursor` 代理，`.execute()` 走同一链路
- `.table("network_requests")`：返回 `FilteredDuckDBRelation`，底层等价于 `SELECT <允许列> FROM network_requests WHERE filtered=false`
- `.table("filter_decisions")` / `.view(*)`：拒绝
- `.table(其他表)`：返回代理 Relation（防止链式 `.query(sql)` 绕过）
- `.create_view / .read_csv / .read_parquet / .from_df / .from_arrow / .register`：一律**拒绝**

**Relation 层**：
- `.filter / .project / .select / .join / .aggregate / .order / .limit / .distinct / .union / .except_ / .intersect / .set_alias / .apply` 等返回新 Relation 的方法：必须把返回值**重新包装**为 `FilteredDuckDBRelation` 代理
- `.query(alias, sql)`：首版一律**拒绝**（不尝试嵌入别名 rewrite，详见决策 13）
- `.create_view() / .df / .pl / .arrow / .fetchdf / .fetch_df / .to_df`：拒绝
- `.fetchall / .fetchone / .fetchmany`：透传物化（Relation 在构造时已过滤，且不依赖额外 dataframe/arrow 可选库）

#### Scenario: Agent 在 execute_code 中直接跑 SQL 时被改写

- **WHEN** Agent 的 Python 代码中执行 `conn.execute("SELECT * FROM network_requests")`
- **THEN** 实际执行的 SQL 被就地改写为带 `filtered = false` 的等价形式
- **AND** 返回的结果集中不含 `filtered=true` 的行

#### Scenario: Agent 尝试绕过改写查询 filter_decisions 时受限

- **WHEN** Agent 在 `execute_code` 中执行 `conn.execute("SELECT * FROM filter_decisions")`
- **THEN** 系统拒绝该查询（统一按"SQL 改写/鉴权失败拒绝"的策略），返回不泄漏过滤机制的错误提示

#### Scenario: Agent 通过 cursor 派生句柄时同样受限

- **WHEN** Agent 执行 `cur = conn.cursor(); cur.execute("SELECT * FROM network_requests")`
- **THEN** `cur.execute` 必须走同一条 SQL 改写链路
- **AND** 结果集中不含 `filtered=true` 的行

#### Scenario: Agent 通过 Relation API 派生句柄时同样受限

- **WHEN** Agent 执行 `rel = conn.table("network_requests"); rel.fetchall()` 或 `conn.from_query("SELECT * FROM network_requests").filter("...").fetchall()`
- **THEN** 物化时底层执行的 SQL 必须已包含 `filtered = false` 过滤
- **AND** 返回的结果集中不含 `filtered=true` 的行

#### Scenario: Agent 调用 conn.register 被拒绝

- **WHEN** Agent 执行 `conn.register("foo", some_df)`
- **THEN** 代理拒绝该调用（避免后续 `SELECT * FROM foo` 绕过过滤），返回不泄漏过滤机制的错误提示

#### Scenario: Agent 调用 view 或 dataframe materializer 被拒绝

- **WHEN** Agent 执行 `conn.view("network_requests")`、`rel.df()`、`rel.pl()`、`rel.arrow()`、`rel.fetchdf()`、`rel.fetch_df()` 或 `rel.to_df()`
- **THEN** 代理拒绝该调用，返回不泄漏过滤机制的错误提示
- **AND** 理由：这些路径要么要求解析既有 view definition，要么依赖当前项目未引入且沙箱也禁止使用的可选 dataframe/arrow 库

#### Scenario: Agent 调用 Relation.query 被拒绝

- **WHEN** Agent 执行 `conn.table("network_requests").query("nr", "SELECT * FROM nr WHERE method='GET'")`
- **THEN** 代理拒绝该调用
- **AND** 理由：`Relation.query(alias, sql)` 的 sql 中以调用方指定的别名（`nr`）嵌入式引用当前 relation，rewriter 在无上下文时无法稳妥区分"该别名是 relation 引用"还是"该别名是物理表 `nr`"；首版不承诺此路径，Agent 应改用链式 `.filter() / .project()` 达成等价效果

### Requirement: query_data 与 execute_code 仅接受只读 SELECT 语句

系统 SHALL 对 `query_data` 和 `execute_code` 代理执行的 SQL 做**语句类型白名单校验**：仅允许 `SELECT`（包含 `WITH ... SELECT`、`SELECT ... UNION [ALL] / EXCEPT [ALL] / INTERSECT [ALL] SELECT` 等 SELECT 级集合操作）；其他语句一律拒绝。

#### Scenario: 拒绝 DDL 语句

- **WHEN** Agent 提交 `CREATE TABLE` / `CREATE VIEW` / `CREATE TEMP VIEW AS SELECT ...` / `DROP` / `ALTER` / `ATTACH` / `DETACH`
- **THEN** 系统拒绝查询，返回不泄漏过滤机制的泛化错误
- **AND** 理由：`CREATE TEMP VIEW AS SELECT ... FROM network_requests` 可把未过滤数据物化后再查，直接违背透明过滤契约

#### Scenario: 拒绝 DML 语句

- **WHEN** Agent 提交 `INSERT` / `UPDATE` / `DELETE` / `MERGE` / `COPY`
- **THEN** 系统拒绝查询
- **AND** 理由：`UPDATE network_requests SET filtered = false` 可直接篡改过滤结果

#### Scenario: 拒绝元数据与 catalog 查询

- **WHEN** Agent 提交 `SHOW TABLES` / `SHOW COLUMNS` / `DESCRIBE <table>` / `PRAGMA table_info(...)` / `EXPLAIN ...`
- **AND/OR** SQL 中引用 `information_schema.*` schema 下对象，或任何**以 `duckdb_` 或 `pragma_` 为前缀**的表函数 / 系统表（例如 `duckdb_tables()` / `duckdb_columns()` / `duckdb_views()` / `duckdb_schemas()` / `duckdb_databases()` / `duckdb_functions()` / `duckdb_keywords()` / `duckdb_settings()` / `duckdb_types()` / `pragma_version()` / `pragma_database_list()` 等——采用前缀匹配而非固定清单）
- **THEN** 系统拒绝查询
- **AND** 理由：这些路径会让 Agent 感知到 `filter_decisions` 表和隐藏字段的存在

### Requirement: execute_code 沙箱禁止导入 pandas / polars / pyarrow

系统 SHALL 在 `execute_code` 沙箱的导入白名单中**继续禁止** `pandas` / `polars` / `pyarrow` 三个库，防止 Agent 通过 `pandas.read_sql(conn, sql)` 或 Relation `.df() / .pl() / .arrow()` 的外部消费路径绕过代理。

#### Scenario: Agent 尝试导入 pandas 被拒绝

- **WHEN** Agent 在 `execute_code` 中执行 `import pandas`（或 `polars` / `pyarrow`）
- **THEN** 沙箱抛出 `ImportError`（与现有沙箱行为一致），Agent 无法使用这些库的 SQL 消费 API

### Requirement: SQL 改写覆盖矩阵

系统 SHALL 对 `network_requests` 引用在以下所有 SQL 模式下都能正确改写（就地过滤且保持原语义）：

1. 简单 `SELECT ... FROM network_requests [AS alias]`
2. `INNER / LEFT / RIGHT / FULL JOIN network_requests`
3. 子查询中的 `network_requests`
4. CTE（`WITH x AS (... FROM network_requests)` / `WITH RECURSIVE`）
5. `UNION [ALL]` 的各分支中的 `network_requests`
6. schema-qualified 引用：`main.network_requests`
7. 带引号标识符：`"network_requests"`、`"main"."network_requests"`
8. 多层嵌套的 CTE / 子查询组合中的 `network_requests`
9. 大小写变体：`NETWORK_REQUESTS` / `Network_Requests` / `"NETWORK_REQUESTS"`（DuckDB 标识符大小写不敏感）

同时 SHALL 保证以下场景**不**触发改写或拒绝：

- CTE 本地名遮蔽：`WITH network_requests AS (...) SELECT * FROM network_requests` 中的 `FROM network_requests` 指向本地 CTE 而非物理表
- 字符串字面量或 SQL 注释中的 `network_requests` / `filter_decisions` 文本

#### Scenario: UNION 分支中的 network_requests 被就地改写

- **WHEN** Agent 提交 `SELECT id FROM network_requests WHERE method='GET' UNION ALL SELECT id FROM network_requests WHERE method='POST'`
- **THEN** 两个分支的 `network_requests` 引用**各自**被改写为带 `filtered = false` 的等价子查询

#### Scenario: schema-qualified 与带引号标识符被识别

- **WHEN** Agent 提交 `SELECT * FROM main.network_requests` 或 `SELECT * FROM "network_requests"`
- **THEN** 改写器识别该引用为 `network_requests` 并就地改写

### Requirement: 历史录制数据不追溯打标

系统 SHALL 仅对新录制应用噪声过滤规则，不对已存储的历史录制数据重新判定或修改。

#### Scenario: 已有录制的 filtered 字段保持当前值

- **WHEN** 本次变更部署后
- **THEN** 已存在于 DuckDB 中的 `network_requests` 行的 `filtered` 字段保持原值（当前均为 `false`）
- **AND** Agent 查询历史录制时，能看到所有行（因为 `filtered=false`）

#### Scenario: 历史数据不被追溯打标（回归测试）

- **WHEN** 本次变更部署、且有历史录制数据存在于 DuckDB
- **THEN** 部署前后对同一历史录制的 `network_requests` 行数和 `filtered` 值完全相同
- **AND** `filter_decisions` 表中不存在历史录制的任何决策行

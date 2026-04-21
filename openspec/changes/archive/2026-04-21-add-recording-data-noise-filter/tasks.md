## 1. 前置准备与依赖

- [x] 1.1 在 `pyproject.toml` `dependencies` 中新增两个依赖，运行 `uv sync` 刷新锁定文件；为 import 位置约束写门卫单测：`sqlglot` / `tldextract` **只允许出现在 `src/recording/filtering/` 目录下**
  - `sqlglot>=23.0.0,<30.0.0`（决策 10；`<30.0.0` 上限用于规避未来大版本 API 破坏）
  - `tldextract>=5.0.0,<6.0.0`（决策 16；eTLD+1 归一化依赖 Public Suffix List）
- [x] 1.2 在 `AppConfig` 中新增 `RecordingNoiseFilterConfig` 数据类（`enabled` / 黑名单域列表 / first-party 白名单 / 静态资源扩展名清单等）
- [x] 1.3 在 `unified_config.py` 添加对应 getter，集成进 `recording.*` 命名空间
- [x] 1.4 更新 `config.example.json` 增加 `recording.noise_filter` 段的默认值

## 2. 过滤规则模块（纯函数，无副作用）

- [x] 2.1 新建 `src/recording/filtering/__init__.py` 作为模块入口（驱动层）
- [x] 2.2 新建 `src/recording/filtering/rules.py`，实现五个规则判定函数：`is_options_preflight` / `is_redirect_3xx` / `is_static_asset` / `is_third_party` / `matches_blacklist`
- [x] 2.3 新建 `src/recording/filtering/primary_host.py`，实现从 `actions` 列表（每个 action 为 dict，URL 取 `action["url"]` 字段）派生 `primary_host`，并基于 `tldextract` 实现 host → registrable domain / eTLD+1 的归一化辅助函数（决策 16）：
  - 模块加载期构造一次 `TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)` 并复用，禁止每次调用都触发 PSL IO
  - 无 `url` 键 / `url` 非 `http(s)://` / URL 无法解析 / host 为 IP 地址 / host 为单段 hostname（如 `localhost`，`suffix` 为空）时，`primary_host` 返回 `None`，跨域规则保守跳过
- [x] 2.4 新建 `src/recording/filtering/decision.py`，定义 `FilterDecision` dataclass 与序列化逻辑（`decision` 字段使用 `"filter" | "keep"` 枚举；**首版只产出 `"filter"`**）
- [x] 2.5 新建 `src/recording/filtering/pipeline.py`，实现 `NoiseFilterPipeline` 类：按顺序调用规则 → 首个命中即产生 `FilterDecision(decision="filter", ...)` → 无命中返回 `None`（**不产生 `keep`，不实现聚合覆盖**）
- [x] 2.6 新建 `src/recording/filtering/llm_judge.py`，实现 `LLMNoiseJudge` 空接口类（`judge()` 始终返 `None`）
- [x] 2.7 为 `rules.py` 每条规则写单元测试（含正样本、负样本、边界情况）
- [x] 2.8 为 `primary_host.py` 写单元测试：
  - 空 actions、非 http URL、多个不同域的情况
  - `www.example.com` / `api.example.com` 归一化到同一 first-party 站点键
  - **ccTLD 场景**：`www.example.co.uk` 与 `api.example.co.uk` 归一化后必须相同（`example.co.uk`），而不是被截成 `co.uk`
  - host 为 IP 地址（`127.0.0.1` / `::1`）、`localhost`、空 host 时归一化返回 `None`
  - 断言 `tldextract` 不触发网络请求（可通过 mock / 检查 `requests` 未被调用 / 使用 `suffix_list_urls=()` 配置）
- [x] 2.9 为 `pipeline.py` 写组合测试（规则顺序验证、**黑名单优先于跨域三方的 reason 优先级**、命中即停验证、全不命中的行为）

## 3. 数据层：Repository 写入方法

- [x] 3.1 在 `src/data/recording_repository.py` 新增 `save_filter_decisions(decisions: List[FilterDecision])` 方法，批量写 `filter_decisions` 表
- [x] 3.2 在 `RecordingRepository` **直接更新** `save_network_requests` 签名（**不**保留 overload / 兼容 shim），改为接收 recording-scoped 的 request rows 列表：每条自带 `action_id`（可空）/ `filtered` / `filter_reason` / `filtered_at`。其中 `filter_reason` 由调用方传 Python `dict | None`，Repository 统一 `json.dumps(..., ensure_ascii=False)` 后写入。**`batch_index` 语义**：`batch_index` **不作为入参 row 字段**，而是由 Repository 按**入参列表的 0-based 序号**隐式分配；`save_network_requests` 返回 `{batch_index: request_id}` 映射，其中 `batch_index` 等于该 row 在入参列表中的索引（调用方必须保证把 `FilteredRequestResult.batch_index` 赋值为入参列表索引，两者语义对齐）。**签名变更影响面**：先 grep 现有 `save_network_requests(` 调用点，确认并同步改完 `duckdb_recording_persister.py` ×2、`recording_recovery.py` ×2、`tests/data/test_recording_repository_timezones.py` ×2 这 6 处直接调用
- [x] 3.2a 两个 Repository 方法 (`save_network_requests` / `save_filter_decisions`) 必须**参与外层事务**、不提前提交。**行为断言测试**（而非字面 grep，因为两个方法当前都委托给 `DuckDBManager.insert_many`，`insert_many` 已是事务感知的——未进入外层事务时自发 `BEGIN/COMMIT`，进入外层事务时透传；字面 grep `self.conn.commit()` 必然通过，给不了有效保证）：
  - (a) `with db.transaction(): save_network_requests(...); save_filter_decisions(...); raise` → 断言两张表对应 `recording_id` 的行数都回到事务开始前的状态（若 Repository 方法自发 COMMIT，就会有残留）
  - (b) `with db.transaction(): save_network_requests(...)` 然后检查事务仍是打开状态（`DuckDBManager._transaction_depth() > 0`），验证未被提前提交
  - (c) 不需要 grep 字面 `commit()` 调用——那不是本 spec 的真实约束
- [x] 3.3 为新增 Repository 方法编写单元测试（含事务回滚场景）

## 4. 驱动层：接入入库流程

- [x] 4.1 确认 `src/recording/browser/duckdb_recording_persister.py` 的 `_extracted_network_request` 已携带 `request_headers` / `response_headers`（当前实现已满足）；`Content-Type` 从 `response_headers` 中取（大小写不敏感查找，兼容 `content-type` / `Content-Type` / `CONTENT-TYPE`）——若发现字段缺失再扩展 `_extracted_network_request`，否则本条任务免做
- [x] 4.2 新建 `src/recording/filtering/ingest_hook.py`，定义 `IngestBatch` 数据类（`recording_id / actions: List[dict] / network_requests: List[dict]`）与 `FilteredRequestResult`（携带原始 dict + 决策 + `batch_index` + `action_list_index: int | None`，其中 standalone request 为 `None`）；实现 `run_filter_hook(batch: IngestBatch, config) -> List[FilteredRequestResult]` 纯函数（入口处检查 `enabled=false` 则短路返回全 `filtered=False`）
- [x] 4.3 在 `save_to_duckdb` 中构造 `IngestBatch` 并调用 `run_filter_hook`，遍历 `standalone_network_requests` 和 `network_requests_map` 产出决策
- [x] 4.4 实现"先识别 `primary_host/primary_site` 再判定"的两遍流程：第一遍读 `actions` 推断主站与 first-party 站点键，第二遍跑规则；同一 registrable domain / eTLD+1 的多子域请求不得仅因 host 不同被判第三方
- [x] 4.5 将 `filtered` / `filter_reason` / `filtered_at` 聚合结果传给 `save_network_requests`；`filter_reason` 写最终生效决策的 JSON 摘要、未过滤时保持 `NULL`；用其返回的 `{batch_index: request_id}` 映射组装 `FilterDecision` 行，并在写 `filter_decisions` 时显式字符串化 `request_id`
- [x] 4.6 调用 `save_filter_decisions` 批量写决策（在同一事务内，见 4.11）
- [x] 4.7 规则流水线调用 `LLMNoiseJudge.judge()`（首版返 None 不产生决策）
- [x] 4.8 **不**显式写入 `is_recommendation` / `importance_level`，让 DuckDB 使用 schema 默认值（`FALSE` / `'unknown'`）；写单测断言入库后这两列取默认值。**前置修复**：当前 `src/data/duckdb_manager.py` 的 `network_requests` CREATE TABLE 中 `importance_level TEXT` 没有 DEFAULT（新装机会落 `NULL`），与迁移路径的 `DEFAULT 'unknown'` 漂移——本任务必须把 CREATE TABLE 改为 `importance_level VARCHAR DEFAULT 'unknown'`，否则新装机断言必炸；同步在测试里覆盖"全新数据库建表后再入库"与"旧库走迁移后再入库"两条路径
- [x] 4.9 加入 `recording.noise_filter.enabled=false` 的短路分支：关闭时所有请求按旧行为写 `filtered=false`，且 `filter_reason=NULL` / `filtered_at=NULL`，不产生任何决策
- [x] 4.10 在 `src/data/recording_recovery.py` 的恢复入库路径**显式重构事务结构**：针对每个 recovered recording/session，先保留队列解析得到的 action dict 列表作为 `IngestBatch.actions`，再把 `action_network_requests` 与 `standalone_network_requests` 扁平化为一个 recording-scoped `IngestBatch`；`save_actions` 后用 `action_list_index -> action_id` 映射补全每条 request 的最终 `action_id`，然后**只调用一次** `save_network_requests`、**只调用一次** `save_filter_decisions`。不得继续使用"逐 action 调 `save_network_requests`"的旧结构，也不得回查 `actions` 表重建 `IngestBatch.actions`
- [x] 4.11 保证两条入库路径（`save_to_duckdb` 与 `recording_recovery`）中的相关写入在**同一 DuckDB 事务内提交**；任一失败则一起回滚。**事务内必须覆盖的写入**：
  - `save_to_duckdb` 路径：`save_actions` → `save_sibling_snapshot`（若有） → `save_network_requests` → `save_filter_decisions`（当前实现已用 `db.transaction()` 包住 actions/snapshots/network_requests，本任务只需把 `save_filter_decisions` 纳入同一事务）
  - `recording_recovery` 路径：`save_recording_session` → `save_actions` → `save_sibling_snapshot`（若有） → `save_network_requests` → `save_filter_decisions` 全部包在同一外层 `db.transaction()` 里（当前 recovery 完全无外层事务，是本任务的主要重构点）
  - 事务内**不需要**覆盖 `_save_screenshots`（持久化到 DuckDB 的时机与规则判定无直接依赖，保持在当前外层事务里即可）；若实现同时把 screenshots 也纳入同一事务，也不禁止
  - **事务边界归属**：由外层调用方显式发 `BEGIN TRANSACTION` / `COMMIT` / `ROLLBACK`（决策 8），Repository 方法不 COMMIT（委托给 `DuckDBManager.insert_many` 的事务感知实现自动透传）；推荐直接使用现有的 `db.transaction()` context manager 以避免遗漏 ROLLBACK 分支
  - **recovery 粒度**：一个 recovered recording/session = 一个事务单元，绝不按 action 分事务；一次 recovery 多个 session 时，每个 session 各自一个事务
- [x] 4.12 写集成测试：构造一批包含所有五类噪声的请求 → 走完整入库链路 → 断言 `filtered` / `filter_reason` / `filtered_at` / `filter_decisions` 的写入正确；断言 `filter_decisions.request_id = CAST(network_requests.request_id AS VARCHAR)`，并覆盖“同站多子域不被误判第三方”
- [x] 4.13 写恢复路径测试：构造 crash-and-recover 场景 → 断言恢复入库后 `filtered` / `filter_decisions` 与正常路径完全一致（相同输入产生相同输出）
- [x] 4.14 写事务回滚测试（**双向**覆盖）：(a) mock `save_filter_decisions` 抛异常，(b) mock `save_network_requests` 抛异常 —— `save_to_duckdb` 路径断言 `network_requests` / `filter_decisions` / `sibling_snapshots` 三张表中该 `recording_id` 的行数都回到事务前状态（`actions` 表由现有外层 `db.transaction()` 保证，一并覆盖）；`recording_recovery` 路径除 `network_requests` / `filter_decisions` / `sibling_snapshots` 外，还必须断言 `actions` 与 `recording_sessions` 表中该 `recording_id` 的行数同样回到事务前状态（DuckDB ACID 保证）。两条入库路径（persister / recovery）分别测，共 4 组用例；外加"回滚后同一 `recording_id` 重新入库"场景：断言能成功写入完整数据（首版 recovery 不做幂等 upsert，见决策 14——上层保证重入前该 recording_id 不存在或属于已提交历史）
- [x] 4.15 写 response_body 保留测试：断言 `filtered=true` 行的 `response_body` 与入库前原始值完全相同（不截断、不置空）
- [x] 4.16 写历史数据不回填测试：预置历史录制数据 → 运行新版入库逻辑 → 断言历史 `network_requests` 行不被修改、`filter_decisions` 无历史录制行
- [x] 4.17 写首版枚举断言测试：构造含五类噪声的批量入库 → 断言 `filter_decisions` 表中**不存在** `decision="keep"` 行（首版规则不产出 keep，见决策 2 / spec L98）

## 5. 驱动层：SQL 改写核心与受限连接代理

> 过滤策略核心放在驱动层（`src/recording/filtering/`），业务工具层只做装配，不持有策略。

- [x] 5.1 新建 `src/recording/filtering/sql_rewriter.py`，基于 `sqlglot` AST 实现两件事：
  - **语句类型白名单**：顶层必须是 `SELECT`（含 `WITH ... SELECT`、`SELECT ... UNION [ALL] SELECT`）。拒绝 DDL（`CREATE / DROP / ALTER / ATTACH / DETACH`，含 `CREATE TEMP VIEW`）、DML（`INSERT / UPDATE / DELETE / MERGE / COPY`）、元数据（`SHOW / DESCRIBE / PRAGMA / EXPLAIN`）、catalog（引用 `information_schema.*` schema；或**以 `duckdb_` / `pragma_` 为前缀**的任意表函数 / 系统表，例如 `duckdb_tables()` / `duckdb_columns()` / `duckdb_views()` / `duckdb_schemas()` / `duckdb_functions()` / `pragma_version()` 等——采用 AST 名字前缀匹配，而非对固定清单硬编码）
  - **就地派生表替换**：对每一处 `network_requests` 引用统一替换为 `(SELECT <允许列白名单> FROM network_requests WHERE filtered = false)` 派生表（**不使用"往 JOIN ON 追加条件"策略**，避免 RIGHT/FULL JOIN 语义错误）；识别 schema-qualified（`main.network_requests`）、带引号标识符（`"network_requests"`）、CTE / 子查询中的引用、UNION 各分支
  - 检测到 `filter_decisions` 引用时直接抛拒绝异常
  - 拒绝或解析失败时抛出的异常类型供业务层统一捕获并按决策 12 脱敏（错误文案固定为两类之一："SQL 解析失败，请简化查询后重试" 或 "数据访问受限"）
- [x] 5.2 为 `sql_rewriter` 写 SQL 覆盖矩阵单元测试（对应 spec "SQL 改写覆盖矩阵" Requirement）：
  - 简单 `SELECT`、`SELECT *`（断言结果不含隐藏列）、`SELECT filtered FROM network_requests`（rewriter 不拒绝，交由 duckdb 执行期因列投影白名单而报 `BinderException`；这是正常 SQL 错误反馈，不泄漏过滤设施；断言 rewriter 输出的 SQL 中 `network_requests` 被替换为派生表）、带 `WHERE`、带别名、带子查询
  - CTE（`WITH`、`WITH RECURSIVE`）
  - **CTE 名称遮蔽**：`WITH network_requests AS (SELECT 1 AS x) SELECT * FROM network_requests` —— 断言不触发改写（CTE 是本地别名不是物理表）；`WITH decoy AS (SELECT * FROM network_requests) SELECT * FROM decoy` —— 断言 CTE 内部对物理表的引用**被**改写
  - **大小写变体**：`SELECT * FROM NETWORK_REQUESTS` / `SELECT * FROM Network_Requests` / `FROM "NETWORK_REQUESTS"` —— 都被识别并改写（DuckDB 标识符默认大小写不敏感）
  - `INNER / LEFT / RIGHT / FULL JOIN`：断言外连接语义不被破坏（`actions LEFT JOIN network_requests` 左表独有行仍保留）；**断言 `RIGHT/FULL JOIN network_requests` 时 `filtered=true` 的行不以 unmatched 行的形式出现在结果里**（派生表替换策略保证）
  - `UNION / UNION ALL` 多分支，每个分支各自被就地改写
  - schema-qualified：`main.network_requests`
  - 带引号标识符：`"network_requests"`、`"main"."network_requests"`
  - 直接/间接访问 `filter_decisions`（断言拒绝）
  - **名字出现在注释/字符串字面量**：`SELECT 'network_requests' AS name` / `SELECT 1 -- FROM network_requests` —— 断言**不**触发改写或拒绝
  - DDL / DML / 元数据 / catalog 语句（断言拒绝，逐类语句至少一例：`CREATE TEMP VIEW AS SELECT ... FROM network_requests`、`UPDATE network_requests SET filtered=false`、`SHOW TABLES`、`PRAGMA table_info('network_requests')`、`SELECT * FROM information_schema.tables`、`SELECT * FROM duckdb_tables()`、`SELECT * FROM duckdb_functions()`、`SELECT * FROM pragma_version()` —— **前缀匹配**覆盖 `duckdb_*` / `pragma_*` 整族，而非固定清单）
  - 非法 SQL（断言抛拒绝异常，不静默放行）
  - **参数化查询占位符保序**：输入 `SELECT * FROM network_requests WHERE method = ? AND response_status = ?`，断言改写后 SQL 中 `?` 出现次数不变、相对顺序不变；派生表 WHERE 子句用字面量 `filtered = false`，不新增占位符
- [x] 5.3 新建 `src/recording/filtering/filtered_conn.py`：实现 `FilteredDuckDBConnection` / `FilteredDuckDBCursor` / `FilteredDuckDBRelation` 三层代理，方法级 allow/deny 如下：
  - **连接层允许**（走 rewriter）：`.execute / .executemany / .sql / .from_query / .query`；rewriter 拒绝类异常由代理层包装成泛化错误再抛给 Agent 代码；duckdb 执行期异常同样包装成泛化错误（保持代理层行为一致性）
  - **连接层受限返回代理**：`.cursor()` → `FilteredDuckDBCursor`；`.table("network_requests")` → 底层等价 `SELECT <允许列> FROM network_requests WHERE filtered=false` 的 `FilteredDuckDBRelation`；`.table(其他)` → 代理 Relation
  - **连接层拒绝**：`.table("filter_decisions")` / `.view(*)` / `.create_view / .read_csv / .read_parquet / .from_df / .from_arrow / .register`
  - **Relation 层**：`.filter / .project / .select / .join / .aggregate / .order / .limit / .distinct / .union / .except_ / .intersect / .set_alias` 等返回新 Relation 的方法必须**重新包装返回值**为 `FilteredDuckDBRelation`；**`.query(alias, sql)` 一律拒绝**（决策 13）；`.create_view()` / `.df()` / `.pl()` / `.arrow()` / `.fetchdf()` / `.fetch_df()` / `.to_df()` 拒绝；`.fetchall()` / `.fetchone()` / `.fetchmany()` 透传物化
- [x] 5.4 为 `filtered_conn` 写单元测试：
  - `conn.execute("SELECT * FROM network_requests")` 被就地改写，**返回结果不含隐藏列**
  - `conn.execute("SELECT filtered FROM network_requests")` 抛代理层脱敏后的泛化异常；断言异常文本**不包含** `filtered` / `column` / `does not exist` / `BinderException` / `network_requests`
  - `conn.execute("SELECT * FROM filter_decisions")` 被拒绝
  - `conn.execute("SELECT 1")` 不受影响
  - `conn.executemany` / `conn.sql` 与 `.execute` 行为一致
  - `cur = conn.cursor(); cur.execute("SELECT * FROM network_requests")` 走同一链路
  - `rel = conn.table("network_requests"); rel.fetchall()` 的结果只含 `filtered=false` 行且不含隐藏列
  - `conn.table("network_requests").filter("method='GET'")` 返回值是 `FilteredDuckDBRelation` 代理（链式不脱代理）
  - `conn.from_query("SELECT * FROM network_requests").filter("...").fetchall()` 同样被过滤
  - `conn.view("network_requests")` 被拒绝；`rel.df()` / `rel.pl()` / `rel.arrow()` / `rel.fetchdf()` / `rel.fetch_df()` / `rel.to_df()` 被拒绝；`conn.register("foo", df)` 被拒绝；`conn.read_parquet(...)` / `conn.read_csv(...)` / `conn.from_df(...)` 被拒绝
  - `rel.query("nr", "SELECT * FROM nr WHERE method='GET'")` 被拒绝（决策 13，不尝试嵌入 alias rewrite）
  - DDL / DML / `SHOW` / `PRAGMA` / `information_schema` / `duckdb_tables()` 全部被拒绝

## 6. 业务工具层：装配过滤策略

- [x] 6.1 在 `src/business/agents/tools/recording_data_tools.py` 的 `query_data` 工具执行前调用 `filtering.sql_rewriter.rewrite()`；改写失败、拒绝语句类型、或访问 `filter_decisions` 时返回**泛化**错误（"SQL 解析失败，请简化查询后重试"），**不**向 Agent 透传 `str(exception)` / `TypeError: ...` / 底层 duckdb 报错；在日志中记录原始 SQL 与异常
- [x] 6.1a **删除 `_query_data` 中现有的正则护栏**：当前实现里 `_SELECT_RE.match(sql)`（非 SELECT 拒绝）、`if ";" in sql`（分号拒绝）、`if "--" in sql or "/*" in sql`（注释符号拒绝）、`re.search(r"\bSELECT\b.*\bINTO\b", ...)`（SELECT INTO 拒绝）这四组校验在本次变更中**必须全部删除**，由 `sql_rewriter` 的 AST 校验统一负责（语句类型白名单 + 多语句解析 + 字符串/注释识别由 sqlglot AST 天然正确处理）。保留正则护栏会让 spec 里"注释/字符串字面量中的名字不触发改写"等 scenario 变成不可达测试，并且错误文案与决策 12 的两类脱敏文案冲突。删除后写一个回归测试：提交 `SELECT 1 -- harmless comment` / `SELECT 'foo;bar' AS s` 能正常执行，不被提前拒绝
- [x] 6.2 **rewriter / 代理层拒绝类异常脱敏**（决策 12）：`recording_data_tools.py` 中 `query_data` 的 rewriter 拒绝类异常（`SqlRewriteError`）和代理层拒绝类异常（`DataAccessRestrictedError`）必须脱敏为泛化文案（"SQL 解析失败，请简化查询后重试" 或 "数据访问受限"）。**duckdb 执行期异常不需要额外脱敏**——rewriter 已在 AST 层拦截所有可能暴露过滤设施的路径（`filter_decisions` 引用、catalog / 系统表查询），列投影使隐藏字段在派生表中确实不存在，duckdb 报错是正常 SQL 反馈（如 `SELECT filtered` 报 "column does not exist"，与查任意不存在的列名无异）。**`execute_code` 要求**：`FilteredDuckDBConnection` / `FilteredDuckDBCursor` / `FilteredDuckDBRelation` 在代理层把 rewriter 拒绝类异常包装成泛化错误，避免 Agent 在 `try/except` 中看到 rewriter 内部细节；duckdb 执行期异常和 Agent 代码运行时异常正常透传。脱敏点：`query_data` 捕获 rewriter 异常后返回泛化文案、`_execute_code` 对 `_classify_error` 命中的异常返回泛化文案；异常分支中的可用表清单（`_ALL_TABLE_NAMES`）已剔除 `filter_decisions`
- [x] 6.3 修改 `_execute_code` 里构造 `exec_globals` 的代码，把 `exec_globals["conn"]` 从 `db.conn` 裸连接替换为 `filtering.filtered_conn.FilteredDuckDBConnection(db.conn)`
- [x] 6.4 确认 `_execute_code` 沙箱的**导入白名单**（`recording_data_tools.py` 中 `_ALLOWED_MODULES` = `{json, math, re, collections, itertools, functools, datetime, statistics, textwrap, string, operator, base64, hashlib, urllib}`），确保 `pandas` / `polars` / `pyarrow` 不在其中；**不扩大白名单**；为该限制写一个门卫单测（尝试 `import pandas` / `import polars` / `import pyarrow` 均抛 `ImportError`）；并写一个防回归测试：grep `_ALLOWED_MODULES` 的字面量不得包含 `pandas` / `polars` / `pyarrow`
- [x] 6.5 为 `_execute_code` 写集成测试：
  - Agent 尝试 `conn.execute("SELECT * FROM filter_decisions")` → 被拒绝
  - Agent 尝试 `conn.execute("SELECT * FROM network_requests")` → 只返回 `filtered=false` 的行
  - Agent 尝试 `try: conn.execute("SELECT filtered FROM network_requests") except Exception as e: print(e)` → 打印出的异常文本为泛化文案（因为 `FilteredDuckDBConnection` 把 duckdb 执行期异常包装为 `MaskedSqlParseError`），**不包含** `filtered` / `BinderException` / `network_requests`
  - Agent 尝试 `cur = conn.cursor(); cur.execute(...)` → 同样受限
  - Agent 尝试 `conn.table("network_requests").fetchall()` → 同样受限
  - Agent 尝试 `conn.view("network_requests")` / `conn.table("network_requests").df()` / `.fetchdf()` / `.fetch_df()` / `.to_df()` → 被拒绝
  - Agent 尝试 `conn.table("network_requests").query("nr", "SELECT * FROM nr")` → 被拒绝（Relation.query 首版不支持）
  - Agent 尝试 `conn.execute("SHOW TABLES")` / `conn.execute("CREATE TEMP VIEW v AS SELECT * FROM network_requests")` / `conn.execute("UPDATE network_requests SET filtered=false")` → 全部被拒绝
  - Agent 尝试 `import pandas` → `ImportError`
- [x] 6.6 修改 `_COMMON_TABLES` 的 `network_requests` 字段描述，移除 `filtered` / `filter_reason` / `filtered_at` / `is_recommendation` / `importance_level` 五项；并让 `describe_data` 中 `network_requests` 的 `row_count` 只统计 `filtered=false` 的可见行
- [x] 6.7 从 `_COMMON_TABLES` 中**完全移除** `filter_decisions` 条目
- [x] 6.8 清洗 `_ALL_TABLE_NAMES`（以及任何用于错误提示的"可用表"列表），剔除 `filter_decisions`；确保 `query_data` / `execute_code` 异常分支返回给 Agent 的文案里不出现 `filter_decisions` / `filtered` / `filter_reason`
- [x] 6.9 写集成测试：Agent 调用 `query_data` / `describe_data` / `execute_code` → 断言返回的数据、字段文档、错误提示都不包含噪声数据或过滤相关字段 / 表名；`network_requests.row_count` 只统计可见行；特别覆盖 `query_data("SELECT * FROM filter_decisions")` 被拒绝
- [x] 6.10 写开关关闭测试：`recording.noise_filter.enabled=false` 时入库侧不跑规则、所有请求写 `filtered=false` 且无决策；同时 `describe_data` / `query_data` / `execute_code` 仍保持隐藏字段 / 表、只读 SELECT、rewriter 拒绝类异常脱敏等查询侧契约；断言关闭时入库链路不会实例化 `NoiseFilterPipeline` / `LLMNoiseJudge`

## 7. 链路冒烟与门卫测试（遵循项目测试策略）

- [x] 7.1 链路冒烟测试：从 `recording_completed` 事件 → 入库 → Agent 查询，断言整条链路上噪声被正确过滤
- [x] 7.2 门卫测试：`src/recording/browser/duckdb_recording_persister.py` 和 `src/data/recording_recovery.py` 都必须 import 并调用共享过滤辅助函数（防止未来重构误删任一侧接线）
- [x] 7.3 门卫测试：`recording_data_tools.py` 中 `_COMMON_TABLES` 的 `network_requests` 字段描述绝不包含 `filtered` 字符串；`_COMMON_TABLES` 中绝不出现 `filter_decisions` 键（防未来回退导致字段 / 表泄漏给 Agent）
- [x] 7.4 门卫测试：`recording_data_tools.py` 中 `_execute_code` 注入的 conn 类型断言为 `FilteredDuckDBConnection`（而非 `db.conn` 原始类型），防止未来回退丢掉代理层
- [x] 7.5 门卫测试：`recording_data_tools.py` 的错误提示字符串（`_ALL_TABLE_NAMES` 或等价列表）在 grep `filter_decisions` 时必须为空
- [x] 7.6 门卫测试：`_execute_code` 的导入白名单 grep `pandas` / `polars` / `pyarrow` 必须为空；尝试在沙箱内 `import pandas` 抛 `ImportError`
- [x] 7.7 门卫测试：`src/business/agents/tools/` 目录下 grep `sqlglot` 应为空（确认业务工具层不重新实现 SQL 解析 / 改写，所有改写走 `src/recording/filtering/sql_rewriter.py` 公开函数）
- [x] 7.8 门卫测试：全项目 grep `import sqlglot` / `from sqlglot` 匹配的文件路径必须全部位于 `src/recording/filtering/` 下（含测试可在 `tests/recording/filtering/` 下）
- [x] 7.9 门卫测试：全项目 grep `import tldextract` / `from tldextract` 匹配的文件路径必须全部位于 `src/recording/filtering/` 下（含测试可在 `tests/recording/filtering/` 下）

## 8. 文档与清理

- [x] 8.1 若架构或约束变化，更新 `docs/ARCHITECTURE.md` 或 `docs/PROJECT_CONSTRAINTS.md`（参考 CLAUDE.md 活文档规则）
- [x] 8.2 在 `config.example.json` 旁边补一个关于 `noise_filter` 配置字段的简短说明（comments）
- [x] 8.3 ~~自测：对现有测试录制（baidu.com 那次）跑一遍新版入库逻辑~~ → **跳过，后续版本处理**。`bcebos.com`（百度云 CDN）是否应加入 first-party 白名单待确认，不影响过滤逻辑正确性

## 9. OpenSpec 归档

- [x] 9.1 全部验收后，运行 `openspec validate add-recording-data-noise-filter --strict` 确认无问题
- [ ] 9.2 运行 `/opsx:archive` 或 `openspec archive` 把本提案归档到 `openspec/changes/archive/`

## Context

### 现状观察

- `network_requests` 表 schema 中已存在 `filtered` / `filter_reason` / `filtered_at` / `is_recommendation` / `importance_level` 字段
- `filter_decisions` 表已建但从未被任何生产代码写入（当前 0 行）
- `DuckDBRecordingPersister.save_to_duckdb` 入库时硬编码写入 `filtered=False / filter_reason=None / filtered_at=None`
- `recording_data_tools.py` 已经把 `filtered` / `importance_level` / `is_recommendation` 字段描述进 `describe_data` 的 Agent 文档
- Agent 主要通过 `query_data` 工具以 SQL 访问 DuckDB；该工具已有 `_MAX_QUERY_CELL_CHARS = 12_000` 的单字段截断（与本提案正交）

### 真实数据的指导

对当前库中唯一一次录制（baidu.com，单域）的分析：

- 111 条 network_requests，其中 80 条 `response_body` 为空（静态资源 / img / favicon）
- 总 response_body 字节数 1.7MB，其中单条 1.2MB 的业务 HTML 占 72%
- 整批请求**没有**跨域第三方、没有加密响应、没有广告埋点
- 规则过滤在这批数据上主要命中点：静态资源（约 60 条） + 重复重定向

这次录制噪声极少并不能推翻"需要过滤"的判断，它只说明单域录制和跨域录制的噪声形态完全不同；跨域场景必须靠规则 + 域名黑名单兜底。

### 相关约束

- `CLAUDE.md` 约束 #3：数据库访问必须通过 Repository
- `CLAUDE.md` 约束 #4：所有配置通过 `get_unified_config()`，不直接读 `config.json`
- 架构分层：`UI → 业务层 → 接口层 → 驱动层 → 数据层`——过滤逻辑属于**驱动层的后置处理**（紧贴 `DuckDBRecordingPersister`），不能跨到业务层

## Goals / Non-Goals

**Goals:**

- 入库阶段对 `network_requests` 做规则驱动的噪声打标，不阻塞录制就绪
- 将决策过程可审计地持久化到 `filter_decisions` 表
- Agent 默认只看到业务相关数据，过滤对 Agent 透明无感
- 保留 LLM 判断和人工覆盖两个扩展源的接入点

**Non-Goals:**

- **不处理大字段交付**（response_body 超大 → Agent 看不全）——那是 P1 的工作，独立提案
- **不做 LLM 判断**——本提案只留空接口，不实现
- **不追溯历史数据**——已有录制的 `filtered` 保持 false，规则仅作用于新录制
- **不改动 `compression_model_*` 配置语义**——昨天 commit 让它 fallback 到主模型，本提案不触
- **不改动 UI**——噪声数据在 Agent 侧被过滤，UI 层如何展示由后续提案决定
- **不涉及 `compression_handler`（会话摘要）**——属于完全不同的处理层

## Decisions

### 决策 1：入库时同步规则判定，不走异步队列

**选择**：入库流程内串行规则判定 → 生成决策 → 写入 `filter_decisions` 和 `network_requests.filtered`，所有规则判定在 `save_to_duckdb` 返回前完成。

**替代方案**：异步队列 / 后台线程 / 下次查询时 lazy 判定。

**理由**：规则判定都是 O(字符串匹配) 的 CPU 操作，预估 1000 条请求 < 100ms；没必要引入异步复杂度。保证"录制结束 → DuckDB 数据立即可用"。

> 对比：LLM 判断（未来 P2.1）必须异步，因为单次调用几秒，这是不同性质的工作。

### 决策 2：`filter_decisions` 作为决策事件流，`network_requests.filtered` 作为聚合结果

**选择**：
- `filter_decisions`：每条命中一条记录，字段 `source="rule" | "llm" | "human"`、`decision="filter" | "keep"`、`reason`、`pattern_matched`、`confidence`（**枚举沿用 `duckdb_manager.py:377` 既有 schema 注释里的 `keep / filter` 语义**，不用新词 `noise`）
- `network_requests.filtered`：由决策聚合得出的最终结论
- `network_requests.filter_reason`：写**最终生效决策的精简 JSON 摘要**，形如 `{"decision":"filter","source":"rule","reason":"static_asset","pattern_matched":".png"}`；若请求未被过滤，则保持 `NULL`
- `network_requests.filtered_at`：仅在聚合结果为 `filtered=true` 时写入最终决策落库时间；若未被过滤，则保持 `NULL`
- `network_requests.filter_reason` 的**编码边界**放在 Repository：上层传 Python `dict | None`，Repository 按现有 `request_headers` / `response_headers` 的惯例统一 `json.dumps(..., ensure_ascii=False)` 后写入 DuckDB JSON 列，避免调用方各自编码导致不一致
- 聚合策略**首版只有一条**：**任一 `decision="filter"` 即 `filtered=true`，否则 `filtered=false`**；首版规则也只产出 `decision="filter"`，**不产出 `keep`，不实现覆盖逻辑**
- `decision="keep"` 仅为未来扩展预留（`source="human"` 人工覆盖等场景），本提案不实现相关聚合规则

**替代方案**：
- (a) 只写 `network_requests.filtered`，不建 `filter_decisions`——已被否决，因为 schema 已存在且多源扩展性好
- (b) 不聚合，每次查询 JOIN `filter_decisions` 判断——性能差，Agent 查询延迟敏感

**理由**：事件流 + 聚合列兼顾审计性和查询性能。首版单源简单实现；未来 LLM/人工介入只需加 source，不改表结构。

### 决策 3：五类规则的判定顺序与互斥性

规则按**先高确定性、后泛化兜底**的顺序评估，任一命中即给出决策：

```
1. OPTIONS 预检       (method=="OPTIONS")
2. 3xx 重定向         (300 <= response_status < 400)
3. 静态资源          (URL 扩展名或 Content-Type 白名单)
4. 广告/埋点黑名单    (URL host 匹配内建黑名单 regex)
5. 第三方请求        (归一化后的 registrable domain / eTLD+1 不属于主站 first-party 集合)
```

**顺序理由**：黑名单规则比“跨域三方”更具体；若某请求同时满足两者，首版应保留更可审计的 `ad_tracking_blacklist` reason，而不是被更泛化的 `third_party_cross_origin` 吞掉。

**first-party 判定**：
- 从录制中的首个 `http/https` action URL 派生 `primary_host`
- 将 `primary_host` 与请求 host 归一化为 registrable domain / eTLD+1；若两者归一化结果相同，则视为 first-party，即使 host 不同（如 `www.example.com` → `api.example.com`）
- 仅当请求 host 的归一化站点键不属于 `{primary_site} ∪ first_party_whitelist` 时，才命中 `third_party_cross_origin`
- 若无法识别 `primary_host`，或 host 无法归一化为站点键，则跨域规则保守跳过，只保留更确定性的前四类规则

**决策 3a：规则配置位置**

- 黑名单清单、静态资源扩展名、first-party 白名单 → 配置文件（新增 `recording.noise_filter.*` 段）
- 规则实现（判定函数）→ Python 代码里（每个规则一个函数）
- **不允许运行时修改规则代码**，但黑名单可配置

### 决策 4：Agent 透明的查询侧默认过滤

**分层**：过滤核心（`sql_rewriter` + `filtered_conn`）属于**驱动层**的策略组件，放 `src/recording/filtering/`；`src/business/agents/tools/recording_data_tools.py`（业务工具适配层）仅装配：把 `filtered_conn.FilteredDuckDBConnection` 包到 `exec_globals["conn"]`、把 `sql_rewriter.rewrite(sql)` 插到 `query_data` 执行前。**不允许**在业务工具里重新实现或绕过过滤策略。

**选择**：

A. **SQL 改写（`query_data`）**：对 AST 里每一处 `network_requests` 引用做**别名感知的派生表替换**：

  **统一策略：始终将 `network_requests` 表节点替换为已过滤并已做列投影的派生表**（下称"净表"）：
  ```sql
  (SELECT <允许列白名单> FROM network_requests WHERE filtered = false) AS <原有别名或随机别名>
  ```
  - 覆盖场景：`FROM network_requests`、`JOIN network_requests`（任意 INNER/LEFT/RIGHT/FULL）、子查询、CTE、UNION 各分支、schema-qualified（`main.network_requests`）、带引号标识符（`"network_requests"`）
  - **不使用"往 JOIN ON 追加条件"策略**：对 RIGHT/FULL JOIN 而言，若 `network_requests` 是保留侧，在 ON 上加 `AND nr.filtered=false` 只会让 `filtered=true` 的行变成 unmatched 行保留在外连接结果里，仍然违反"只能看到 filtered=false"的契约。改写成派生表是唯一确保语义正确的方式。
  - **列投影**：净表的 SELECT 列表显式枚举允许列（排除 `filtered / filter_reason / filtered_at / is_recommendation / importance_level`），防止 `SELECT *` 或 `SELECT filtered FROM network_requests` 泄漏隐藏字段
  - `filter_decisions` 引用直接抛拒绝异常（不到改写步骤）
  - **AST 语义要求**（详见决策 11）：CTE / 子查询别名遮蔽下的 `network_requests` 名字不得被改写；标识符大小写不敏感（`NETWORK_REQUESTS` / `Network_Requests` 均识别）；注释与字符串字面量中的 `network_requests` / `filter_decisions` 文本不触发改写或拒绝（由 sqlglot AST 天然保证）
  - **边界**：首版**不承诺解析数据库中既有 view definition** 来追踪其底层是否引用了 `network_requests`；因此代理层 `.view()` 接口一律拒绝，避免文档承诺超出可稳健实现的范围

B. **只读语句白名单（`query_data` 与 `execute_code` 共用）**：解析 AST 顶层语句类型，**仅允许** `SELECT`（含 `WITH ... SELECT`、`SELECT ... UNION [ALL] / EXCEPT [ALL] / INTERSECT [ALL] SELECT` 等 SELECT 级集合操作）。显式拒绝：
  - DDL：`CREATE TABLE / CREATE VIEW / CREATE TEMP VIEW / DROP / ALTER / ATTACH / DETACH`
  - DML：`INSERT / UPDATE / DELETE / MERGE / COPY`
  - 元数据：`SHOW / DESCRIBE / PRAGMA / EXPLAIN`
  - Catalog：任何对 `information_schema.*` schema 下对象的引用；以及任何**以 `duckdb_` 或 `pragma_` 为前缀**的表函数 / 系统表（如 `duckdb_tables()` / `duckdb_columns()` / `duckdb_views()` / `duckdb_schemas()` / `duckdb_databases()` / `duckdb_functions()` / `duckdb_keywords()` / `duckdb_settings()` / `duckdb_types()` / `pragma_version()` / `pragma_database_list()` 等）——采用前缀匹配而非固定清单，避免漏掉 DuckDB 新增的 catalog 函数
  - 理由：`execute_code` 若允许这些语句，Agent 可以通过 `SHOW TABLES` 看到 `filter_decisions`、`CREATE TEMP VIEW AS SELECT ... FROM network_requests` 物化未过滤数据再查、`UPDATE` 篡改 `filtered` 字段、`duckdb_functions()` 反查系统注册表等方式完全绕过透明过滤契约

C. **受限连接代理（`execute_code`）**：`exec_globals["conn"]` 不再是 `db.conn` 裸连接，而是 `FilteredDuckDBConnection`，**两层包裹**：

  **连接层方法分级**：
  | 方法 | 处置 |
  |------|------|
  | `.execute(sql)` / `.executemany(sql, ...)` / `.sql(sql)` | 走 `sql_rewriter.rewrite(sql)`，返回结果；rewrite 失败则拒绝；若底层 DuckDB 执行抛 `BinderException` / `CatalogException` / `ParserException` / `ConversionException` 等，**在代理层包装成泛化异常后再抛给调用方** |
  | `.cursor()` | 返回 `FilteredDuckDBCursor` 代理，`.execute()` 走同一链路 |
  | `.table("network_requests")` | 返回 `FilteredDuckDBRelation` 代理，底层等价于 `conn.sql("SELECT <允许列> FROM network_requests WHERE filtered=false")` |
  | `.table("filter_decisions")` / `.view(...)` | 拒绝 |
  | `.table(其他表)` | 透传，返回代理 Relation（防止 Relation 上链式调 `.query(sql)` 绕过） |
  | `.from_query(sql)` / `.query(sql)` | 等同 `.execute(sql)`，走 rewriter |
  | `.create_view()` / `.read_csv()` / `.read_parquet()` / `.from_df()` / `.from_arrow()` / `.register()` | 一律拒绝（这些 API 不传 SQL 字符串，无法改写，且可能物化未过滤数据） |

  **Relation 层方法分级**：所有返回新 `DuckDBPyRelation` 的方法（`.filter()` / `.project()` / `.select()` / `.join()` / `.aggregate()` / `.order()` / `.limit()` / `.distinct()` / `.union()` / `.except_()` / `.intersect()` / `.set_alias()` 等）必须把返回值也包成 `FilteredDuckDBRelation` 代理；**`.query(alias, sql)` 首版一律拒绝**（详见决策 13，不尝试嵌入别名 rewrite）；`.create_view()` / `.df()` / `.pl()` / `.arrow()` / `.fetchdf()` / `.fetch_df()` / `.to_df()` 一律拒绝；`.fetchall()` / `.fetchone()` / `.fetchmany()` 透传物化（安全：Relation 在构造时已经过滤，且不依赖额外 dataframe/arrow 可选库）。

- **不加参数**（Python 函数签名上也不加）——本次保持最简；未来内部调试需要时再加

D. **字段/表隐藏（`describe_data`）**：返回的字段文档里**移除** `filter_decisions` 整张表，并在 `network_requests` 字段描述中移除 `filtered` / `filter_reason` / `filtered_at` / `is_recommendation` / `importance_level` 五个字段；同时 `network_requests` 的 `row_count` 只统计 Agent 可见的 `filtered=false` 行，避免 Agent 通过概览计数反推出隐藏行数。

E. **错误文案脱敏**：`query_data` / `execute_code` 的异常分支（即当前 `recording_data_tools.py` 里 `query_data` 捕获 `Exception` 后拼接 `f"SQL 执行失败。可用表: {', '.join(_ALL_TABLE_NAMES)}。"` 的位置，以及 `_execute_code` 把 `str(e)` 回写给 Agent 的位置）同步剔除 `filter_decisions`，可用表清单中不得出现该表名。rewriter / 代理层拒绝类异常必须脱敏为泛化文案（详见决策 12）；duckdb 执行期异常和 Agent 代码运行时异常正常透传，帮助 Agent 定位问题。

F. **沙箱导入契约**：`execute_code` 的导入白名单**继续禁止** `pandas` / `polars` / `pyarrow`——否则 Agent 可通过 `pandas.read_sql(conn, "SELECT * FROM network_requests")` 绕开代理。考虑到这三个库当前也不在项目依赖里，首版 Relation 代理**不承诺** `.df()` / `.pl()` / `.arrow()`，而是统一拒绝；未来若要放开，必须同步扩展依赖与代理能力。

**替代方案**：建数据库视图 `network_requests_clean`、让 Agent 查视图——否决，因为 Agent 写的 SQL 可能直接 `FROM network_requests`，不能强制它改表名。

**风险**：SQL 改写必须稳健地处理：
- `FROM network_requests` 和 `JOIN network_requests`
- 子查询 / CTE 中的引用
- 带别名（`AS nr`）的引用
- 简单正则改写不可靠 → 用 `sqlglot`（决策 10 已明确引入为新依赖，否决了 EXPLAIN / sqlparse / 正则备选）

**改写失败的处理**：**直接拒绝查询并返回错误**（Agent 侧统一返回决策 12 定义的泛化文案"SQL 解析失败，请简化查询后重试"），不再静默放行原 SQL。
- 放行原 SQL 会直接违反"Agent 看不到噪声"的硬契约；而改写失败是罕见边界（语法错误 / 未覆盖的嵌套），让 Agent 重写 SQL 比让一条噪声穿透契约更可接受
- 日志中记录改写失败的 SQL 以便后续补测

### 决策 5：`response_body` 原样保留

**选择**：噪声打标不影响 `response_body` 字段值；即使被判 noise，body 也照常入库。

**理由**：
- 规则误判可恢复（只需清空 `filtered`）
- 本次数据看噪声几乎都是 body=0 的静态资源，保留成本极低
- DuckDB 列存压缩率高，存储风险可控
- 未来若需省存储，单独做 `prune_filtered_bodies` 运维命令

### 决策 6：LLM 判断的空接口形态

```python
# src/recording/filtering/llm_judge.py
class LLMNoiseJudge:
    def judge(self, request: NetworkRequestRow) -> Optional[FilterDecision]:
        """首版始终返回 None；P2.1 实现 LLM 调用。"""
        return None
```

规则流水线中预留调用点，但如果 `judge` 返 `None` 则不产生 `filter_decisions` 记录。

### 决策 7：`is_recommendation` / `importance_level` 字段处理

- Schema 保留（不动列），但**对齐 CREATE TABLE 与迁移两条路径的默认值**
- `is_recommendation`：CREATE TABLE（`duckdb_manager.py` `network_requests` 建表语句）与迁移（`_migrate_network_requests_table`）均已是 `DEFAULT FALSE`，无需改动
- `importance_level`：**存在默认值漂移**——CREATE TABLE 里是裸 `importance_level TEXT`（新装机落 `NULL`），`_migrate_network_requests_table` 的 `ALTER TABLE ... ADD COLUMN importance_level VARCHAR DEFAULT 'unknown'` 才有 `'unknown'` 默认值。**本提案顺手把 CREATE TABLE 改成 `importance_level VARCHAR DEFAULT 'unknown'`**，让新装机与迁移库行为一致，否则 task 4.8 的"取 schema 默认值"断言会在新装机上炸
- 首版**不**被规则写入（这两个字段语义是"重要程度分级"，属于 LLM 判断范畴，规则给不了有效信号）——入库代码不显式赋值，让 DuckDB 按对齐后的默认值填充
- `describe_data` 不暴露给 Agent

### 决策 8：恢复路径同样接入过滤（含事务语义）

**背景**：`src/data/recording_recovery.py` 的崩溃恢复入库路径（当前存在两处 `repository.save_network_requests` 调用：action-attached requests 与 standalone requests）直接绕过 `DuckDBRecordingPersister`。若只在 persister 接线，恢复场景会成为过滤旁路。

**选择**：
- 把"构造 `NoiseFilterPipeline` → 跑规则 → 聚合决策"抽到一个共享辅助函数（如 `src/recording/filtering/ingest_hook.py`），`duckdb_recording_persister.py` 和 `recording_recovery.py` 都调用它
- `recording_recovery` **不**沿用当前“逐 action 调 `save_network_requests`”的提交结构；改为**每个 recovered recording/session 构造一个 recording-scoped `IngestBatch`**，扁平化收集该录制的所有 action-attached requests + standalone requests，在一个外层事务里完成 `save_actions` → `save_network_requests` → `save_filter_decisions`
- recovery 构造 `IngestBatch.actions` 时，直接复用**队列解析阶段保留在内存中的原始/标准化 action dict 列表**，不得通过回查 `actions` 表重建；这样才能与 persister 路径共享同一套 `primary_host` 推断输入

**接口设计**：hook 接受一个标准化的 `IngestBatch` 数据类作为输入，屏蔽两个调用方的上下文差异：
```python
@dataclass
class IngestBatch:
    recording_id: str
    actions: List[dict]           # 用于推断主域，可为空列表
    network_requests: List[dict]  # 每条带 url/method/response_status/request_headers/response_headers 等
    # batch_index 由 hook 内部按列表序号自动分配
```
hook 返回 `List[FilteredRequestResult]`，每条携带原始 dict + 规则决策 + 稳定的 `batch_index`（与入参列表序号对应）。

**恢复路径的扁平化约定**：
- `FilteredRequestResult` 额外保留来源 `action_list_index: int | None`（standalone request 为 `None`）
- `save_actions` 返回 `action_ids` 后，先构造 `action_id_by_list_index`
- 再基于 `action_list_index` 为每条 request 解析出最终 `action_id`，形成一份**整条 recording 级别**的 request rows 列表
- `save_network_requests` 对这份列表**调用一次**，返回 recording-scoped 的 `{batch_index: request_id}` 映射；随后 `save_filter_decisions` 也**调用一次**

**request_id 映射**：`request_id` 在 `save_network_requests` 入库后才生成，因此流程顺序必须是：
1. `ingest_hook` 打标，返回带 `batch_index` 的结果列表
2. `save_network_requests` 入库并返回 `{batch_index: request_id}` 映射
3. 用映射组装 `FilterDecision` 行（填入 `request_id / action_id / recording_id`）；其中 `filter_decisions.request_id` 由于 schema 为 `TEXT`，写入时显式使用 `str(request_id)`
4. `save_filter_decisions` 写入决策
5. 步骤 2–4 在同一事务内

- **两条路径共享相同的事务边界**：`save_network_requests` 与 `save_filter_decisions` 必须在**同一个 DuckDB 事务内提交**；任一失败必须一起回滚，不允许出现 "请求已入库但决策未入库" 或反之的中间状态
- **事务边界归属**：`BEGIN / COMMIT / ROLLBACK` 由**外层调用方**（`duckdb_recording_persister.save_to_duckdb` 或 `recording_recovery` 的恢复入库点）负责；`save_network_requests` / `save_filter_decisions` 两个 Repository 方法**内部不得自行 `COMMIT`**，只发 INSERT，让外层控制提交点。这是让两步 INSERT 能绑在同一事务的前提
- 恢复路径如果需要分片提交（例如一次恢复多个 session），每个 session 的"actions + network_requests + filter_decisions"为一个事务边界单元；**同一 session 内不得按 action 分事务提交**

### 决策 9：性能估算

- 估算：1000 条请求的规则判定约 50–100ms（字符串匹配 + sqlglot AST 解析）
- **本提案不把具体数字写进硬验收**——性能基础设施与数据集规模需单独评估；spec 里以"预期量级"表述，不设 MUST 数字阈值
- 未来若发现回归，再补专项性能基准（独立 change）

### 决策 10：引入 `sqlglot` 作为新依赖

**选择**：在 `pyproject.toml` 的 `dependencies` 中新增 `sqlglot>=23.0.0,<30.0.0`（上限用于规避未来大版本 API 破坏，如过去版本间 `Select.from_` / `Table` AST 节点命名的调整），并**禁止**在 `src/business/agents/tools/` 直接 `import sqlglot`——改写逻辑集中在 `src/recording/filtering/sql_rewriter.py`，业务工具层只调用其公开函数。

**替代方案**：

- (a) 基于正则/字符串匹配的轻量改写——已否决，无法稳健处理 CTE 遮蔽、带引号标识符、schema-qualified、子查询、UNION 各分支、注释内假引用等场景
- (b) 基于 DuckDB `EXPLAIN` 的 schema 推断——已否决，语义上只能得到"执行计划中用到的表"，得不到 AST 层级的"哪一处 token 是 `network_requests` 引用"，无法做原地替换
- (c) 使用 `sqlparse`——已否决，其输出仍是 token 流，不产生完整 AST，改写相当于手写 AST 构建

**理由**：

- `sqlglot` 是成熟的多方言 SQL AST 库（支持 DuckDB dialect），完整的 `parse → walk → replace` 能力是唯一能在可接受风险内实现"覆盖矩阵"的方案
- 引入成本：纯 Python，无 C 扩展；对打包与启动时间影响可忽略

**与现有正则护栏的衔接**：`recording_data_tools.py` 当前 `_query_data` 在调用 DB 前用正则硬拒绝 `;` / `--` / `/*` / `SELECT INTO` / 非 SELECT 开头——这些检查在引入 sqlglot AST 校验后**必须全部删除**，由 `sql_rewriter` 的语句类型白名单（决策 4B）+ AST 遍历统一负责。否则：
- 正则会把带 `--` 注释或字符串字面量里含 `network_requests` 的合法 SQL 提前拒掉，使得 spec 里"注释/字符串字面量中的名字不触发改写"的 scenario 变成不可达测试
- 两层护栏并存时出错文案会分化（一边是现有中文正则文案，一边是决策 12 的两类脱敏文案），错误脱敏契约被打破
- 多语句防御由 sqlglot 解析得到的顶层语句数量来守（`parse_one` 只产生单语句 AST，多语句应抛拒绝）

### 决策 11：SQL 改写的 AST 语义约束

`sql_rewriter` 必须满足以下 AST 语义（不仅是"命中 `network_requests` 字符串"）：

- **CTE / 子查询别名遮蔽**：`WITH network_requests AS (SELECT 1) SELECT * FROM network_requests` 中的 `network_requests` 是 CTE 名，不得被改写；仅当 AST 识别为"表引用（Table）"且表名解析到真实物理表 `network_requests` 时才触发替换
- **大小写不敏感**：DuckDB 默认标识符大小写不敏感，rewriter 必须同时识别 `network_requests` / `NETWORK_REQUESTS` / `Network_Requests`；带引号标识符（`"network_requests"`、`"NETWORK_REQUESTS"`）按 DuckDB 规则处理——双引号内仍不敏感（DuckDB 默认），除非未来启用大小写敏感标识符，则保守策略是"引号内按字面匹配"，现阶段两种情况都识别
- **`filter_decisions` 名称遮蔽**：同上，仅当 AST 识别为真实表引用时才拒绝；用户把 `filter_decisions` 作为 CTE 名（不真实存在）的场景不被拒绝
- **注释与字符串字面量**：`-- FROM network_requests` 或 `'... network_requests ...'` 这类位于注释或字符串里的名字不得被误改写（由 sqlglot AST 自然保证）

### 决策 12：错误脱敏范围

**背景**：rewriter 在 AST 层已拦截所有可能暴露过滤设施的路径（`filter_decisions` 引用、catalog / 系统表查询、非只读语句），且列投影使隐藏字段（`filtered` / `filter_reason` 等）在派生表中不存在。因此 duckdb 执行期异常不会泄漏过滤设施——例如 `SELECT filtered FROM network_requests` 在改写后，`filtered` 对 duckdb 来说确实是个不存在的列名，报 "column does not exist" 是正常反馈，不会暴露"底层表有这个字段"的事实。

**选择**：脱敏分为两层：

1. **必须脱敏的异常**（由 rewriter / 代理层拦截）：
   - `sql_rewriter` 抛出的拒绝异常（语句类型不允许、涉及 `filter_decisions`、catalog / 系统表引用等）
   - `sql_rewriter` 内部解析异常（sqlglot ParseError / 未覆盖模式）
   - `FilteredDuckDBConnection` / `FilteredDuckDBRelation` 的方法拒绝异常（`.register()` / `.view()` / `.df()` 等代理拒绝）
   - 统一返回给 Agent 的文案：`"SQL 解析失败，请简化查询后重试"` 或 `"数据访问受限"`

2. **不需要脱敏的异常**（可正常透传给 Agent）：
   - duckdb 执行期异常（`BinderException` / `CatalogException` / `ParserException` / `ConversionException` 等）——这些是常规 SQL 错误反馈（列不存在、类型不匹配等），不含过滤设施信息，对 Agent 修正 SQL 有帮助
   - Agent 自身 Python 代码的运行时异常（`NameError` / `SyntaxError` / `TypeError` 等）

**分层约束**：
- `query_data`：rewriter 异常由业务工具边界捕获并脱敏；duckdb 执行期异常正常返回错误信息（含可用表清单，清单中不含 `filter_decisions`）
- `execute_code`：**`FilteredDuckDBConnection` / `FilteredDuckDBRelation` 在代理层把 rewriter 拒绝类异常包装成泛化异常**，避免 Agent 代码 `try/except` 时看到 rewriter 内部细节；duckdb 执行期异常和 Agent 代码运行时异常正常透传

**不得**在错误文案的可用表清单里出现 `filter_decisions`。日志侧记录原始异常栈以便排查。

### 决策 13：Relation API 边界收紧

- `FilteredDuckDBRelation.query(alias, sql)` 首版**直接拒绝**，不尝试做"嵌入 alias 引用当前 relation"的 rewrite 处理
  - 理由：`Relation.query` 的 sql 里用户指定别名引用当前 relation（类似 `this AS nr`），rewriter 不持有该上下文，容易在改写时把对 relation 别名的引用误判为物理表引用；首版复杂度/收益不成比例
  - Agent 若需要对 relation 再做过滤，应链式 `.filter() / .project()` 而非 `.query()`
- `FilteredDuckDBRelation.fetchdf() / fetch_df() / to_df()` 等别名方法与 `.df()` 同等拒绝（sqlglot 不控这层，由代理显式枚举）

### 决策 14：recovery 事务回滚后的幂等性

**背景**：事务回滚后上层可能重试同一 `recording_id` 的 recovery 入库。需要保证重试不产生"部分写入残留"或"重复 `filter_decisions`"。

**选择**：

- `save_network_requests` / `save_filter_decisions` 在事务内用 `recording_id` 作为写入边界单元；回滚后该 `recording_id` 对应的两张表行数必须回到事务开始前的状态（DuckDB 事务语义天然保证）
- recovery 重试前，上层必须确认"该 recording_id 已不存在于 `network_requests` 或存在但属于已提交的历史数据"——重试不是"同一事务的继续"，是"全新事务"，因此靠 DuckDB 的 ACID 保证即可
- 首版 recovery **不做幂等去重**（即同一 recording_id 重入库会新增而非 upsert），这是 recovery 模块的既有行为边界；本提案不扩展该边界，只保证过滤数据不写半套

### 决策 15：enabled=false 时的初始化边界

`recording.noise_filter.enabled=false` 只控制**入库侧规则判定与决策写入**，**不**控制 Agent 侧数据防护。模块仍然会被 Python import（不可避免），但必须满足以下约束：
- 入库链路不得实例化 `NoiseFilterPipeline` / `LLMNoiseJudge`，不得执行规则匹配
- `ingest_hook` 遇到 enabled=false 时必须在**入口处短路返回**（所有请求标记 `filtered=False`、`filter_reason=NULL`、`filtered_at=NULL`）
- `filter_decisions` 表不得新增任何记录
- `sql_rewriter` / `FilteredDuckDBConnection` 仍可在 Agent 查询链路中按需实例化，因为它们承载的是“只暴露允许表/列、只允许只读 SELECT”的长期契约，而不是入库判定逻辑
- 理由：回滚规则判定不能退化成“把过滤设施和写保护暴露给 Agent”；关闭后 Agent 可见行集合会因全部 `filtered=false` 而回到当前全量数据视图，但看不到内部设施本身

### 决策 16：eTLD+1 归一化依赖 `tldextract`

**背景**：决策 3 的"第三方请求"规则和 first-party 判定都要求把 host 归一化为 registrable domain / eTLD+1。简单取"最后两段"在 ccTLD 场景下会错判——例如 `www.example.co.uk` 若归一化为 `co.uk`，会把同站的 `api.example.co.uk` 也误判为三方。准确判定必须依赖 Public Suffix List（PSL）。

**选择**：在 `pyproject.toml` `dependencies` 中新增 `tldextract>=5.0.0,<6.0.0`，`src/recording/filtering/primary_host.py` 通过 `tldextract` 计算 registrable domain。

**替代方案**：

- (a) 手写"最后两段"近似——已否决，ccTLD 场景错判率不可接受
- (b) 内建 ccTLD 硬编码清单——已否决，维护成本高且覆盖不全
- (c) 使用 `publicsuffix2`——可行但维护活跃度不如 `tldextract`；`tldextract` 额外提供 `subdomain / domain / suffix` 三段分解，更适合本场景
- (d) 离线打包 PSL 数据——`tldextract` 默认会在首次使用时在线下载 PSL 缓存到用户目录；为避免离线环境首次失败，必须用 `TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)` 构造器，**强制使用库内置快照**，不做网络请求。接受的风险：PSL 快照跟随 `tldextract` 版本更新，足够新即可

**约束**：

- `import tldextract` 只允许出现在 `src/recording/filtering/` 下；门卫测试同 `sqlglot`
- `primary_host.py` 必须在模块加载期构造一次 `TLDExtract(suffix_list_urls=(), fallback_to_snapshot=True)` 实例并复用，避免每次调用都读 PSL
- 输入 host 为 IP 地址、单段 hostname（如 `localhost`）或解析结果 `suffix` 为空时，视为无法归一化：`primary_host` 返回 `None`，跨域规则保守跳过（与决策 3 "无法识别 primary_host 时跨域规则不生效"一致）

## Risks / Trade-offs

- **风险**：规则误杀业务 API
  - 例：业务使用 CDN（`bcebos.com`）被当成三方；OAuth 跳转被 3xx 规则误判
  - **缓解**：`filter_decisions` 保留完整理由，可人工回看；`response_body` 原样保留便于复核；跨域规则依赖主域识别，主域识别不到时降级为"仅黑名单"模式

- **风险**：广告/埋点黑名单维护
  - **缓解**：黑名单放配置文件可热更；首版内建清单统一为 `doubleclick` / `googletagmanager` / `google-analytics` / `sentry` / `hotjar` / `baidu-tongji`，用户可增补

- **风险**：SQL 自动改写可能破坏复杂查询
  - **缓解**：优先用 `sqlglot` 做 AST 改写而非正则；为 Agent 常用 SQL 模式准备单测
  - **改写失败**：直接拒绝查询并在日志记录告警（不再放行原 SQL）——放行会让 Agent 看到噪声，直接违背透明过滤契约；拒绝会让 Agent 重写 SQL，代价可接受

- **风险**：`execute_code` 注入的 `conn` 成为过滤旁路
  - Agent 可能直接 `conn.execute("SELECT * FROM network_requests")`，完全绕开 `query_data` 的 SQL 改写
  - **缓解**：包装 `conn` 为受限代理，所有 `.execute()` / `.sql()` 走同一条改写链路；为 `execute_code` 写集成测试断言绕过尝试被拦截

- **风险**：`filter_decisions` 表随录制增长膨胀
  - 粗估：单次录制 100-1000 条命中 → 100-1000 行决策；年累计百万级不是问题
  - **缓解**：本提案不引入定期清理；若未来成为问题再做归档

- **Trade-off**：入库同步判定让"录制完到就绪"多了 50-100ms
  - 相对于 DuckDB 写入本身的几百 ms，可忽略
  - 但确立了"入库只做规则、不做 LLM"的边界

## Migration Plan

1. **落地顺序**：先建 Repository 写入方法和规则模块（无业务影响） → 接入 `DuckDBRecordingPersister`（新录制开始打标） → 修改 `recording_data_tools`（Agent 查询侧生效）
2. **回滚**：任一阶段出问题可通过关闭配置 `recording.noise_filter.enabled=false` 退化到"全部 filtered=false + 不写决策"；Agent 可见数据行集合等同现状，但查询侧隐藏 / 只读防护继续保留
3. **历史数据**：不追溯。已有录制保持 `filtered=false`（即"全部可见"），Agent 可见**行集合**与之前一致；但 `describe_data` 持续隐藏过滤字段 / `filter_decisions`，这是长期查询侧契约，不随 `enabled=false` 回退

## Open Questions

（无。`sqlglot` / `tldextract` 依赖问题已在决策 10 / 决策 16 明确：新增 `sqlglot>=23.0.0,<30.0.0` 与 `tldextract>=5.0.0,<6.0.0` 到 `pyproject.toml`。）

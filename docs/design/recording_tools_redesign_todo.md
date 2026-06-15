# 录制数据查询工具重新设计

## 状态：已完成

本文件记录录制数据查询工具的重新设计思路。目标是替换当前 PM 和程序员各自独立的 `query_recording_data` 工具，设计一套通用的、不限定角色的数据访问工具。

---

## 一、为什么要重新设计

### 当前方案的问题

当前设计（pm_agent_design.md + programmer_agent_design.md）为 PM 和程序员分别设计了 `query_recording_data` 工具，通过 `query_type` 枚举（PM 4 种、程序员 7 种）限定查询方式。

问题：

1. **太死**。7 个 query_type 本质上是我们替 agent 决定了"你只能这样看数据"。agent 是 ReACT 模式，应该自己决定看什么。
2. **角色耦合**。PM 版本不包含 network_requests，程序员版本多了 3 个查询类型。这不是真正的权限问题——PM 不看网络请求是因为看了对需求分析没帮助，不是因为涉密。这种引导应该由 prompt 负责，不是工具限制。
3. **扩展性差**。以后加桌面录制，新增 `ui_elements`、`accessibility_tree` 等表，每加一种数据就要给 PM 和程序员各加 query_type，两边都要改。
4. **重复实现**。PM 和程序员共享的查询（action_summary、element_context、screenshot）需要跨文件复用，维护成本高。

### 目标状态

- **一套工具，所有 Agent 共用**。PM、程序员、试用 Agent 用完全相同的工具实例。
- **角色差异由 prompt 处理**。PM 的 prompt 引导它关注操作流程和用户意图；程序员的 prompt 引导它关注技术线索。工具层不做角色区分。
- **agent 自主决定看什么**。工具提供"发现"和"获取"两个能力，agent 根据自己的判断使用。
- **新数据类型低成本接入**。加桌面录制的新表后，只需在 describe_data 的硬编码描述中添加新表信息，工具定义和 agent prompt 无需修改。

---

## 二、全局设计思路

### 核心原则

这些原则贯穿整个工具设计，做决策时如果拿不准，回到这里对照：

1. **工具负责"数据是什么"，prompt 负责"怎么思考"**。工具（尤其是 describe）应该告诉 agent 每类数据是什么含义、有什么特征、哪些字段需要注意（如大字段警告）。agent 拿到这些信息后，根据自身角色的 prompt 决定怎么用这些数据。数据说明跟着数据走（在工具返回值里），不写死在 prompt 里——这样新增数据类型时 prompt 不用改。

2. **上下文精准控制是最高优先级约束**。（架构 v2 第八节原文："上下文精准控制是整个 Agent 架构最关键的设计原则"）。通过三层机制保护上下文：describe_data 的大字段警告（事前引导）、agent prompt 和 FC schema 的按需查询提示（行为约束）、ContextManager 引用替换（事后兜底）。工具层不做截断——不替 agent 做决策，但确保 agent 有足够的信息做出正确决策。

3. **录制数据 = 用户做了什么（技术线索），不等于用户想做什么（目标）**。目标由 PM Agent 通过需求确认确定，录制数据只提供实现线索。工具设计不应该预设"数据会被怎么用"。

4. **不替 agent 做决策**。不通过 query_type 枚举限定 agent 的查询方式，不通过权限系统限制 agent 能看什么。agent 是 ReACT 模式，自己判断需要什么信息。

5. **简单优于灵活**。工具的参数设计要让 LLM 容易正确使用。宁可功能少一点，也不要搞出 LLM 经常调错的复杂接口。

### 工具设计的演进

最初设想是两个工具（describe + query），讨论过程中逐步抽象：

1. **截图查看和多模态分析本质是一件事**——都是调多模态模型"看"图片，需要单独的工具（已确定）
2. **跨表关联和全文搜索本质也是一件事**——一条 SQL 就能搞定，query 工具用 SQL 表达力最强
3. **进一步抽象：SQL 查询能做的事，写段代码也能做，还更灵活**——于是出现了"临时代码执行工具"的想法

### 已确定的工具集（5 个）

```
1. describe_data   — 数据发现（渐进式：无参返回表概览，传表名返回字段详情）
2. query_data      — SQL 查询数据
3. execute_code    — 临时代码执行（SQL 不够用时的补充）
4. read_recording  — 读取录制元数据
5. read_field_chunk — 分段读取大字段原始内容
```

注：`analyze_image` 仅在浏览器录制路径下注入，桌面录制路径不注入该工具。

#### 工具定位

| 工具 | 定位 | 使用频率 | 典型场景 |
|------|------|---------|---------|
| describe_data | 数据发现入口（渐进式） | 任务开始调 1~2 次 | 先看有哪些表，再看感兴趣的表有哪些字段 |
| query_data | 主力数据获取 | 高频（~90% 的数据查询） | "第 3 个操作的 DOM 信息"、"有没有返回 JSON 的 XHR" |
| execute_code | SQL 的补充 | 低频（~10%，SQL 搞不定时） | 需要循环遍历、复杂数据处理、跨表聚合计算 |
| analyze_image | 截图理解 | 按需 | "这个页面上有什么元素"、"截图里表格的数据" |

#### 设计决策记录

**Q: PM 用什么工具？**
A: 所有 agent（PM、程序员、未来的其他 agent）使用完全相同的 4 个工具。角色差异由 prompt 引导，不在工具层区分。PM 也可以写 SQL，毕竟 PM 是 LLM 扮演的，写 SQL 不是问题。

**Q: 为什么不用代码执行替代 SQL？**
A: SQL 对 LLM 来说更容易生成正确的查询，出错率低，且 DuckDB 的 SQL 执行效率高于 Python。90% 的数据查询用 SQL 就够了。execute_code 只是 SQL 不够用时的补充（如需要循环处理、复杂计算）。

**Q: describe 是否多余（agent 可以自己查 schema）？**
A: 不多余。describe 不只返回 schema，还返回**带含义的描述**——字段代表什么、哪些字段要小心（大字段警告）、数据量级等。这些元信息不在数据库 schema 里，需要工具层注入。

**Q: execute_code 与 submit_code 的关系？**
A: 本质不同。execute_code 是**临时代码**，跑完拿结果，用于探索数据，代码是手段。submit_code 是**交付代码**，提交给系统入库，代码本身是目的。需要在 schema description 中明确传达区别。

---

## 三、工具详细设计

### 上下文注入

4 个工具都不需要 agent 传 `recording_id`。工具 handler 在注册时通过闭包或上下文注入获取当前 recording_id，对 agent 透明。agent 只需要关心"我想查什么"，不需要关心"数据在哪"。

```python
# 示意：工具注册时绑定 recording_id
def create_tools(recording_id: str) -> list[ToolDefinition]:
    def describe_handler(tables: list[str] | None = None):
        return _describe_data(recording_id, tables)

    def query_handler(sql: str):
        return _query_data(recording_id, sql)

    # ... 其他工具类似
```

### 工具 1: describe_data

**职责**：数据发现入口。告诉 agent 有什么数据可查，渐进式返回——先概览再详情。

**已确定的设计方向**：

- **渐进式返回**（两级）：
  - **不传 tables 参数**：返回所有表名 + 每个表的含义描述 + 数据量。轻量，agent 一眼看清全貌。
  - **传 tables 参数**（一个或多个表名）：返回指定表的字段详情（名称 + 类型 + 描述 + 注意事项）。
- **带含义的描述**，不是冷冰冰的 schema。agent 需要知道：
  - **这个数据是什么**（表/字段的含义）
  - **哪些字段需要小心**（大字段警告、二进制标记等）
- **描述跟着录制模式走**。browser 返回 browser 的说明，desktop 返回 desktop 的说明。新增录制类型时只改 describe 实现，prompt 不用改。
- **工具名用 data 而非 recording**。更抽象，以后数据源不限于录制数据时不用改名。
- **无需传 recording_id**。工具 handler 通过执行上下文（闭包/注入）获取，agent 不需要关心。

**输入**：
- `tables`（可选）— 要查看详情的表名列表。不传则返回概览。

**输出**：

不传 tables 时（概览）：
```json
{
  "tables": [
    {"name": "recording_sessions", "description": "录制会话元数据（录制模式、起止时间等）", "row_count": 1},
    {"name": "actions", "description": "用户操作记录（点击、输入、导航等）", "row_count": 12},
    {"name": "network_requests", "description": "浏览器网络请求记录", "row_count": 87},
    {"name": "sibling_snapshots", "description": "操作目标元素的兄弟元素快照，用于识别列表类操作", "row_count": 5},
    {"name": "filter_decisions", "description": "网络请求过滤决策记录（系统自动标记哪些请求被过滤及原因）", "row_count": 42}
  ]
}
```

传 tables 时（字段详情）：
```json
{
  "table_details": {
    "actions": {
      "description": "用户操作记录（点击、输入、导航等）",
      "row_count": 12,
      "fields": [
        {"name": "action_id", "type": "INTEGER", "description": "操作 ID（主键）"},
        {"name": "recording_id", "type": "VARCHAR", "description": "所属录制会话 ID"},
        {"name": "sequence_number", "type": "INTEGER", "description": "操作序号，从 1 开始"},
        {"name": "action_type", "type": "VARCHAR", "description": "操作类型：click, fill, navigate, scroll, ..."},
        {"name": "recording_mode", "type": "VARCHAR", "description": "录制模式：browser / desktop"},
        {"name": "url", "type": "VARCHAR", "description": "操作发生时的页面 URL（browser 模式）"},
        {"name": "app_name", "type": "VARCHAR", "description": "应用名称（desktop 模式）"},
        {"name": "window_title", "type": "TEXT", "description": "窗口标题（desktop 模式）"},
        {"name": "parameters", "type": "JSON", "description": "操作参数（输入值、按键、坐标等）"},
        {"name": "dom_element", "type": "JSON", "description": "操作目标元素信息（tag, id, class, text 等）"},
        {"name": "dom_tree_snapshot", "type": "JSON", "description": "操作时的 DOM 树快照", "warning": "⚠️ 大字段，可能几十~几百 KB，建议按需查询"},
        {"name": "screenshot_before", "type": "BLOB", "description": "操作前截图", "warning": "⚠️ 二进制数据，SQL 无法直接查看，请使用 analyze_image 工具"},
        {"name": "screenshot_after", "type": "BLOB", "description": "操作后截图", "warning": "⚠️ 二进制数据，请使用 analyze_image 工具"},
        {"name": "timestamp", "type": "DATETIME", "description": "操作发生时间"}
      ]
    }
  }
}
```
（以上为示意，精确结构待实现时确定）

**已决策**：
- [x] 字段描述的详细程度——**每个字段都描述**。字段总量不多（几十个），全描述也就几百 token，漏掉反而导致 agent 多一轮交互试探。
- [x] 描述信息的维护方式——**硬编码在 handler 中**（dict 常量）。表和字段不多，变化频率低，做可配置 metadata 是过度设计。以后需要再抽离。
- [x] 是否在概览中列出 DuckDB 视图——**暂不提供**。agent 直接写 SQL 已够用，等实际跑起来发现频繁写某类复杂 SQL 时再加视图。
- [x] 传了不存在的表名——**返回错误信息 + 可用表名列表**，帮 agent 自我修正。

### 工具 2: query_data

**职责**：agent 写 SQL 查询录制数据，主力数据获取工具。

**已确定的设计方向**：

- **agent 直接写 SQL**。SQL 表达力强，LLM 写 SQL 的能力成熟，DuckDB SQL 语法对 LLM 友好。
- **不用子 agent 翻译**。agent 从 describe 拿到表结构后，自己写 SQL，直接执行，拿结果。简单直接。

**输入**：
- `sql` — SQL 查询语句

**输出**：查询结果（JSON 格式）

**已决策**：
- [x] SQL 安全策略——**只允许 SELECT，正则检查** `^\s*SELECT\b`（忽略大小写）。agent 是我们控制的 LLM，正则防御够用，不需要 SQL AST 解析。已知限制：挡不住 DuckDB 的 `read_csv_auto()` 等文件读取函数，但 agent 是受控 LLM，风险可接受。
- [x] 返回格式——**行数组** `[{col1: val1, col2: val2}, ...]`。LLM 更容易理解，行格式比列式更直观。
- [x] 大字段保护——**结构化占位替换**。达到阈值的文本字段以 `__large_field__` 占位对象交付（含预览和定位信息），Agent 可通过 `read_field_chunk` 分段续读原文。取代原 12KB 无差别截断。二进制字段（screenshot）仍替换为 `[截图（二进制）]`。
- [x] 行数/大小上限——**工具层不限制**，agent 自己写 LIMIT。但需在两处提醒上下文意识：
  - **agent prompt**：提醒 agent 查询大字段或大量数据时注意控制返回量，避免撑满上下文窗口。
  - **query_data 的 FC schema description**：提示"非必要不要 SELECT *，按需查询字段；数据量大时使用 LIMIT 分页"。
- [x] 错误处理——返回 `{"error": "错误信息", "hint": "可用表: actions, network_requests, ..."}`。给 agent 足够信息自我修正，不附完整表结构（agent 可以自己调 describe_data）。

- [x] recording_id 数据隔离——**不做工具层隔离**。recording_id 在 agent 启动时写入 prompt（模板替换），agent 写 SQL 时自己加 `WHERE recording_id = 'xxx'`。agent 是我们控制的 LLM，不需要防它跨 recording 查询。

### 工具 3: execute_code

**职责**：SQL 不够用时，临时执行 Python 代码探索数据。代码是手段，执行结果是目的。

**已确定的设计方向**：

- **SQL 的补充，不是替代**。90% 的查询用 SQL，只有需要循环遍历、复杂计算、数据处理时才用 execute_code。
- **临时代码**。跑完拿结果，不入库。与 submit_code（交付代码）本质不同。
- **沙箱执行**。需要安全限制，防止恶意或误操作。

**输入**：
- `code` — Python 代码

**输出**：代码的 stdout + 返回值

**已决策**：
- [x] 沙箱策略——**不做严格沙箱**，只加 **30 秒超时**防止死循环。agent 是我们控制的 LLM，限制太多会失去工具意义。模块白名单暂不做，后期视情况再加。
- [x] 预注入环境——预注入 `conn`（DuckDB 连接）和 `recording_id`。不预注入 import，agent 自己写。
- [x] 输出大小限制——**不截断**，与 query_data 一致，交给 ContextManager 处理。
- [x] 与 `_syntax_check` 的关系——**独立**。目的不同（探索数据 vs 交付代码安全检查），硬要共享反而互相牵制。

### 工具 4: analyze_image

**职责**：调多模态模型理解截图内容。代码看不了图片，这个能力必须单独提供。

**输入**：
- `action_index` — 操作序号，支持单个（`3`）或列表（`[2, 3, 4]`）
- `question` — 想了解什么（如"页面上有哪些表单元素"）

handler 内部按序号拉出 before/after 截图，按时间顺序排列传给多模态模型。before/after 是内部存储概念，不暴露给 agent。单次调用最多传 5 个 action_index（即最多 10 张图），超过则报错提示缩小范围。

**输出**：多模态模型的分析结果（文本）

**已决策**：
- [x] 模型与图片传递——**通用设计，不绑定具体模型**。通过 UnifiedConfigManager 获取用户配置的多模态模型，图片传递方式由驱动层适配（base64/URL/其他）。handler 只负责从 DuckDB 读出二进制数据，传给驱动层。
- [x] 是否缓存分析结果——**不缓存**。同一张图不同 question 结果不同，命中率低，简单优先。
- [x] 上下文管理——**图片不进 agent 主上下文**。handler 内部单独调一次多模态模型，只把文本结果返回给 agent。图片 token 开销是 handler 内部的事。暂不压缩，后续发现截图太大再加。

### 需要同步修改的地方

工具重新设计后，以下文档和代码需要同步更新：

- `pm_agent_design.md` — 删除 PM 版 query_recording_data 的工具定义（三、四节），改为引用本设计
- `programmer_agent_design.md` — 删除程序员版 query_recording_data 的工具定义（第三节），改为引用本设计
- `architecture_discussion_v2.md` — 更新"PM 和程序员是同一个工具的不同配置"的表述
- `src/business/agents/tools/pm_recording_tools.py` — 重构或替换
- `src/business/agents/tools/programmer_recording_tools.py`（尚未创建）— 不再需要单独文件

---

## 四、已解决的设计难点

> 以下问题在第三节逐个工具讨论过程中全部决策完毕，此处汇总记录。

### 1. describe 的粒度 → 渐进式两级返回
- 无参返回表概览（~100 token），传表名返回字段详情
- 每个字段都描述，硬编码在 handler 中
- 暂不提供 DuckDB 视图

### 2. SQL 安全与大字段 → 轻量防御 + 结构化占位
- 只允许 SELECT，正则检查 `^\s*SELECT\b`
- 大字段以 `__large_field__` 结构化占位对象交付（含预览和定位信息），Agent 可通过 `read_field_chunk` 分段续读
- 二进制字段替换为 `[截图（二进制）]`
- ContextManager 引用替换机制兜底

### 3. 衍生数据 / 视图 → 暂不提供
- agent 直接写 SQL 做 JOIN 和拼接
- 等实际跑起来发现频繁写某类复杂 SQL 时再加预定义视图

### 4. 二进制数据（截图） → analyze_image 工具
- describe 中标注为二进制字段，提示用 analyze_image
- SQL 查到截图字段返回占位提示
- analyze_image 从 DuckDB 读二进制，传给用户配置的多模态模型

### 5. execute_code 沙箱 → 轻量限制
- 不做严格沙箱，只加 30 秒超时
- 预注入 conn（DuckDB 连接）和 recording_id
- 模块白名单暂不做，后期视情况再加
- 与 `_syntax_check` 独立，目的不同

---

## 五、与现有架构的关系

### 数据存储层（已实现）

录制数据存储在 DuckDB（`data/mexemplar.duckdb`），表结构定义在 `src/data/models_duckdb.py`：

- `recording_sessions` — 录制会话元数据（recording_mode 字段区分 browser/desktop）
- `actions` — 操作记录（action_type, url, dom_element, dom_tree_snapshot, parameters, screenshot_before/after, ...）
- `network_requests` — 网络请求（url, method, request_type, request/response_headers, response_body, ...）
- `sibling_snapshots` — 兄弟元素快照（用于列表操作识别）
- `filter_decisions` — 网络请求过滤决策

数据访问通过 `src/data/recording_repository.py` 的 `RecordingRepository` 类。

### ContextManager 的引用替换机制

工具返回的大块数据在 N 步之后会被 ContextManager 替换为指针（`[REF::{message_id}]`），agent 需要时可以调 `load_reference` 加载回来。这意味着：

- 工具返回值即使偏大，也不会永久占据上下文——ContextManager 会自动清理
- 当次返回仍会占据上下文空间，但工具层不做截断（通过 describe 警告 + prompt 引导让 agent 自己控制查询量）
- 引用替换的阈值是 2000 字符（小于此值的工具结果不做引用替换）

### AgentLoop 的工具注册机制

工具以 `ToolDefinition(name, schema, handler)` 形式注册，通过 `loop.run(session_id, user_input, tools=[...])` 传入。`talk_to_user` 和 `load_reference` 由 AgentLoop 自动追加。

新工具设计需要产出：
- Function Calling JSON Schema（LLM 看到的接口定义）
- Handler 函数（实际执行逻辑）
- ToolDefinition 实例（注册到 AgentLoop）

---

## 六、设计完成标准

所有设计问题已决策完毕。以下验证清单用于实现时自检：

### describe_data
1. ✅ 不传 tables 返回表概览（表名 + 含义 + 行数）
2. ✅ 传 tables 返回字段详情（每个字段都描述）
3. ✅ 不同录制模式返回不同的表和描述（跟着 recording_mode 走）
4. ✅ 大字段 warning、二进制字段 warning 示例已在第三节给出

### query_data
5. `SELECT dom_element FROM actions WHERE sequence_number = 3`
6. `SELECT * FROM network_requests WHERE request_type = 'xmlhttprequest' AND response_headers LIKE '%application/json%'`
7. ✅ 原样返回，不截断。ContextManager 几步后自动引用替换。agent prompt 和 FC schema 已提醒按需查询。
8. ✅ 二进制字段替换为 `[二进制数据，请使用 analyze_image 工具]`
9. ✅ 正则检查 `^\s*SELECT\b`，非 SELECT 直接拒绝

### execute_code
10. 场景：需要遍历所有 action 的 dom_element JSON，提取所有出现过的 tag_name 并统计频次——SQL 处理嵌套 JSON 很费劲，Python 几行搞定
11. ✅ 预注入 conn + recording_id，agent 自己写 import
12. ✅ 30 秒超时，输出不截断交给 ContextManager

### analyze_image
13. `analyze_image(action_index=5, question="页面上有哪些表单元素")` 或 `analyze_image(action_index=[3,4,5], question="这几步操作页面发生了什么变化")`
14. ✅ 用户配置的多模态模型，图片不进 agent 主上下文，handler 内部调用

### 通用
15. ✅ PM 和程序员用完全相同的 5 个工具
16. ✅ 新增表只改 describe_data 的硬编码描述
17. ✅ 衍生数据由 agent 自己 SQL 拼，暂不提供预定义视图
18. 🔲 Function Calling Schema 待实现时产出

---

### read_field_chunk（已实现）
- 实现文件：`src/business/agents/tools/recording_data_tools.py`
- 占位对象带 `__large_field__` 标记，含 `locator`（定位信息）、`preview`（预览文本）、`size_chars`
- Agent 按 locator + field + offset + length 调用 read_field_chunk 分段读取原文
- network_requests 走 filtered SQL rewrite path，其他 StableLocatorRule 覆盖表走参数化直读
- 配置项：`recording.large_field.{threshold_chars, preview_chars, max_chunk_chars}`
- 详见 `specs/001-recording-field-layering/`

---

*创建时间：2026-03-18*
*最后更新：2026-04-24（5 个工具全部落地，新增 read_field_chunk）*
*前置讨论：programmer_agent_design.md 审阅过程中产生*

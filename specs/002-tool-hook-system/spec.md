# Feature Specification: 工具执行 Pre/Post Hook 系统

**Feature Branch**: `002-tool-hook-system`
**Created**: 2026-04-25
**Status**: Completed
**Input**: User description: "docs/local/tool-hook-plan.md 这次做这个，用speckitworktree新建个工作树"

## Clarifications

### Session 2026-04-25

- Q: `run_command` 的 5 次限流计数器作用域是什么？ → A: 每次 `AgentLoop.run()` 调用独立——开始时初始化为 0，`run()` 结束自动释放；不跨 run() 累计、不跨 session 共享、不持久化。
- Q: `AgentConfig.global_pre_hooks` / `global_post_hooks` 中"global"的作用域是什么？ → A: **AgentConfig 内全局**——仅对该 AgentConfig 下挂载的所有 `ToolDefinition` 工具生效；不作用于 AgentLoop 内建注入工具，不跨 Agent 类型共享、不引入框架级注册表。想让一个 hook 跨 PM/Programmer/Trial/Assistant 全部生效，由调用方在 4 个 AgentConfig 构造时各挂一份。
- Q: 除了从 handler 迁移过来的 5 类"门卫式"pre_hook，本 feature 是否还要交付新增的非校验类示例 hook（如 audit log）？ → A: **不交付**。本 feature 的代码产出 = hook 协议 + 5 类门卫迁移（`write_file` / `edit_file` / `exec` / `read_file` / `list_dir` / `query_data` / `analyze_image` / `run_command`）+ 单元测试。日志/审计/调用计时类 hook 由后续 PR 各自补；SC-005 仅作为"挂载成本"的结构属性指标，不要求本 feature 内真存在一份新示例 hook 文件。
- Q: hook 链中某一个 hook 抛异常时，链上**其后**的 hook 是否仍然执行？ → A: **整条链中止（abort）**。pre_hook 链中任意 hook 抛异常，立刻停止后续 pre_hook 的执行，直接进入 handler，并跳过本次工具调用的全部 post_hook；post_hook 链中任意 hook 抛异常，立刻停止后续 post_hook 的执行，handler 的原始结果直接返回 LLM。该决定不影响 AgentLoop 的 while 循环——工具调用一定会有结果上抛，loop 正常继续。
- Q: pre_hook 是否支持修改 handler 入参或形成 args 流水线？ → A: **不支持**。pre_hook 只做放行/拒绝/观测；handler 始终接收 LLM 原始入参。所有 pre_hook 看到的 `ctx.args` 都是同一份只读隔离视图，不存在 pre_hook 改参、merge、完全替换或流水线传递语义。
- Q: 多个 post_hook 串联（工具级 + 全局）时，链内 `args` 与 `result` 如何传递？ → A: **不做成流水线**。每个 post_hook 接收的 `ctx.args` 内容等价于 **LLM 原始入参**，但必须与 handler 入参隔离；接收的 `result` = **handler 原始返回值**（不会被前一 post_hook 改写）。链中多个 post_hook 同时改写 `result` 时，**最后一个**返回非 None `PostHookResult.result` 的 post_hook 生效。post_hook 主要面向只读用途（审计、日志、计时），不鼓励多 post_hook 同时改写 `result`。
- Q: handler 抛出**未捕获异常**时，post_hook 链是否执行？ → A: **正常执行**。若此前没有触发 FR-013 的 pre_hook 异常短路，AgentLoop 捕获异常并转换为 error 字符串，作为 `PostHook` 的第二个 `result` 参数传入；post_hook 链照常运行，可审计/记录/改写错误文案。异常本身不向 LLM 上抛（与现有 AgentLoop 行为一致）。
- Q: post_hook 获取 handler 结果时，是否应通过 `ToolCallContext.result`？ → A: 不通过 `ToolCallContext.result`。`ToolCallContext` 不携带 `result` 字段；post_hook 只通过第二个 `result` 参数接收 handler 原始结果或异常转换后的 error 字符串。
- Q: `PreHookResult` 是否包含 `args` 字段？ → A: 不包含。`PreHookResult` 只表达是否拒绝工具调用；返回 `error` 时短路 handler 和 post_hook，返回 None 或无 error 时放行。
- Q: `write_file` / `edit_file` / `exec` 的用户确认迁移到 pre_hook 时，确认能力是否进入 `ToolCallContext`？ → A: 不进入。用户确认仍由 `builtin_general_tools` 内的现有确认 helper 执行；对应 pre_hook 直接调用该 helper，`ToolCallContext` 不新增确认回调。
- Q: `analyze_image` 的 5 次限制是否是 per-run 调用计数器？ → A: 否。只保留现有“单次调用最多 5 个 action_index”的限制，并迁移到 pre_hook；不新增 per-run 调用次数计数器。
- Q: `talk_to_user` / `load_reference` 等 AgentLoop 内建注入工具是否进入 hook 管线？ → A: 不进入。本 feature 只覆盖通过 `ToolDefinition` 传入或动态构建的工具；AgentLoop 内建注入工具不受工具级或全局 hook 影响。
- Q: callable 工具路径中，同名工具的 handler / hook 变更是否必须在下一轮生效？ → A: 必须。schemas 可继续按工具名集合缓存，但执行映射（handler / pre_hook / post_hook）必须每轮按最新 `ToolDefinition` 刷新。
- Q: `ToolCallContext.args` 是否允许 hook 原地修改？ → A: 不允许。`ToolCallContext.args` 使用递归只读隔离视图；hook 尝试修改顶层字段或嵌套 dict/list 会抛异常，并按 hook 异常规则处理，handler 入参不受影响。
- Q: 当某个 `pre_hook` 抛出未捕获异常、AgentLoop 记录日志并继续执行 handler 后，handler 完成时是否还要继续执行 `post_hook` 链？ → A: 不执行。pre_hook 异常后只执行 handler，跳过本次工具调用的全部 post_hook，并直接返回 handler 的原始结果或异常转换后的 error 字符串。
- Q: `ToolCallContext.args` 的“只读隔离视图”应如何处理嵌套可变对象？ → A: 顶层和嵌套对象都必须递归只读；hook 对嵌套 dict/list 的修改会抛异常，handler 入参必须完全不受影响。

### Session 2026-04-26

- Q: 迁移门卫式校验后，handler 是否还能保留执行必需的解析/规范化/默认值处理？ → A: 可以。handler 允许保留执行必需的解析、规范化、默认值处理和核心执行准备；只把拒绝、确认、限流、安全策略判断迁移到 pre_hook。
- Q: `ToolCallContext.args` 的运行时写入行为是什么？ → A: 顶层和嵌套对象都暴露为递归只读隔离视图；hook 尝试修改会抛异常，按对应 pre/post hook 异常规则处理，handler 入参不受影响。
- Q: `edit_file` 的 `old_text` 存在且唯一校验是否迁移到 pre_hook？ → A: 不迁移。`old_text` 目标查找与唯一性校验属于编辑执行前的核心准备，留在 handler；pre_hook 只迁移路径存在性、用户确认等门卫逻辑。
- Q: `query_data` 的 SQL pre_hook 是否要做 raw-text 禁注释/禁分号？ → A: 不做 raw-text 禁注释/禁分号；pre_hook 复用现有 sqlglot/rewrite 解析与过滤策略，允许 harmless 注释和字符串内分号，拒绝多语句、非查询、隐藏/系统表等现有策略会拒绝的 SQL。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 工具执行管线支持统一的 Pre/Post 拦截 (Priority: P1)

作为 Agent 框架的维护者，我需要在 Agent 调用任何 `ToolDefinition` 工具之前与之后都能插入自定义逻辑（拦截、观测、改写返回值），并且这种能力对**已有 `ToolDefinition` 工具完全透明**——没有声明 hook 的工具行为不变。

**Why this priority**：这是整个 feature 的地基。没有这层引擎，后面的现有校验迁移（Story 2）和全局观测（Story 3）都无从挂载。任何一个高优工具能挂上 hook 并按约定语义执行，这个 feature 就有最小可交付价值。

**Independent Test**：用 1 个工具单元测试覆盖完整的钩子链——构造 1 个带 pre_hook（放行/拦截/误写入）和 post_hook（改结果）的工具，单独跑 AgentLoop 的工具执行路径，断言：(a) pre_hook 返回 error 时 handler 不被调用且错误返回 LLM；(b) pre_hook 放行时 handler 收到 LLM 原始入参；(c) pre_hook 尝试原地修改 `ToolCallContext.args` 顶层或嵌套 dict/list 时抛异常，handler 仍收到 LLM 原始入参，且本次 post_hook 被跳过；(d) 正常路径下 handler 返回值被 post_hook 改写后才返回 LLM。**不依赖任何已有工具迁移**即可验证。

**Acceptance Scenarios**:

1. **Given** 一个工具的 `pre_hook` 返回 `error="not allowed"`，**When** Agent 调用该工具，**Then** handler 不被执行，LLM 收到的工具结果是该错误文案，并且 `post_hook` 不被执行。
2. **Given** 一个工具的 `pre_hook` 尝试原地修改 `ToolCallContext.args` 顶层字段或嵌套 dict/list，**When** Agent 调用该工具，**Then** 该写入抛出 hook 异常，handler 看到的仍是 LLM 原始入参，并且本次 post_hook 不执行。
3. **Given** 一个工具的 `post_hook` 改写了 handler 返回值，**When** 调用完成，**Then** LLM 收到的是改写后的字符串，handler 自身的返回值不影响。
4. **Given** 一个**没有**声明 pre/post 的工具，**When** Agent 调用，**Then** 行为与未引入 hook 系统时完全一致。

---

### User Story 2 - 把分散在 handler 内的"门卫式"安全校验迁移到 pre_hook (Priority: P2)

作为代码库维护者，我希望 `builtin_general_tools`、`recording_data_tools`、`trial_tools` 三批工具里的"先校验后执行"逻辑（路径白名单、命令白名单、SQL 注入防护、用户确认、调用次数上限等）以**统一形式**收敛到 pre_hook，handler 函数体只保留核心业务，使后续审计、扩展、复用变得可行。

**Why this priority**：Story 1 提供了机制，Story 2 是把现有"内联校验"债务真正转化为统一管线的产出。没有这一步，新机制只是"有但没人用"。

**Independent Test**：对 `write_file`、`exec`、`query_data`、`run_command` 这四个最具代表性的工具，分别运行被拒绝路径的单元测试（写系统目录、含 shell 元字符的命令、多语句/隐藏表访问 SQL、超过 5 次的 run_command），断言（a）请求被 pre_hook 拒绝、（b）handler 未被调用、（c）原 handler 函数体内部已不再包含被迁移走的拒绝/确认/限流/安全策略判断，但仍可保留执行必需的解析、规范化、默认值处理和核心执行准备。

**Acceptance Scenarios**:

1. **Given** `write_file` 的 pre_hook 已挂载系统目录黑名单，**When** Agent 请求写入 `/etc/passwd` 或 `C:\Windows\System32\hosts`，**Then** 请求被拦截并返回拒绝原因，handler 未运行。
2. **Given** `exec` 的 pre_hook 已挂载白名单 + 元字符检测，**When** Agent 请求 `git status; rm -rf /`，**Then** 因检测到 `;` 元字符被拦截。
3. **Given** `query_data` 的 pre_hook 已挂载 SQL 安全策略，**When** SQL 为 `SELECT * FROM x; DROP TABLE y`（多语句），**Then** 被拦截。
4. **Given** `run_command` 的 pre_hook 维持调用计数，**When** 第 6 次调用进入，**Then** 被拦截并返回限流错误。
5. **Given** 上述工具的 handler 源代码，**Then** 不再包含已迁移走的拒绝/确认/限流/安全策略判断代码段；执行必需的解析、规范化、默认值处理和核心执行准备仍可保留。

---

### User Story 3 - 全局 Hook 用于跨工具的日志/审计/限流 (Priority: P3)

作为运维与质量负责人，我希望可以挂载**对当前 AgentConfig 下所有 `ToolDefinition` 工具生效**的 pre/post 钩子（例如：每次工具调用打日志、对所有耗时工具加超时审计），无需逐个工具改代码。

**Why this priority**：单工具 hook（Story 1+2）已能交付安全收敛，Story 3 让这层管线在系统级观测上发挥更大杠杆。是延展，但不阻塞 P1/P2。

**Independent Test**：写 1 个全局 pre_hook（记录 `tool_name + args.keys()` 到 list）+ 1 个全局 post_hook（记录 `tool_name + len(result)` 到 list），跑两个不同工具的调用，断言两个工具都触发了同一个全局 hook，且执行顺序为：工具 pre → 全局 pre → handler → 工具 post → 全局 post。

**Acceptance Scenarios**:

1. **Given** `AgentConfig.global_pre_hooks` 中挂了一个日志 hook，**When** Agent 在一次会话中调用 `read_file` 与 `query_data`，**Then** 该 hook 收到两次调用，且每次都能拿到对应的工具名和参数。
2. **Given** 同一工具同时挂了工具级 pre_hook 与全局 pre_hook，**When** 调用发生，**Then** 工具级 pre_hook 先执行，全局 pre_hook 后执行；二者看到的 `ctx.args` 内容等价于 LLM 原始入参，并以递归只读隔离视图暴露。
3. **Given** 工具级 pre_hook 已经返回 error，**When** 调用发生，**Then** 全局 pre_hook 不再执行，handler 不执行，post hook 不执行（短路）。

---

### Edge Cases

- **同步 vs 异步 handler**：当前所有 handler 是同步函数；hook 也按同步契约设计，不强制异步化。
- **动态工具懒加载路径**（assistant Agent 的 callable 工具构建）：schemas 可继续按工具名集合缓存，但执行映射（handler / pre_hook / post_hook）和用于批处理分类的 `ToolDefinition` 元数据（含 `is_interrupting`）必须每轮按最新对象刷新；同名工具的 handler、hook 或中断类型变更必须在下一轮生效。
- **AgentLoop 内建注入工具**：`talk_to_user`、`load_reference` 不是调用方传入的 `ToolDefinition`，本 feature 不把它们纳入 hook 管线；全局 hook 仅对当前 `AgentConfig` 下的 `ToolDefinition` 工具生效。
- **hook 链异常**：任意 pre/post hook 抛异常时，整条链 abort——pre 链异常会停止剩余 pre_hook、直接进 handler，并跳过本次工具调用的全部 post_hook；post 链异常直接返回 handler 原始结果。剩余同链 hook **不再执行**（含审计、限流类全局 hook）。AgentLoop 循环不中断（工具调用一定有结果上抛）。详见 FR-013。
- **多工具批处理路径**：AgentLoop 会先按当前 `ToolDefinition.is_interrupting` 对同轮 tool calls 做批处理分类。混合中断型批次、未知工具、`not_executed` 等 AgentLoop 控制错误不进入 hook；只有实际要执行 handler 的工具调用进入 hook 链。普通多工具批次中，pre_hook 拒绝、handler 异常、标准化错误结果或 handler/`is_interrupting` 契约违规都视为可靠失败，必须触发现有 `not_executed` 级联。
- **ToolSignal 类型返回值**（`submit_requirements`、`submit_code`、`submit_trial_result` 等 `is_interrupting=True` 的信号工具）：合法单中断调用允许执行 pre_hook，但 post_hook **不应**改写信号；handler 返回 `ToolSignal` 后信号原样上抛 AgentLoop。若中断型工具与其他工具同轮出现，按批处理非法输出处理，不执行 hook 或 handler。
- **handler 抛未捕获异常**：普通工具若此前没有触发 FR-013 的 pre_hook 异常短路，AgentLoop 捕获并转换为标准化 error 字符串，post_hook 链**照常执行**（该 error 字符串作为 `PostHook` 的第二个 `result` 参数传入），异常不向 LLM 上抛；批处理失败级联依据原始执行状态判定，不被 post_hook 改写后的文本掩盖。详见 FR-015。
- **现有依赖反射工具列表的位置**（如 PM/程序员 Agent 直接传 `list[ToolDefinition]`）：必须无感支持 hook，不需要每个 Agent 独立改代码。
- **配置热更新场景**：hook 配置目前**不是**通过 unified_config 暴露给运行期热改，仅在 AgentConfig 构造期固定；这是有意约束。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**：`ToolDefinition` 工具调用路径**必须**在 handler 执行前后插入用户定义函数（pre_hook、post_hook）。
- **FR-002**：pre_hook **必须**能否决工具调用——返回错误后，handler 不执行、post_hook 不执行，错误文本以标准化工具错误结果的 `message` 形式返回 LLM；在普通多工具批次中，该拒绝必须作为可靠失败触发同轮后续工具的 `not_executed` 级联。
- **FR-003**：pre_hook **不得**修改传给 handler 的参数。handler 收到的始终是 LLM 原始入参；`ToolCallContext.args` 本身为递归只读隔离视图，hook 原地修改顶层字段或嵌套 dict/list 时必须抛异常并按 FR-013 处理；通过返回值表达改参也不得改变 handler 入参。
- **FR-004**：post_hook **必须**能改写 handler 返回值；LLM 收到的是改写后的字符串。多个 post_hook 串联时，每个 post_hook 都接收 handler 的**原始**返回值（**链不流水线**——前一 post_hook 的改写不被后一 post_hook 看到）；LLM 最终收到的是链中**最后一个**返回非 None `PostHookResult.result` 的 post_hook 改写结果，若无任何 post_hook 改写则为 handler 原始返回值。
- **FR-005**：执行顺序**必须**为：工具级 pre_hook → 当前 AgentConfig 的 global pre_hooks（按列表顺序）→ handler → 工具级 post_hook → 当前 AgentConfig 的 global post_hooks（按列表顺序）。任意一个 pre_hook 返回 error 即短路全部后续步骤。"global" 的作用域仅限于当前 AgentConfig 实例（见 Key Entities），不存在跨 AgentConfig 的框架级全局 hook 链。pre_hook 链与 post_hook 链都**不做流水线**：所有 hook 都接收 LLM 原始入参的递归只读隔离视图；所有 post_hook 都接收 handler 原始返回值，详见 FR-004。
- **FR-006**：`builtin_general_tools` 中 `write_file`、`edit_file`、`exec`、`read_file`、`list_dir` 的"门卫式"校验（系统目录黑名单/白名单拒绝判断、路径存在性/文件目录类型拒绝判断、命令白名单拒绝判断、shell 元字符拒绝判断、用户确认）**必须**全部迁移到对应工具的 pre_hook；handler 函数体内不再保留这些拒绝/确认判断。`edit_file` 的 `old_text` 目标查找与唯一性校验属于编辑执行前的核心准备，**不**迁移到 pre_hook，允许保留在 handler 内。handler 允许保留执行必需的解析、规范化、默认值处理和核心执行准备。用户确认仍复用 `builtin_general_tools` 内现有确认 helper，由对应 pre_hook 调用；不把确认回调加入通用 `ToolCallContext` 协议。
- **FR-007**：`recording_data_tools` 中 `query_data` 的 SQL 安全策略与 `analyze_image` 的"单次调用最多 5 个 action_index"限制**必须**迁移到 pre_hook。`query_data` 的 pre_hook 必须复用现有 `sql_rewriter.rewrite()` / 过滤策略进行拒绝判断：拒绝解析失败、多语句、非查询语句、隐藏表/系统表访问等现有策略会拒绝的 SQL；不得新增 raw-text 禁注释或禁字符串内分号规则。`query_data` 的返回值清洗 `_sanitize_query_value` 仍保留在 handler 内。handler 允许保留执行必需的参数解析、`rewrite(sql)` 查询执行准备和结果转换。`analyze_image` 不新增 per-run 调用次数计数器。
- **FR-008**：`trial_tools` 中 `run_command` 的调用次数上限（5 次）**必须**通过闭包捕获计数器实现并迁移到 pre_hook。计数器作用域为**单次 `AgentLoop.run()`**，run() 开始时初始化为 0，run() 结束自动释放（不跨 run() 累计、不跨 session 共享、不持久化）。handler 允许保留执行命令所需的调用封装和结果转换。
- **FR-009**：以下逻辑**必须**保留在原位，**不**迁移到 hook：`programmer_tools.syntax_check`（整个 handler 即校验本身）、`recording_data_tools.execute_code` 的运行时沙箱（受限 builtins/import/超时）、`tool_executor` 的 venv 隔离与命令白名单（位于 handler 层之下）、`dynamic_tool_manager` 的发布状态与允许列表（属于工具发现/激活，非执行路径）。
- **FR-010**：hook 系统**必须**对未声明 pre/post 的 `ToolDefinition` 工具完全透明——所有现有 `ToolDefinition` 与现有测试零修改即可继续通过。
- **FR-011**：hook 系统**必须**在动态工具构建路径（`AgentLoop._rebuild_tools` 接收 callable 重建工具列表）下同样生效。callable 每轮返回 `ToolDefinition` 列表后，schemas 可继续按工具名集合缓存，但执行映射（handler / pre_hook / post_hook）和批处理分类使用的 `ToolDefinition` 元数据（含 `is_interrupting`）**必须**每轮按最新对象刷新；同名工具的 handler、hook 或中断类型变更必须在下一轮生效。
- **FR-011a**：AgentLoop 内建注入的 `talk_to_user`、`load_reference` **不**进入 hook 管线，不受工具级 hook 或当前 AgentConfig global hooks 影响。
- **FR-012**：hook **必须**能从上下文获取至少：工具名、原始入参、session id、Agent 类型、当前迭代序号。
- **FR-013**：hook 抛出未捕获异常时，**必须**记录日志且不污染工具结果，且**整条 hook 链中止**：
  - **pre_hook 链异常**：立刻停止该链中后续 pre_hook 的执行（不论是工具级还是 global 级），跳过本次校验阶段的剩余 hook，**直接进入 handler 执行**，handler 完成后**跳过本次工具调用的全部 post_hook**，并直接返回 handler 的原始结果或异常转换后的 error 字符串；
  - **post_hook 链异常**：立刻停止该链中后续 post_hook 的执行，handler 的**原始返回值**直接返回给 LLM，不再被任何 post_hook 改写；
  - 异常不向上传播到 AgentLoop，AgentLoop 的 while 循环不受影响；
  - 异常本体记录到项目标准 logger，level 不低于 WARNING。
- **FR-014**：`ToolDefinition.is_interrupting=True` 且 handler 返回 `ToolSignal`（例如 `submit_requirements`、`submit_code`、`submit_trial_result`）时，post_hook **必须**被跳过，信号原样上抛 AgentLoop；`is_interrupting=False` 的普通工具若返回 `ToolSignal`，属于 handler 契约违规，必须按标准化错误处理，不进入 post_hook。
- **FR-015**：普通工具 handler 抛出**未捕获异常**时，AgentLoop **必须**捕获并将异常转换为标准化 error 字符串作为工具结果；若此前没有触发 FR-013 的 pre_hook 异常短路，该字符串以 `PostHook` 的第二个 `result` 参数传给 post_hook 链，post_hook 链**照常执行**（可审计、可改写错误文案）；异常本身不向 LLM 上抛。批处理级联必须依据原始 handler 异常状态判定，即使 post_hook 改写了最终文本，也不得把该失败误判为成功。
- **FR-016**：hook 系统**必须**保留 `003-fix-agentloop-tool-calls` 已引入的多工具批处理语义：执行任何 hook/handler 前先按当前 `ToolDefinition.is_interrupting` 分类；混合中断型批次直接写入 `invalid_model_output`，不执行 hook/handler；普通批次按顺序逐个执行 hook-aware 工具调用，可靠失败后为后续调用写入 `not_executed`；合法单中断调用可执行 pre_hook 与 handler，但成功 `ToolSignal` 跳过 post_hook，失败/契约违规不触发暂停或完成语义。

### Key Entities *(include if feature involves data)*

- **ToolCallContext**：单次工具调用的不可变上下文。包含 `tool_name`、`args`、`session_id`、`agent_type`、`iteration` 等读字段；hook 接收后不修改它本体，且不携带 `result` 字段或用户确认回调。`args` 字段向 hook 暴露为 LLM 原始入参的递归只读隔离视图：顶层字段和嵌套 dict/list 都不得写入，尝试写入必须抛异常；该异常按对应 pre/post hook 异常规则处理，且 handler 入参不受影响。pre_hook 与 post_hook 都不能通过原地修改 `ctx.args` 或返回值改写 handler 入参。
- **PreHookResult**：pre_hook 的返回值。语义：仅表达是否拒绝工具调用；携带 `error` 时立即短路 handler 和 post_hook，并把错误文本以工具结果形式返回 LLM。返回 None 或无 error 表示放行。`PreHookResult` 不携带 `args` 字段，不支持 merge、完全替换或删除参数语义。
- **PostHookResult**：post_hook 的返回值。语义：可能携带 `result`（替换原 handler 字符串结果）。多个 post_hook 串联且各自改写 result 时，链中**最后一个**返回非 None `result` 的 post_hook 生效；前面 post_hook 的改写不被后续 post_hook 看到（链不流水线，详见 FR-004）。
- **PreHook / PostHook**：可调用类型别名。前者签名 `(context) -> PreHookResult | None`；后者签名 `(context, result) -> PostHookResult | None`，其中 `result` 为 handler 原始字符串结果或 handler 异常转换后的 error 字符串。返回 None 表示"对该次调用无影响"。
- **ToolDefinition**（扩展）：在现有字段（含 `is_interrupting: bool = False`）基础上新增可选 `pre_hook` / `post_hook` 字段，默认 None。`is_interrupting` 继续作为 AgentLoop 批处理分类和 handler 返回契约校验的唯一声明式来源；只有通过调用方传入或动态构建的 `ToolDefinition` 工具才参与 hook 管线。
- **AgentConfig**（扩展）：新增 `global_pre_hooks: list[PreHook]` / `global_post_hooks: list[PostHook]`，默认空 list。**作用域为该 AgentConfig 实例内所有 `ToolDefinition` 工具**——不跨 AgentConfig 实例共享，没有"框架级全局"注册表的概念；也不作用于 AgentLoop 内建注入的 `talk_to_user` / `load_reference`。需要跨 PM/Programmer/Trial/Assistant 复用同一 hook 时，调用方在每个 AgentConfig 构造时各挂一份。

### Constraints & Compatibility *(include when relevant)*

- **CC-001**：现有所有 Agent 单元测试与集成测试**必须**零修改通过，作为向后兼容的硬证据。
- **CC-002**：不引入新的第三方依赖；hook 协议用 dataclass + Callable 即可。
- **CC-003**：同步 handler **不**改造为异步；hook 协议本身保持同步契约。
- **CC-004**：删除策略——FR-006/007/008 涉及的旧拒绝/确认/限流/安全策略判断代码必须**整段删除**（含相关注释），不允许并行保留作为"备用路径"；执行必需的解析、规范化、默认值处理、核心执行准备和结果转换不属于必须删除范围。`edit_file` 的 `old_text` 存在性/唯一性校验按 FR-006 视为执行准备，不属于必须删除的门卫式校验。
- **CC-005**：hook 配置作用域为 AgentConfig 构造期固定；运行期不通过 unified_config 热改，避免与 ContextManager / Worker 的并发语义打架。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **Business** (`src/business/`) — `agents/agent_loop.py`、`agents/config.py`、`agents/tools/builtin_general_tools.py`、`agents/tools/recording_data_tools.py`、`agents/tools/trial_tools.py`，新增 `agents/hook_models.py`

不涉及 UI / Execution / Data / Recording / Utils 改动。

### Agent Impact *(if touching Agent system)*

- 受影响 Agent：**PM / Programmer / Trial / Assistant 全部**——它们共享 `AgentLoop._execute_tool_batch` / `_execute_solo_interrupt` 下沉到 `_execute_tool_call` 的工具执行路径。
- 工具 handler 改动：5 个 builtin 工具 + `query_data` + `analyze_image` + `run_command`，handler 函数体精简，校验前移；其他工具不变。
- System prompt 变更：**无**。
- Orchestrator dispatch 变更：**无**——Orchestrator 不直接管工具执行，hook 仅在 AgentLoop 内可见。

### Data Store Impact *(if touching data layer)*

- 不涉及 SQLite / DuckDB / Config / Secrets。

### Event Impact *(if adding/changing events)*

- 不新增 blinker 事件。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**：现有所有 Agent 与工具相关的单元/集成测试零修改下通过率 **100%**。
- **SC-002**：在单次工具调用上，整套 hook 链（工具 pre + 1 个全局 pre + 工具 post + 1 个全局 post，hook 内部为空操作）相对未挂任何 hook 的额外开销不超过 **5 ms**（在本地基准机上）。
- **SC-003**：被迁移的"门卫式"校验在新 pre_hook 路径下被拦截的覆盖率与现状**等价**：`tests/test_hook_protocol.py` 至少为以下场景各自提供 1 个测试——`write_file` 系统目录、`exec` 元字符、`exec` 非白名单命令、`query_data` 多语句/非查询语句/隐藏或系统表访问拦截、`run_command` 第 6 次调用拦截、`analyze_image` 单次传入 6 个 action_index 拦截；同时保留 `query_data` harmless 注释和字符串内分号的允许路径。
- **SC-004**：handler 函数体内**不再出现**已迁移的拒绝/确认/限流/安全策略判断代码（通过 grep / AST 静态扫描验证：`builtin_general_tools` handler 内不再执行系统目录拒绝、命令拒绝或用户确认判断；`recording_data_tools` handler 内不再有 SQL 安全策略关键字扫描）。执行必需的解析、规范化、默认值处理、核心执行准备和结果转换可保留；`edit_file` handler 内允许保留 `old_text` 存在性/唯一性校验。
- **SC-005**：**结构属性指标**——开发者在本 feature 完成之后，挂载一个新的全局 pre_hook（例如调用日志打印）所需新代码 ≤ **30 行**，且不需要修改任何工具的 handler、不需要修改 AgentLoop 引擎本体。本 feature **不**附带这样的示例代码，仅以"挂载成本"做为评价指标。
- **SC-006**：动态工具懒加载路径（assistant Agent）下，同名工具新增或替换 hook 后，即使工具名集合不变，下一轮工具调用也必须使用最新 hook；专门的链路冒烟测试覆盖此路径。
- **SC-007**：hook 协议测试必须覆盖 `ToolCallContext.args` 的递归只读隔离：hook 尝试修改顶层字段或嵌套 dict/list 时会抛异常；pre_hook 误写入时 handler 收到的参数仍与 LLM 原始入参一致且本次 post_hook 被跳过。
- **SC-008**：多工具批处理回归必须保持 003 语义：普通多工具批次中 hook 拒绝或 handler 失败会触发后续 `not_executed`；混合中断型批次不会执行任何 hook/handler；合法单中断工具的 `ToolSignal` 仍直接返回既有 AgentResult。

## Assumptions

- AgentLoop 当前架构（同步 handler、`_rebuild_tools` 双模式：list / callable、`_execute_tool_batch` 多工具批处理、`_execute_solo_interrupt` 单中断路径）保持稳定，本 feature 不顺手重构 AgentLoop 整体形态。
- 现有 `ToolSignal` 语义（信号工具中断循环）保持不变。
- 所有受影响工具当前的 handler 约定（同步、返回 str 或 ToolSignal）保持不变；`recording_data_tools.execute_code` 的运行时沙箱视作 handler 内核的一部分，不做 hook 化。
- 调用统计、日志、审计等观测能力的具体实现属于"如何使用 hook"的下游问题，**不在本 feature 的代码交付物里**——本 feature 仅交付 hook 协议、5 类门卫迁移与单元测试；非校验类 hook（audit log、perf timer 等）由后续 PR 各自补，不打包进本 feature。
- `tests/test_hook_protocol.py` 是唯一新增测试文件，其他测试文件不修改是预期目标（CC-001 的硬约束）。

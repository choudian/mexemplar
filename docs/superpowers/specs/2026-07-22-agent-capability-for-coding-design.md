# 让本系统自己承担编码开发的能力缺口

日期：2026-07-22
状态：逐条推进中

## 背景与目标

目标是用 Exemplar 自己的主助理 + 专员 + 临时子代理承担代码开发，而不是依赖外部
Claude Code / Codex CLI —— 后者只是当前的一条路，不能是唯一的路。

调查过程中读了 Claude Code 的泄漏源码（2026-03-31 经 npm `.map` 文件泄漏，
约 1900 文件 / 51 万行 TypeScript），用于对标。

## 关键认知：层级映射

最初的对比是错的。Claude Code 的主 agent **不对应** Exemplar 的主助理：

```
Claude Code                    Exemplar
                               用户
                                ↓
                          【主助理】← Claude Code 没有这一层
                                ↓
用户 ←→ 主 agent（干活）  ≈    专员（干活）
          └─ 子代理              └─ 临时子代理
```

**Claude Code 整个就是一个开发专员**，它上面直接是人。Exemplar 多出的主助理层是
增量价值（跨任务调度、跨领域协调、长期记忆），不是负担，代价是多一次信息传递损耗。

由此得出设计原则：**专员对标 Claude Code 主 agent**，照能力清单逐行补齐。

协作结构本身**不需要改**。两边都是 2 层半，第三层都限死在"同步、一次性、不能再派"：

- Claude Code：普通子代理的 Agent 工具被过滤（`agentToolUtils.ts:196`）；
  in-process teammate 可派同步子代理但不能派后台、不能再派 teammate（`:102-103`）
- Exemplar：专员至多起一个同步临时子代理（`tool_registry.py:341`）

## 完整清单

| # | 问题 | 状态 |
|---|---|---|
| 0.1 | codex 收到的是路径不是任务书 | 已归档 035 |
| 0.2 | 目标仓库选填，默认改 Exemplar 自己 | 已归档 035 |
| **1.1** | **token 用量完全没记录** | **已定稿（本文）** |
| **1.2** | **撞轮次上限是 ERROR / 静默挂起** | **已定稿（本文）** |
| **1.3** | **压缩体系补强（含原 2.6 / 6.1 / 6.2）** | **已定稿（本文）** |
| **1.4** | **单条消息工具结果总预算** | **已定稿（本文）** |
| 2.1 | 执行体拿不到项目文档 | 待过 |
| 2.2 | 轮次硬编码 30，要做成配置项（含 per-agent 模型） | 待过 |
| 2.3 | 预算维度（用户已砍掉 token 限制，剩轮次 / 时间） | 后议 |
| 3.1 | 专员每次新建会话，完全失忆 | 待过 |
| 3.2 | 专员没有专属记忆（对标 agent memory 三档 scope） | 待过 |
| 4.1 | 蒸馏不覆盖执行体会话（14 个干活会话，0 个被提炼） | 待过 |
| 4.2 | 归属是自由文本（27 个 scope 值，26 个只用过一次） | 待过 |
| 4.3 | 推翻机制没接线（`superseded_by` 用了 0 次） | 待过 |
| 4.4 | 记忆全量注入，没有索引 + 按需召回 | 待过 |
| 4.5 | 执行体拿不到任何记忆 | 待过 |
| 4.6 | 没有巩固工序（对标 autoDream） | 待过 |
| 4.7 | 36% 蒸馏失败率，原因未查 | 待查 |
| 5.1 | DAG 可视化 | 另有设计文档 |
| 5.2 | 孤儿 worktree 无人清理 | 未设计 |
| ~~6.3~~ | ~~2 个任务卡在 `pending_dispatch`~~ | **误报，非问题**（见附录） |

---

## 1.1 记录 token 用量

### 现状

`llm_client.py:331` 直接丢弃整个响应对象：

```python
response = self.llm.invoke([message], **kwargs)
return response.content   # usage_metadata 随函数返回一起消失
```

后果：跑一个任务花了多少、哪个环节烧的、哪个专员最费，全查不到。Kimi 额度用尽时
无法回溯原因。

### 实测证据

两个 provider × 两条调用路径（普通 / 工具调用），全部完整返回：

| | GLM-4.7 | 讯飞 astron-code |
|---|---|---|
| 回一个 "ok" | 257 token（推理 243） | 13 token（推理 0） |
| 工具调用一次 | 228 token（推理 52） | 165 token（推理 0） |
| `usage_metadata` 结构 | 完整 | 完整 |

两家结构**完全一致**（LangChain 已标准化），含 `input_token_details.cache_read` 与
`output_token_details.reasoning`。写一次取值代码适用于所有 OpenAI 兼容 provider。

同样的活成本差 **20 倍** —— 差异来自推理 token，而这部分**不在返回的 content 里**。

字符估算的偏差实测（讯飞，输入侧）：

| 样本 | 项目估算 | 真实 | 偏差 |
|---|---|---|---|
| 纯英文 | 28 | 21 | 高估 33% |
| 纯中文 | 23 | 37 | **低估 38%** |
| 中英混合 | 43 | 37 | 高估 16% |

输出侧对推理模型完全失效：content 为 `'ok'` 时估算 1 token，实际 246。

### 定稿

**只做记录，不做任何限制**（用户明确决定不给子 agent 限 token 量）：

- `LLMResponse` 增加 usage 字段：input / output / total / cache_read / reasoning
- `_extract_response` 取 `ai_message.usage_metadata`；**`chat()` 也必须改**，它现在
  把整个响应扔了
- 取不到时用字符估算兜底，标记来源 `actual` / `estimated`
- 挂在 assistant 消息上落库，可按会话 / 任务 / 专员聚合

**估算兜底的定位必须写明**：只服务压缩触发（输入侧，±40% 可接受），不服务成本口径
（输出侧对推理模型差两个数量级）。

由此得出一条硬约束：**不返回 usage 的 provider 不得配推理模型**，否则消耗完全不可见。

### 消耗作为信号而非闸门

不设限制，但任务回流时在 briefing 里带上本次消耗（含推理占比）。主助理看到一个任务
烧了大量 token 仍未完成，可自行判断是否任务拆得过大 —— 决定权在它，不是被硬停。

---

## 1.2 撞轮次上限转暂停，且父侧收得到

### 现状：一条完整的静默挂起链路

```
撞轮次上限
  → agent_loop.py:1369-1381  resumable 时返回 PAUSED，只带 result_type 和 error 文本，
                              不带 reentry_type / suspend_reason
  → task_executor_adapter.py:204-218  suspend_reason 落默认 waiting_system；
                                       reentry_type 仅在存在时透传
  → dispatcher.py:633-651  _paused_reentry_payload 只认 task_question / needs_review，
                            其余一律返回 None
  → 父侧零通知，任务静默挂起
```

有个细节说明这是疏忽而非设计：撞上限在**不可恢复**分支保留了明确的
`ResultType.MAX_ITERATIONS_REACHED`，在**可恢复**分支反而只剩 error 文本。

### 影响范围：临时子代理已经中招

- `delegate_to_subagent` 按复杂度分路（`delegation_orchestrator.py:38-70`）：
  simple 走同步委派（主助理直接拿到 paused，**无此问题**）；complex 走统一模型建图
  → 进 task 框架 → **命中上述链路**
- 临时子代理 `resumable_on_failure=True`（`orchestrator.py:1838`），所以复杂路径下
  这个缺口**现在就存在**
- 专员 `resumable_on_failure` 未设、取默认 False（`orchestrator.py:1848`），撞上限直接
  ERROR —— 反而误打误撞避开了静默挂起

实际数据：14 个临时子代理会话**全部 completed**，尚未触发过。但一旦承担编码任务，
撞上限将成为常态。

### inspect / continue 对专员的可用性：已验证可放开

阻塞点只有一处硬编码类型检查（`orchestrator.py:1090`）：

```python
if getattr(session, "agent_type", None) != AgentType.EPHEMERAL_SUBAGENT:
    return None
```

后续三层归属校验对专员**天然成立**，因为专员 session 与临时子代理用同一个
workflow_id 生成函数：

```
delegation_orchestrator.py:135  临时子代理  workflow_id = _new_delegation_workflow_id(parent)
delegation_orchestrator.py:339  专员        workflow_id = _new_delegation_workflow_id(parent)
                                            → 均为 dlg_<父会话哈希>_<随机>
orchestrator.py:1132            校验         workflow_id.startswith(f"dlg_{parent_hash}_")  ✓
```

parent_session_id 链路亦已确认：`service.py:329` 建图时 `owner_session_id = session_id`
（主助理会话）→ `task_executor_adapter.py:55` 取 `owner_session_id or session_id`
→ 传入 `run_specialist_via_delegated_executor` → 哈希对得上。

边界（正确行为）：专员再派出的子代理，主助理 inspect 不到 —— 那个子任务的 owner 是
专员会话，越级查看被拒，正是该校验要守的东西。

### 定稿

```
1. AgentLoop 撞上限的 PAUSED 返回带上暂停原因
   —— 改这一处，专员与临时子代理同时覆盖（共用同一个 AgentLoop）
2. _map_to_outcome 将其映射为 suspend_reason + reentry_type
3. SuspendReason 增加"预算用尽"值（现仅有等用户 / 等系统 / 用户停止）
4. _paused_reentry_payload 增加对应分支，父侧收得到通知
5. specialist_config 增加 resumable_on_failure=True
6. orchestrator.py:1090 类型检查放开专员
   → inspect_subagent / continue_subagent 对专员立即可用；
     continue 自带 extra_iterations=20，追加预算的形态现成
7. 通知内容：撞了上限 + 已跑轮数 + 上限值 + 进展摘要
   —— 到此为止，后续处置交给父侧自行决断（父侧是 ReAct agent，
      且手握 mutate_task_graph / decide_task_adjudication / abandon 等动作空间）
```

**实施顺序**：1-4 先做（修临时子代理已有缺口），5-6 后做（让专员进入这条路），
否则专员会从"报错"变成"静默挂起"，比现状更糟。

### 对标数据

Claude Code 的同一问题处理方式：

- `maxTurns` 是 agent frontmatter 的**可选**字段（`loadAgentsDir.ts:89`），
  `query.ts:1705` 写作 `if (maxTurns && ...)` —— **不配就是无上限**
- 撞上限**不是失败**（`query.ts:1705-1711`）：发一条 `max_turns_reached` 消息，
  然后 `return { reason: 'max_turns', turnCount }`，与"完成"同属正常返回
- 有明确上限的反而是特例：fork 子代理 200 轮、提炼记忆 5 轮 —— 都是已知该跑几轮的活

---

## 1.3 压缩体系补强

原清单里 1.3 / 2.6 / 6.1 / 6.2 是同一件事的不同侧面，合并到这里。

### Claude Code 的实际形态：不是四层，是六道

读 `query.ts` 主循环，每次请求前按顺序过一遍：

```
messagesForQuery = 上一个 compact 边界之后的消息          query.ts:365
      ↓
① applyToolResultBudget   一条消息内工具结果总和超预算 → 替换预览   :379  不调模型
      ↓
② snip                    砍历史片段，记录省了多少 token           :401  不调模型
      ↓
③ microcompact            清旧工具结果正文                        :414  不调模型
      ↓
④ context collapse        分段折叠，跑在 autocompact 前            :440  调模型
      ↓
⑤ autocompact             整体结构化摘要（先试 SessionMemory）      —    调模型
      ↓
   发请求
```

**三条运转规律**：

1. **从不要钱的往要钱的走**。前三道纯本地字符串操作。每一道都在试图让后面那道不必发生。
2. **每道向下一道上报省出量**。`:397-399` 注释：`snipTokensFreed is plumbed to
   autocompact so its threshold check reflects what snip removed`。
3. **后面的机制等前面的结果**。`:429-431`：collapse 跑在 autocompact 前，
   `so that if collapse gets us under the autocompact threshold, autocompact is a
   no-op and we keep granular context instead of a single summary` ——
   宁可多跑一道，也不愿整段历史被压成一坨。

**刻意设计成互不干扰**（`:369-372`）：content replacement 跑在 microcompact 之前，
因为 cached MC 纯按 `tool_use_id` 操作、从不检查内容，两者组合得很干净。

### 记账机制：一个锚点 + 两种修正

```
tokenCount = 上次 API 返回的真实 token（input + output + cache_creation + cache_read）
           + 那之后新增消息的估算
           - 各机制上报的省出量
```

（`tokens.ts:48-51` + `autoCompact.ts:225`）

**为什么各机制必须主动上报**：基准值从**最后一条 assistant 消息**读取，而 snip 砍的是
它前面的历史 —— 那条消息还在，身上记的 usage 仍是砍之前的数，**测量点本身看不见前面
发生的删除**。故只能显式传 `tokenCount - snipTokensFreed`。

**并行工具调用的坑**（`tokens.ts:214-224`）：模型一次调 N 个工具时，流式代码拆成 N 条
assistant 记录，**共用同一个 message.id 和同一份 usage**，工具结果穿插其间：

```
assistant(id=A), 结果1, assistant(id=A), 结果2, assistant(id=A), 结果3
```

若从最后一条 assistant 往后估，只估到结果3，**前两个结果全漏**——而它们下次请求都要
发出去。故拿到带 usage 的记录后要往前走到同 `message.id` 的第一条。本项目支持 4 路
并发工具调用，同样中招。

**对 c1 的要求**：阈值判断要留一个"各机制省出量"扣减接口。当前扣减项为空
（microcompact 不做、1.4 待定），但接口先留，避免以后加一道就改一次判断逻辑。

### 各层对本项目的适用性

| 层 | 本项目 | 结论 |
|---|---|---|
| ① 工具结果总预算 | 无（output governance 是**单条**上限，不是总和） | **1.4，做** |
| ② snip | 无 | 不做 |
| ③ microcompact | 无 | **不做**（见下） |
| ④ context collapse | `load_reference` 部分等价 | **升级为 1.3e** |
| ⑤ autocompact | 有但弱 | **主战场，本节 a/b1/c1/d** |

**③ microcompact 不做的理由**（记录下来避免重开）：它的三条触发路径本项目全不通——
缓存编辑 API 是 Anthropic 专有；时间触发要求已知的缓存 TTL，而各 provider 不同且不公开；
无条件清理 Claude Code 自己已删除（`microCompact.ts:288-291`），用户当年也因死循环废弃过，
两边判断一致。更关键的是 **1.3e 是更优等价物**：内容可取回而非永久丢失，靠自己能测的
token 阈值而非猜不到的 TTL。另外本项目已有 Claude Code 缺失的一层——output governance
的 12000 字符写入时上限，大输出压根不进上下文，他们非要 microcompact 正是因为缺这层。

### a. 摘要不重压，改为分段累积

`_split_messages`（`compression_handler.py:343-381`）纯按位置切：

```python
keep_count = min(self.keep_recent, total_count)
compress_start = len(messages) - keep_count
compress_msgs = messages[start_idx:compress_start]   # 除最后 N 条外全进压缩区
```

**完全不判断某条消息是否为上次的摘要**。摘要（`role="summary"`,
`message_type="compressed"`）是活跃消息，新消息追加后即被挤出保留区，于是：

```
第 1 次：80 条原文          → 摘要A
第 2 次：摘要A + 80 条新的  → 摘要B    ← 摘要A 被重压
第 3 次：摘要B + 80 条新的  → 摘要C    ← 摘要A 已是第三手信息
```

越早期的内容失真越累积，而编码任务里最早期的恰恰最重要（需求是什么、为什么选这个
方案、哪条路已试过不通）。

**改法**（三处）：
1. `_split_messages` 识别 `message_type == "compressed"`，摘要不进压缩区
2. `keep_recent` 只对原文消息计数，摘要不占保留区名额
3. `_rebuild_messages`（`:474-483`）现在只收单个 `compressed_msg`，改为收摘要列表按
   sequence 排序插入

结果形态：

```
[system] [摘要1 · 覆盖 1-80] [摘要2 · 覆盖 81-160] [摘要3 · …] [最近 N 条原文]
```

`compressed_range` 字段已记录每段覆盖区间，渲染时可直接标注，时间顺序与阶段边界得以
保留。

**已知新风险**（不做 YAGNI 处理，加监控）：摘要永不压缩 → 累积 → 摘要本身也算进
token → 越攒越易触发下次压缩而可压原文越少。量级估算：单摘要上限 1024 token
（配置 `compression_model_max_tokens`），实际约 500-800；阈值 80000。攒 10 个占 10%
无感，攒 50 个占 50% 压缩效率减半。**决策：只加 warning 日志**，摘要数超阈值时记录。
合并策略（分层折叠）等真实长会话数据出现后再设计，现在拍脑袋定不准。

### b1. 工具引用改为确定性附加

现状（`_post_process_summary`，`:415-472`）：扫描摘要中出现的 `tool_call_id`，还原成
`函数名(参数) → [REF::消息ID](N字符)`。

**脆弱点**：整条链依赖摘要 LLM 记得把 ID 写进去。docstring 自己写明"LLM 可能不会在
摘要中保留所有 tool_call_id……未匹配的信息丢失可接受"，代码只在匹配率 < 50% 时记
warning，不阻塞。

而 `tool_call_info` / `tool_result_refs` 两个映射**本来就是从原始消息完整扫出来的，
不依赖模型**，目前只用于文本替换。

**改法**：保留替换，同时把完整的工具调用 + 引用清单作为固定一节附在摘要末尾。
从"模型写了才有"变成"一定在"。改动小，但把可能完全丢失变成确定保留。

### b2. 压缩后重读在改的文件 —— 缓做

Claude Code 这条是**机制性必需**：压缩时 `readFileState.clear()`
（`compact.ts:518-522`），而 Edit 要求先 Read 过，不重读则压缩后第一个 Edit 必然失败。
它重读最近 5 个读过的文件（`POST_COMPACT_MAX_FILES_TO_RESTORE = 5`，单文件 ≤5000
token，总预算 50K）。

**本项目不构成必需**，因为多一条它没有的路：

- baseline 是**无状态内容指纹**：`base_{sha256[:20]}_{size}`
  （`file_tools.py:108-122`），服务端不存任何状态，随时可从文件重算
- 因此历史 baseline **不会过期**，只会"不再匹配"——而不匹配恰好证明文件真被改过
- 不匹配时报错直接给出行动指引："The file changed since it was observed;
  **read the current file before mutating**."（`file_tools.py:139-146`）

于是压缩后 agent 的路径是：看到 `[REF::xxx]` → 回查 → 拿到内容和当时 baseline →
文件没变则直接成功，变了则被拒并被告知重读。**路走得通，只是多花一两轮**。

**决策：缓做**。b1（保证有路）优先级高于 b2（让路更短）。真跑长任务发现费轮次再做。
若做，形态建议改为"优先重读本次会话 edit/write 过的文件"而非"最近读过的"——改过的
才是当前工作对象。

### c1. 用真实 token 替代字符估算 —— 做

实测偏差（讯飞，输入侧）：纯中文**低估 38%**。更关键的是估算只遍历消息内容，
**系统提示词、能力目录、工具 schema 完全算不到**——而这对专员很占地方。

天然对照（同模型，仅差一个工具定义）：

| | 提示词 | `input_tokens` |
|---|---|---|
| 普通调用 | "Reply with one word: ok"（23 字符） | 11 |
| 工具调用 | "What is the weather in Tokyo?"（29 字符）+ 一个工具 schema | **163** |

差出的 152 就是工具定义。星火同样：11 → 153。

`usage_metadata.input_tokens` 的语义正是"这次请求发出去的全部内容有多大"，即压缩要
判断的东西。与 `output_token_details.reasoning`（output 的子项）无关。

**已知滞后**：只能在请求返回后拿到，故压缩判断时手上是上一次请求的实际大小，滞后一轮。
用足够余量吸收即可——一轮增量最多是一个回复加几个工具结果。滞后一轮远好过整体偏低
38% 且漏算工具定义。

### c2. 阈值跟上下文窗口走 —— 缓做

**API 不提供窗口大小，已实测确认**：

| Provider | `/models` 返回 |
|---|---|
| GLM | `{"id","object","created","owned_by"}` —— 无任何窗口字段 |
| 讯飞 | `{"object":"list","data":[]}` —— 空 |

OpenAI 的 `/models` 规范本就无 `context_length`，各家照抄规范。仅 OpenRouter 类聚合
平台自行扩展。

余下三条路：硬编码对照表（模型更新即过时，GLM 列表里已有 glm-5/5.1/5.2；自建端点与
中转查不到）、故意撑爆看报错（浪费调用且格式不一）、**配置项手填**。

**决策：缓做**。当前单模型到底，把固定阈值调对即可。真做时形态为：配置项加窗口大小，
阈值按比例（如 0.7）算，不填则退回现固定阈值行为。

### d. 补四段摘要结构 —— 做

现有 5 段（`COMPRESSION_PROMPT`，`:94-133`）：关键决策 / 技术发现 / 当前进展 /
待确认事项 / 标识符清单。

对编码场景缺四段：

```
+ 本次任务的初衷（用户最初要什么，原样保留其原话）
+ 改动过的文件清单（只列路径 + 引用 ID，不放内容）
+ 试过但失败的路径（防重复踩坑）
+ 下一步（逐字引用，不转述）
```

最后一条抄 Claude Code，其注释给的理由是"确保任务解释不漂移"——转述一次偏一点，
压缩三次即跑偏。

**不照抄 9 段**：其"关键技术概念 / 问题解决 / 待办任务 / 当前工作"已被现有 5 段覆盖。

**注意现有 prompt 中一条对编码有害的规则**：

> 不需要保留：工具调用的原始数据（只保留分析结论）

对话场景成立，编码场景不成立（文件内容、报错堆栈、测试输出恰是关键）。但它与引用机制
配套：原始数据不进摘要，可按 ID 查回。**故问题不是"数据丢了"，而是"摘要里没留下线索
让 agent 知道该查哪个引用"**——摘要是索引，引用是详情，现在索引缺栏。补上四段即解决，
该规则本身保留。

### e. 引用替换作为压缩第一步 —— 做

**这是本节最有价值的一条**，它同时解决了旧机制的失败、替代了 microcompact，
并给出本项目版本的 context collapse。

#### 旧机制为什么失败：位置不对，不是机制不对

`reference_handler.py` 至今仍在，`context_manager.py:86` 仍在调用，但
`apply_replacements` 已被改成直通（`:31-46`），废弃理由写在 docstring：

> 旧实现会在**每次上下文组装时**按 size/steps 阈值把历史 tool result 重新替换为
> `REF::` 纯指针。该机制会让 search/fetch 等工具结果在 load_reference 后**再次被归档，
> 造成模型反复恢复同一引用**。Phase 1 先停用会话内替换。

配置仍在：`memory_reference_steps_threshold=3`、`memory_reference_size_threshold=10000`。

病根是**每次组装重算的视图变换**——不落库、无状态，故可无限循环。

对照 Claude Code 的 microcompact：它是**一次性改写**，内容换成
`[Old tool result content cleared]` 后落定，不会再被重新判定。**同一个机制，
一个能用一个死循环，差别只在这里。**

而压缩本身就是一次性持久化状态变更（`msg_repo.create` + `mark_archived`）。
把引用替换挪进压缩管线，天然不会重复判定。

#### 断死循环还需要一条硬规则

仅靠"一次性"不够，否则：

```
read_file 结果 → 替换成引用
  → 模型 load_reference 取回
  → 取回的内容成为 load_reference 的工具结果留在上下文
  → 下次压缩：这条也是个大工具结果 → 又被替换
  → 模型又去取
```

绕一圈仍是循环，只是变慢。故必须加：**`load_reference` 的返回结果永不被引用替换**。

这即 Claude Code 的 `frozen` 思路（`toolResultStorage.ts:643-645`：
"replacing content the model already saw unreplaced" 是不允许的）——模型主动要回来的
东西，系统不能再拿走。按工具名判定，确定性规则。

#### 放在第一步的收益

| | 引用替换 | LLM 摘要 |
|---|---|---|
| 消息结构 | **全部保留** | 糊成一段 |
| assistant 推理过程 | 原样在 | 被概括掉 |
| 时间顺序、因果 | 在 | 靠摘要复述 |
| 内容 | **可按 ID 取回** | 取不回 |
| 成本 | 零模型调用 | 一次调用 |

替换后重新测量，**若已降到阈值以下，整个 LLM 摘要不必发生** —— 上下文仍是完整的
消息序列，只是工具结果变成指针。这正是 collapse 注释说的 "keep granular context
instead of a single summary"，而本项目版本**比它更强：折叠内容可取回**。

#### 管线形态

```
压缩触发（阈值判断，用 c1 的真实 token）
   ↓
① 引用替换（零模型调用）
   · 范围：超出 keep_recent 窗口的工具结果
   · 阈值：复用现有 size_threshold（10000 字符）
   · 排除：load_reference 的返回结果，永不替换
   · 持久化：改写消息 + 归档原文，一次性落定
   ↓
   重新测量
   ↓
   已降到阈值以下？ ── 是 ──→ 结束，保住完整消息序列
   │
   否
   ↓
② LLM 结构化摘要（现有机制 + a / b1 / d 改进）
```

`reference_handler.py` 的代码与配置均在，改造量小于重写：把"组装时视图变换"改为
"压缩时持久化变更"，加 `load_reference` 排除规则。

### 1.3 定稿

| | 内容 | 结论 |
|---|---|---|
| a | 摘要不重压，分段累积 + 摘要数 warning | 做 |
| b1 | 工具引用确定性附加，不靠模型写 ID | 做 |
| b2 | 压缩后重读在改的文件 | 缓 |
| c1 | 真实 `input_tokens` 替代字符估算 + 预留扣减接口 | 做（依赖 1.1） |
| c2 | 阈值跟上下文窗口走 | 缓 |
| d | 补四段摘要结构 | 做 |
| **e** | **引用替换作为压缩第一步** | **做** |

---

## 1.4 单条消息工具结果总预算 —— 做

### 与现有 output governance 不是一回事

| | 现有 output governance | 1.4 |
|---|---|---|
| 判什么 | **单个**工具结果 | 一条消息内所有工具结果**加起来** |
| 时机 | 工具返回时（写入） | 每次组装请求前 |
| 超了 | 转 artifact + 引用 | 替换成预览 |
| 依据 | `visible_char_cap=12000`、`raw_reference_threshold=20000` | `applyToolResultBudget`（`toolResultStorage.ts:367+`） |

Claude Code 同一文件里两层都有：`maxResultSizeChars` + 落盘（≈ 本项目 output
governance），以及额外的 aggregate budget。

**场景真实存在**：一轮并发调 4 个工具，每个 11000 字符均未超单条上限，
加起来 44000 全进上下文。本项目支持 4 路并发工具执行。

### 现有数据（供预算取值参考，非做与不做的依据）

查 `data/mexemplar.db` 全部 144 条 assistant 消息：

| 并发度 | 次数 |
|---|---|
| 1 个工具 | 92 次（96%） |
| 2 个工具 | 4 次（4%） |
| 3-4 个 | 0 次 |

4 次并发的结果字符总和：1651 / 1651 / 9282 / **13205**。

**注意这批数据全是对话类任务**（待办、讨论），不代表编码任务的并发读文件模式。
故该数据只用于校准预算默认值，不作为"要不要做"的依据 —— 本条按机制价值直接实施。

### 选择策略：按大小降序，从最大的开始截

Claude Code 的做法（`toolResultStorage.ts:675-692`）：

```js
const sorted = [...fresh].sort((a, b) => b.size - a.size)   // 降序
for (const c of sorted) {
  if (remaining <= limit) break                              // 降到预算内即停
  selected.push(c)
  remaining -= c.size
}
```

**不是截最后一个**。例：4 个结果 500 / 30000 / 800 / 600，总和 31900 超预算——

- 截最后那个（600）→ 剩 31300 仍超，得继续截，最终仍要动那个 30000 的
- 截最大的（30000）→ 一刀降到 1900，另外三个完整保留

同样降到预算内，**截最大的动的条数最少**。且这批结果来自同一轮并发调用，不存在新旧
之分；最大的那个往往是全文读取（可只看摘要），小的常是精确查询结果（更该完整保留）。

### 它自带死循环的解法

`toolResultStorage.ts:643-662` 的状态记录：

- `mustReapply`：之前替换过的 → 重新套用**缓存下来的同一个替换结果**（幂等，
  前缀稳定不破缓存）
- `frozen`：模型已看过完整原文的 → **禁止再替换**

第二条尤其关键：模型看过的东西不能事后拿走，否则即是旧 `reference_handler` 那种
"清了又恢复、恢复了又清"。

且（`:669-673`）：若光 frozen 部分就超预算，**接受超支**，交给后续压缩——
宁可超支也不破坏"看过的不再改"这条规则。

### 定稿

```
· 范围：会被合并成同一条消息发出的那组工具结果（并发调用的一批）
· 触发：该组结果字符总和 > 预算
· 预算：24000 字符，走配置
· 选择：按大小降序，从最大的开始截，降到预算内即停
· 截成什么：预览 + 引用 ID（复用现有 artifact 机制，可取回）
· 幂等：同一个结果永远截成同一个字符串
· frozen：模型已看过完整原文的，禁止再截
· 超支：frozen 部分即超预算时接受超支，交给压缩
```

**预算取 24000 的理由**：语义为"允许两个满额结果（各 12000）并存，第三个开始截"。

取 12000（等于单条上限）会**惩罚并发**——每轮只允许一个结果完整存活，模型并发读 2 个
文件必有一个变预览、需多花一轮 `load_reference` 取回；这会把模型推向顺序调用（分 2 轮
各拿满 12000 反而不触发），而并发本身是好事。且历史最大值 13205 会被误伤，
那约 4400 token 实际不构成压力。

24000 既保住并发价值，又挡住 4 路全满额（48000）这类真正的极端。配置项，改错代价低。

---

## 附录：已排除的疑似问题

### `pending_dispatch` 根容器 —— 误报

数据库中 2 个任务停在 `pending_dispatch`，曾疑为调度器故障。实为**正常状态**，
`reentry_briefing.py:204-208` 注释写明：

> 根容器节点（parent_task_id is None，标题 "Assistant request"）代表整个用户请求，
> **在图收口前永远停在 pending_dispatch**。把它算进进度会输出
> "completed=0, running=1, pending=1, 就绪可派节点：Assistant request"，
> 误导主助理以为还有节点在跑。

统计与调度判定均只看 `parent_task_id is not None` 的真实执行节点，与
`graph_scheduler._advance` 一致。

**遗留未解**：这两张图只有根容器、无真实执行节点、0 条边，说明 `delegate_task` 未建出
子任务。原因已无法追溯——`unified dispatch failed` 错误日志不存在（说明 except 分支
未触发），而对应时段（2026-07-13 02:02 UTC）sidecar 日志完全空白。9 天前的事，且可能
是当时版本行为。**结论：不考古，改为跑一次真实任务验证当前链路**。

# Phase 1 数据模型：外部 Coding 可靠性修复

**Date**: 2026-07-21

本特性不新增持久化实体或表。SQLite v33 在既有 `external_coding_attempts` 上增加三个
内部恢复字段，用来让进程 ownership 跨 sidecar 重启保持 fail-closed；公开 DTO、事件与
配置契约不变。

---

## 值概念 1：目标仓库位置（Target Repository Location）

外部 coding session 要作用于哪个代码仓库。

### 来源

由调用方（持有"外部 Coding"能力组合的固定执行专员）在启动时显式提供。
不从任何隐含来源推导。

### 验证规则

按顺序校验，任一不通过即拒绝，且**不产生任何副作用**：

| 序 | 规则 | 不通过时 |
|---|---|---|
| 1 | MUST 非空 | 拒绝，说明缺少目标仓库 |
| 2 | 路径 MUST 存在 | 拒绝，说明位置不存在 |
| 3 | MUST 是一个可用的 git 仓库（HEAD 可解析） | 拒绝，说明该位置不是可用仓库 |

**明确不做的校验**：不禁止该位置指向 Exemplar 自身仓库。以 Exemplar 为目标是正当用途，
本特性消除的是"未指明时滑向 Exemplar"，而非"指向 Exemplar"本身。

### 变更前后对比

| | 变更前 | 变更后 |
|---|---|---|
| 参数必填性 | 选填 | **必填** |
| 缺失时行为 | 静默回退到进程当前工作目录（即 Exemplar 仓库） | **拒绝** |
| 无效时行为 | 底层异常上抛 | 返回可行动说明，不透出异常文本 |

---

## 值概念 2：隔离工作区位置（Isolation Worktree Location）

每个 coding session 独占的 git worktree 落盘位置。

### 派生规则

由配置项 `external_coding.worktree_root`（默认 `.worktrees/coding`）与 coding session 标识派生：

| 配置形态 | 展开基准 | 结果 |
|---|---|---|
| 相对路径（默认） | **目标仓库位置** | `<目标仓库>/<worktree_root>/<coding_session_id>` |
| 绝对路径 | 不展开 | `<worktree_root>/<coding_session_id>` |

**变更点**：相对路径的展开基准由「进程当前工作目录」改为「目标仓库位置」。
配置键名与默认值均不变，改变的是解释方式——属行为语义变更，需同步活文档。

### 不变量

- 隔离工作区 MUST 与目标工作区物理隔离（既有约束，不变）
- 同一 coding session 的工作区位置在其生命周期内不变（既有行为，不变）

---

## 值概念 3：Artifact 绝对路径集（Artifact Absolute Path Set）

`artifact_dir`、`handoff_path`、`plan_path`、`result_path` 与每次 attempt prompt 均属于同一
session 的路径集。配置的 artifact 根若为相对路径，先以 sidecar 当前工作目录展开为绝对根；
之后只持久化绝对路径。`ExternalCodingSessionRepository.create_session()` 将 plan/result 设为
必填非空参数，数据库列为兼容既有 schema 仍可空，但 035 后的新行不能表达半初始化状态；
通用 `update_session` 不允许再修改 plan/result，路径集在首次持久化后保持不可变。

---

## 值概念 4：持久进程身份（Durable Process Identity）

running attempt 的业务事实不能只依赖进程内 registry 或私有状态文件。v33 新增：

| 字段 | 类型 / 默认值 | 规则 |
|---|---|---|
| `process_create_time` | nullable REAL | 与 `pid` 组合成可跨重启验证的身份；无法取得时为 NULL，恢复路径保持 fail-closed |
| `termination_unconfirmed` | BOOLEAN NOT NULL DEFAULT 0 | running reservation / running result 写 true；只有确定 terminal observation 或三态 stop 的 confirmed 结果写 false |
| `launch_started` | BOOLEAN NOT NULL DEFAULT 0 | reservation 初始为 false；调用 adapter 前先持久化 true，用于区分可安全恢复的 pre-spawn reservation 与 ownership 不完整的已启动进程 |

旧 running 行迁移为 `NULL/true/true`：缺少创建时间意味着 ownership 无法验证，必须从升级
时刻起 fail-closed；旧 terminal 行迁移为 `NULL/false/true`。两类旧行都不会被误判为从未
启动。三个字段只由 `ExternalCodingSessionRepository` 读写，不进入 attempt 的公开 serializer。

`uq_external_coding_attempts_active_session` 是 `status='running'` 的 partial unique index，
以数据库约束保证每个 coding session 至多一个 active attempt；service 的预检只负责
提供清晰错误，不作为并发硬保证。

ownership 还受同一组跨字段不变量约束：running 必须
`termination_unconfirmed=true`，terminal 必须为 false；`launch_started=false` 时 PID 与
创建时间必须为空；创建时间非空时 PID 必须非空。domain result/snapshot 只校验其携带的
status/ownership 与 PID/创建时间组合；它们没有 `launch_started`，不能宣称守住 pre-spawn。
Repository 校验完整 attempt 合并态；ORM check constraints 约束新 schema，v33 的幂等
INSERT/UPDATE triggers 为既有 SQLite 表补同等 row guard。`launch_started` 只由专用 CAS 置 true，
从通用 Repository 更新面移除，UPDATE trigger 另比较 OLD/NEW 拒绝 true→false。显式矛盾值
必须报错，不允许 Repository 静默“纠正”。

### 身份与恢复规则

1. PID 只有同时匹配持久化创建时间时，重启后的 runner 才能认领或终止该系统进程；
   PID 复用或创建时间缺失不得猜测。
2. 私有状态文件的确定终态只有在 PID + 创建时间匹配 durable identity 时才可清除 ownership；
   普通 running、状态文件缺失/损坏或身份冲突不能覆盖数据库里的
   `termination_unconfirmed=true`。durable 创建时间为 NULL 时，状态文件携带的创建时间不得
   反向写回数据库；否则下一次 poll 会把未验证元数据“洗白”为可信身份。
3. 状态文件标记了 termination unconfirmed 且 PID 身份仍匹配时，后续 stop 必须再次尝试
   终止，而不是因旧 marker 直接放弃。
4. 父 PID 已退出但先前未确认整棵进程树终止时，系统无法证明 descendants 已消失，故仍
   保持 running 并禁止 resume。
5. headless / interactive monitor 共用一个顶层守护 wrapper；stdout/stderr reader 的读取异常
   必须以独立信号进入该 wrapper，不能伪装成 EOF；reader 发出的 EOF/失败 sentinel 是 stream
   完成的权威事实，进程退出与 queue 瞬时为空不能替代。任意未预期异常先尝试有界终止，
   再写安全终态或 unconfirmed marker。两条写入都失败时，数据库 running guard 与进程内
   registry 至少保留一条恢复路径。
6. 进程内 registry 键包含 PID、创建时间、状态路径与实例令牌；lookup 同时验证 durable
   identity 和状态路径，删除使用对象 CAS，旧 monitor 的迟到清理不能删除 PID 复用后的 owner。
   PID 注册碰撞后的补偿终止若失败，新 owner 以独立键保留，旧、新 owner 的 poll/stop/清理
   互不串扰。
7. monitor 已确认进程退出但 terminal marker 首写失败时，内存 owner 保留安全终态 payload；
   后续 poll 只有重试落盘成功才返回该终态并释放 registry，重试失败继续保留 owner。输出
   reader 的 queue put 可由 monitor cancel，避免提前退出后后台线程永久阻塞在满队列。

---

## 启动流程的失败分支

本特性关注的是失败路径的确定性，故在此明确各分支的终态与残留要求。

```
启动请求
  │
  ├─ 目标仓库缺失 ──────────→ 拒绝｜零残留
  ├─ 目标仓库不存在 ────────→ 拒绝｜零残留
  ├─ 目标仓库非可用仓库 ────→ 拒绝｜零残留
  │
  ├─ 校验通过
  │    │
  │    ├─ artifact / handoff 创建失败 ─→ 拒绝｜进入同一补偿边界
  │    │
  │    ├─ 创建隔离工作区失败 ─→ 拒绝｜回收部分 worktree / 分支 / artifact 后零残留
  │    │
  │    ├─ 工作区已创建
  │    │    │
  │    │    └─ 会话记录写入失败 ─→ 拒绝｜**回收已创建的工作区**后零残留
  │    │
  │    └─ 全部成功 ───────────→ 进入既有 plan 阶段流程（不变）
```

### 零残留的定义

补偿成功后的拒绝，以下四者 MUST 均不存在：

1. 目标仓库下的隔离 worktree 目录
2. 对应的 git 分支
3. `external_coding_sessions` 中的会话行
4. 本次启动为该 session id 新建的 artifact 目录

会话首次写入同时携带 `plan_path` / `result_path`，避免“create 成功、随后 update 失败”
形成半初始化行。工作区创建部分失败或会话首次写入失败时，启动补偿路径同时清理生成的
worktree、`coding/<session-id>` 分支与本次 artifact；预先存在的共享根目录不得被删除。
Git 或文件系统自身拒绝删除时，补偿器必须继续尝试其余资源、验证最终状态，并返回包含
session 标识但不含底层异常原文的 cleanup-incomplete；此时不得把失败描述成“零残留”。
首次 session 写入抛错且回读也无法判断提交结果时同样保留资源，不做可能破坏已提交行的
猜测性清理；安全错误携带预生成 session 标识，供后续恢复与人工定位。安全日志以该 id 关联
create/lookup 两个异常类型，不记录异常正文、资源路径或堆栈。

### Attempt 启动不变量

1. 先创建 durable running reservation，再写 attempt prompt、启动 CLI
2. reservation 以 `termination_unconfirmed=true, launch_started=false` 起步；写 prompt 与
   adapter object construction 成功后、调用 adapter start 前以
   `attempt_id + status=running + launch_started=false` 单条 CAS 取得启动权并持久化
   `launch_started=true`。factory 失败仍按 pre-spawn 关单；CAS 未命中说明并发关单已获胜，
   必须在 spawn 前中止；`launch_started` 此后不得通过 Repository 或原始 SQL 回退；
   `Popen` 后尽快持久化 PID + 创建时间。
   任何初始化失败先停止进程树；仅“确认已停止 / 确认先前退出”可移除 registry 并清标记，
   “无法确认”必须保留 registry 与 durable identity
3. 启动结果落库失败先停止 PID；若无法证明已停止，attempt/session 保持非终态；若 PID
   ownership 补写也失败，启动调用显式失败
4. `poll` 抛错只是观测不确定，attempt 保持 running，禁止 resume，后续 refresh 重试
5. failed/interrupted 的 session 与 attempt 终态在 Repository 同一事务提交；任一写入失败
   两行一起回滚，durable attempt 仍为 running，下一次 refresh 可重试。成功 attempt 终态
   与随后 PLAN/RESULT 校验保留为可重试的两步投影。abandon、plan 协议违规等显式 stop
   同样必须原子投影，不得先关 attempt 再另行提交 session
6. stop 结果使用三态值而不是 bool；service 不以普通 poll snapshot 猜测进程树退出证明
7. monitor 任意异常不得裸退出线程；守护恢复失败时继续保留 running ownership
8. 同一 session 的第二个 running reservation 由 partial unique index 拒绝；pre-spawn 关单
   首次失败可借 `launch_started=false` 在 refresh/resume 安全补关，true 且身份不全则继续
   fail-closed
9. 所有基于 running observation 的更新带 `expected_status='running'` 条件 CAS；先到的 terminal
   写入获胜后，迟到 running/terminal 观测只能读取权威当前行，不能复活 attempt、清除
   `finished_at` 或覆盖并发结果。Repository 对未知投影字段立即报错，避免拼写错误静默丢失
10. reader 读取失败与进程正常 EOF 分型；wait 超时补偿复用整棵进程树的三态终止证明，
    不得只 kill 父 PID 后投影 terminal

---

## 不变的部分

明确记录以避免实现时误改：

- `external_coding_sessions` 表结构；attempt 仅增加 ownership 字段、单活索引和跨字段 guards
- session 状态机与 plan / implement 两阶段协议
- 合并前冲突分析、回滚计划生成
- 能力组合授权链（固定专员 / 已配组合 / 正式任务 / 组合已发布 四重限定）
- session 与 owner 的绑定关系

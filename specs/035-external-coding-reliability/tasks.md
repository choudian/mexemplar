---

description: "Task list for 外部 Coding 可靠性修复"
---

# Tasks: 外部 Coding 可靠性修复

**Input**: Design documents from `/specs/035-external-coding-reliability/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: 包含测试任务。依据：spec CC-005 与 SC-005 要求测试覆盖不减少，
constitution 原则 IV 要求静默失败风险路径必须有自动化测试，
且本特性修复的正是两条静默失败路径——测试是交付主体而非附属。按 TDD 先写测试后实现。

**Organization**: 按用户故事分组。US1 与 US2 触及的源文件与测试文件**完全不重叠**，可全程并行。

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属用户故事（US1 / US2）

## Project Paths

- **Python source**: `src/`（本特性仅触及 `src/business/`）
- **Python tests**: `tests/business/external_coding/`
- **Test runner**: `uv run python -m pytest`
- **Formatter/linter**: `uv run black src/ tests/`、`uv run flake8 src/ tests/`

---

## Phase 1: Setup

**Purpose**: 固定回归基线，供交付时对比

- [X] T001 记录变更前测试基线：执行 `uv run python -m pytest tests/business/external_coding tests/guardrails/test_external_coding_guardrails.py tests/guardrails/test_external_coding_composition_scope.py tests/integration/test_external_coding_closed_loop.py tests/data/test_external_coding_session_repository.py tests/data/test_external_coding_baseline_migration.py tests/desktop_api/test_external_coding_sessions_api.py tests/desktop_api/test_external_coding_ui_event.py tests/execution/test_external_coding_quota.py -q`，把通过数量记入 `specs/035-external-coding-reliability/quickstart.md` 的执行记录栏（变更前实测为 119 passed，用于 T014 对比）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 验证 research.md 决策 4 的前提。前提不成立则落盘规则变更需要迁移方案，必须暂停重评估

- [X] T002 验证 `external_coding_sessions` 与 `external_coding_attempts` 两表均为 0 行（查询 `data/mexemplar.db`）。若任一表非空，**停止执行后续任务**，回到 research.md 决策 4 补充历史 worktree 的迁移或兼容方案后再继续

**Checkpoint**: 前提成立后，US1 与 US2 可并行开工

---

## Phase 3: User Story 1 - 干活的仓库不会被搞错 (Priority: P1) 🎯 MVP

**Goal**: 目标仓库说不清就拒绝，绝不默认落到 Exemplar 自身；隔离工作区随目标仓库落盘

**Independent Test**: 发起一次不指明目标仓库的启动，确认被拒且系统零残留；
再发起一次指明外部仓库的，确认工作区与分支全部落在该仓库内

### 测试先行

- [X] T003 [US1] 新建 `tests/business/external_coding/test_target_repository_required.py`，覆盖六类场景并确认此刻全部失败：(a) 未提供目标仓库 → 拒绝且无 worktree、无分支、无 `external_coding_sessions` 行；(b) 目标位置不存在 → 拒绝且错误文案可行动、不含底层异常文本；(c) 目标位置存在但非 git 仓库 → 同上；(d) 目标仓库无任何提交致 HEAD 不可解析 → 同上；(e) 合法外部仓库 + 默认相对 worktree 根 → 隔离 worktree 落在该仓库下且 Exemplar 不新增 worktree/分支；artifact 仍服从既有配置根；(f) 显式指向 Exemplar 自身仓库 → **放行**，不得因指向自身而拒绝。另断言 `start_external_coding_session` 的 schema 中 `targetWorktreePath` 位于 `required`

### 实现

- [X] T004 [US1] 在 `src/business/external_coding/service.py` 删除 `target_worktree_path or Path.cwd()` 兜底（约第 144 行），改为缺失即抛出可行动错误；按 data-model.md 的顺序补齐存在性与 git 仓库可用性校验，错误文案不得透出原始异常、堆栈或内部路径
- [X] T005 [US1] 在 `src/business/external_coding/service.py` 调整隔离工作区落盘基准（约第 150-152 行）：配置 `external_coding.worktree_root` 为相对路径时以目标仓库为基准展开，为绝对路径时原样使用；保持既有"会话行写入失败时回收已创建 worktree"的零残留行为
- [X] T006 [P] [US1] 在 `src/business/agents/tools/external_coding_tools.py` 将 `targetWorktreePath` 移入 `required`（约第 36-38 行），并按 `contracts/start-external-coding-session.md` 改写其 description：绝对路径、必须是可用 git 仓库、不填即拒、指向 Exemplar 自身也需显式写出。填参约束只写在 schema description，不得写入主助理系统提示词
- [X] T007 [US1] 执行 `uv run python -m pytest tests/business/external_coding/test_target_repository_required.py -q`，确认 T003 的六类场景全部转绿

**Checkpoint**: US1 独立可交付。此时风险敞口已关闭，即可作为 MVP 停下

---

## Phase 4: User Story 2 - 换哪个外部工具结果一样可靠 (Priority: P2)

**Goal**: 任务书必须真正送达 codex，而非只给一个存放位置

**Independent Test**: 分别构造两个工具的启动指令，确认都含明确的任务书获取指示

**与 US1 的关系**: 完全独立。触及的源文件（`cli_adapters.py`）与测试文件
（`test_external_coding_tools.py`）均与 US1 不重叠，可同时进行

### 测试先行

- [X] T008 [US2] 在 `tests/business/external_coding/test_external_coding_tools.py` 扩充命令构造断言并确认此刻失败：codex 分支的提示词参数不含裸 `@` 前缀且含明确读取指示；Claude Code 分支保持 `@` 引用写法不变；两条断言覆盖 plan、implement、resume 三种情形

### 实现

- [X] T009 [US2] 在 `src/business/external_coding/cli_adapters.py` 将 codex 分支的 `f"@{prompt_path}"`（约第 193 行）改为带动词的明确指示（`Follow the instructions in this file: <path>`）；Claude Code 分支（约第 152 行）保持不变，并在该行补注释说明其有效性依赖 CLI 的 background prefetch 机制、加 `--bare` 会使其静默失效（FR-009）
- [X] T010 [US2] 执行 `uv run python -m pytest tests/business/external_coding/test_external_coding_tools.py -q`，确认 T008 的断言全部转绿

**Checkpoint**: US2 独立可交付

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T011 [P] 在 `docs/PROJECT_CONSTRAINTS.md` 的外部 coding 约束段（约第 82-91 行区域）新增两条：启动外部 coding session 必须显式指明目标仓库、缺失即 fail-closed 且零残留；`external_coding.worktree_root` 为相对路径时以目标仓库为基准展开（键名与默认值不变，改变的是解释方式）
- [X] T012 [P] 同步更新 `src/AGENTS.md`、`src/CLAUDE.md`、`src/GEMINI.md` 三份镜像的外部 coding 约束条目，内容与 T011 一致；三份文件必须保持同内容（改完用 md5 校验一致性）
- [X] T013 [P] 执行 `uv run black src/ tests/` 与 `uv run flake8 src/ tests/`，修正本特性引入的格式与静态检查问题
- [X] T014 执行 T001 的同一条全量回归命令，确认全绿且通过数量不少于 T001 记录的基线（SC-005）
- [X] T015 按 `quickstart.md` 第 4 步执行真实行为确认：准备一个 Exemplar 之外的 git 仓库作为目标，实际派一次极小改动任务，逐条核对 4.3 与 4.4 的确认项，并把结果（日期、所选 CLI、各项结果、任何跳过项及原因）回填至 quickstart.md 的执行记录栏。**此任务不可省略**——030 的同类人工验证从未执行，正是 codex 任务书未送达问题长期未被发现的原因

---

## Phase 6: Verification Remediation

**Purpose**: 修复第一轮 `/speckit.verify.run all` 与 T015 真实运行暴露的中级及以上问题

- [X] T016 [US1] 在 `tests/business/external_coding/test_target_repository_required.py` 补充部分 worktree 创建失败与 session 首次持久化失败场景，断言 worktree、生成分支、session 行和本次 artifact 全部零残留，且共享根目录不被误删
- [X] T017 [US1] 在 `src/business/external_coding/service.py`、`src/business/external_coding/git_ops.py` 与 `src/data/repos/external_coding_session_repository.py` 实现启动补偿：安全错误不透出 Git 原文，删除生成分支，清理本次 artifact，并让 plan/result 路径随 session 首次写入原子保存
- [X] T018 [US2] 在 `src/business/external_coding/cli_adapters.py` 与 `src/execution/external_coding_process.py` 修复当前 CLI 运行时契约：Windows PATH/PATHEXT 无 shell 解析、Claude stream-json verbosity、Codex resume 父参数顺序、Codex headless `-o` 阶段 artifact 与句中绝对路径脱敏
- [X] T019 [US2] 在 `tests/business/external_coding/test_cli_adapters.py` 与 `tests/business/external_coding/test_external_coding_tools.py` 固化上述命令语法、阶段输出、shim 解析与脱敏契约，并重跑完整 external coding 回归
- [X] T020 按 `quickstart.md` 重跑真实 Codex 生产路径，必须使用默认命令名 `codex`，进入 `plan_ready`、生成含精确目标的有效 `PLAN.md`、命令摘要路径脱敏且 Exemplar 状态前后不变；同步更新 spec/plan/data-model/tasks/quickstart 与活文档

---

## Phase 7: Review Remediation

**Purpose**: 修复首轮 `/speckit.review.run all` 六个专项发现的中高等级原子性、测试与文档问题

- [X] T021 [US1] 将相对 artifact 根在 session 创建入口绝对化，并让 handoff/plan/result/prompt 全链持久化绝对路径；补外部目标仓库行为测试
- [X] T022 [US1] 把 artifact/handoff、worktree/分支和首次 session 写入纳入单一启动补偿边界；Git 删除检查返回码和最终注册/ref 状态，cleanup 失败显式返回 session 标识
- [X] T023 [US2] 为 `ExternalCodingProcessRunner.start()` 增加 Popen 后初始化补偿，确保状态写入或 monitor 启动失败会停进程并清 registry，无法停止时保留 PID 管理权
- [X] T024 [US2] attempt 改为先持久化 reservation 再 spawn；结果落库失败先停进程，poll 异常保持 running 并禁止并发 resume
- [X] T025 将 Repository 的 plan/result 首次写入参数收紧为必填非空，并更新所有直接构造夹具
- [X] T026 补 linked worktree、相对 artifact、部分写入、Git 非零、Popen 接线/初始化、attempt 落库与 poll 异常的故障注入测试
- [X] T027 同步修正 research 的 CLI 初判、spec/plan/data-model、活文档与三份模块 AI 镜像
- [X] T028 重跑 external coding 全量回归、flake8、变更文件 Black、diff/check 与镜像哈希，并回填 quickstart

---

## Phase 8: Second Verification Remediation

**Purpose**: 修复第二轮 `/speckit.verify.run all` 的进程树确认与规格口径问题

- [X] T029 [US2] 让 PID/tree 终止 helper 在 terminate 后 kill 并二次 wait，只有所有已观测父子进程消失才返回成功；补真实 parent + child 进程行为测试
- [X] T030 [US1] 统一 spec/SC/tasks 对默认相对 worktree 根、绝对 worktree 根与中央 artifact 根的口径，并修正 plan 的受影响层描述
- [X] T031 重跑 CLI runner 定点测试、external coding 全量回归与静态门槛，回填 quickstart

---

## Phase 9: Second Review Remediation

**Purpose**: 修复第二轮 `/speckit.review.run all` 的终止证明、状态投影、脱敏与类型不变量问题

- [X] T032 [US2] 将 process stop 升级为“确认已停止 / 确认先前退出 / 无法确认”三态；monitor/startup 在终止未确认时持久化 `terminationUnconfirmed`、保持 registry/running，并补初始化与运行期故障注入测试
- [X] T033 [US2] 统一所有 CLI 启动异常分支的 command summary 脱敏；禁止首次持久化后通过通用 Repository API 修改 plan/result artifact 路径，并补测试
- [X] T034 [US2] 收敛 session/attempt 终态投影顺序（T042 进一步升级为单事务）；移除 service 用普通 poll 猜测 stop 成功的路径；PID ownership 补写失败改为显式失败，并补重试/静默失败测试
- [X] T035 重跑 external coding 全量回归、flake8、变更文件 Black、核心编译、diff check 与 AI 三镜像校验，回填 quickstart

---

## Phase 10: Third Review Remediation

**Purpose**: 修复第三轮 `/speckit.review.run all` 发现的跨 sidecar 重启 ownership 与 monitor
线程静默退出缺口

- [X] T036 [US2] 增加 SQLite v33：在 `external_coding_attempts` 持久化
  `process_create_time` / `termination_unconfirmed`，贯穿 model、Repository、domain result、
  adapter 与 service；字段不得进入公开 DTO/event
- [X] T037 [US2] 让 runner 以 PID + 创建时间验证重启后的进程身份；旧 unconfirmed marker
  不阻断对匹配存活 PID 的再次 stop，父进程消失、PID 复用、身份缺失或冲突继续 fail-closed
- [X] T038 [US2] 用单一 guarded monitor wrapper 收口 headless / interactive 未预期异常；终止、
  marker 或 terminal status 写入失败时保留 registry 与 durable running ownership
- [X] T039 补 v33 幂等升级/回退、状态与 marker 双写失败、跨重启 stop、父进程消失及 monitor
  恢复故障注入测试；重跑 external coding 扩大范围、静态门槛、核心编译、diff check、活文档与
  AI 三镜像校验，并回填 quickstart

---

## Phase 11: Fourth Review Remediation

**Purpose**: 修复第四轮 `/speckit.review.run all` 发现的 PID 复用、终态身份与跨表事务缺口

- [X] T040 [US2] 将进程 registry 升级为完整身份 + 状态路径键；注册碰撞先补偿新进程，
  lookup 校验 durable identity，所有 monitor/stop 清理使用对象 CAS
- [X] T041 [US2] terminal 状态文件只有匹配 durable PID + 创建时间才可投影；冲突或缺失
  保持 running/unconfirmed，并补 PID 与创建时间冲突测试
- [X] T042 [US2] 将 failed/interrupted attempt 与 session 投影收为 Repository 单事务；
  terminal 强制清除 unconfirmed，提交失败统一 rollback
- [X] T043 [US2] v33 增加 `launch_started` 与每 session 单 running attempt partial unique index；
  调用 adapter 前持久化 spawn 边界，pre-spawn 关单失败可恢复，已启动身份不全继续 fail-closed
- [X] T044 补 PID 复用覆盖/迟到删除、原子回滚、重复 active attempt、terminal 类型不变量及
  pre-spawn reservation 恢复测试；同步 spec/plan/data model/约束与 AI 三镜像

---

## Phase 12: Fifth Review Remediation

**Purpose**: 修复第五轮 `/speckit.review.run all` 发现的旧数据 ownership、迟到观测、
显式 stop 原子性与后台 reader 生命周期缺口

- [X] T045 [US2] v33 将既有 running attempt 回填 `termination_unconfirmed=true`；重启后
  durable 创建时间缺失时拒绝 terminal marker，且状态文件中的创建时间不得在连续 refresh
  中反向补成 durable identity
- [X] T046 [US2] monitor 已确认退出但 terminal 首写失败时，由后续 poll 重放安全终态并释放
  registry；输出 reader 的满队列 put 支持 cancel，monitor 提前结束后不泄漏后台线程
- [X] T047 [US2] abandon 与 plan 协议违规等显式 stop 将 session/attempt 终态放入同一
  Repository 事务；提交失败两行一起回滚并可再次重试
- [X] T048 [US2] running poll/stop 投影统一使用 expected-status CAS；terminal 状态不可复活，
  stale running 观测不得清除 `finished_at`，未知投影字段显式拒绝
- [X] T049 [US2] PID 注册碰撞后的补偿终止若失败，同时保留旧、新完整 owner；对象 CAS、
  poll 与 stop 按身份/状态路径隔离，不互相覆盖、误删或误终止
- [X] T050 补旧行迁移、缺失创建时间双 refresh、terminal 重放、reader 取消、显式 stop
  原子失败、stale CAS 与碰撞补偿失败测试；同步 spec/plan/data model/架构/约束与 AI 三镜像，
  并执行扩大范围回归和静态门槛

---

## Phase 13: Sixth Verify Remediation

**Purpose**: 修复第六轮 `/speckit.verify.run all` 发现的 terminal 重放二次失败恢复缺口

- [X] T051 [US2] monitor recovery terminal payload 的 poll 重写若再次失败，保持 running 与
  registry owner，不得提前释放最后恢复路径；只有 marker 真正落盘后才返回 terminal 并以
  对象 CAS 清理 owner。强化连续两次写失败、第三次成功的行为测试并重跑扩大范围门槛

---

## Phase 14: Sixth Review Remediation

**Purpose**: 修复第六轮 `/speckit.review.run all` 发现的 reservation→spawn 竞态、reader
错误吞没、恢复标识、Git 错误分类与 attempt 跨字段不变量缺口

- [X] T052 [US2] 将 `launch_started=false→true` 改为同时约束 running 状态的 Repository CAS；
  CAS 未命中必须在 adapter 前中止，并补 abandon 精确插入 reservation/launch 间隙的并发测试
- [X] T053 [US2] 让 stdout/stderr reader 将读取异常作为独立故障信号交给 guarded monitor；
  wait 超时补偿统一终止并确认整棵进程树，补读取异常不被当成 EOF 的故障注入测试
- [X] T054 [US1] 目标分支 probe 只将 `GitOperationError` 分类为安全仓库状态故障，未知异常继续
  上抛；session 首次写入结果和回读均未知时保留资源并返回预生成 session id，补两类测试
- [X] T055 [US2] 由 domain result/snapshot enforce 其可见的 running/terminal ownership 与
  PID/创建时间组合，由 Repository、ORM check constraints 与 v33 幂等 insert/update triggers
  额外 enforce pre-spawn identity；显式矛盾更新不得自动修正，并补 Repository/迁移/类型测试
- [X] T056 同步 spec/plan/data-model/research/quickstart、架构/约束与 src 三份 AI 镜像；修正
  “明确文件读取指示减少工具往返”与“无需迁移方案”的过宽表述
- [X] T057 重跑 external coding 扩大范围、全仓 flake8、相关 Black、核心编译、diff check 与
  AI 三镜像哈希，并将实际结果回填 quickstart

---

## Phase 15: Seventh Review Remediation

**Purpose**: 修复第七轮 `/speckit.review.run all` 发现的 reader 完成竞态、adapter factory
边界、Git/恢复诊断、spawn 单向事实与文档契约偏差

- [X] T058 [US2] 删除“进程已退出 + queue 瞬时为空即 stream 完成”捷径，以 reader EOF/失败
  sentinel 为权威；补进程先退出、reader 延迟抛错仍进入 guarded recovery 的确定性线程测试
- [X] T059 [US2] 将 adapter object construction 移到 launch CAS 前并纳入 pre-spawn 关单；
  补 factory 抛错后 attempt 为 terminal/unlaunched、无 PID、无 active slot 的测试
- [X] T060 [US1] 用 `GitProcessError` 安全归一化 timeout/OSError；HEAD 只转换预期 Git 异常，
  未知异常继续传播；首写/回读双失败日志记录 session id 与两次异常类型但不记录正文/路径
- [X] T061 [US2] 从通用 Repository mutable fields 移除 `launch_started`，v33 UPDATE trigger
  拒绝 true→false；补 Repository 回退拒绝及原始 SQL UPDATE guard/事务回滚测试
- [X] T062 修正 spec/data-model/活文档对 domain 与 pre-spawn guard 的过度承诺，并同步
  plan/quickstart/架构/约束/src 三份 AI 镜像
- [X] T063 重跑 external coding 扩大范围、全仓 flake8、相关 Black、核心编译、diff check、
  AI 三镜像哈希并回填 quickstart

---

## Dependencies & Execution Order

```
T001 (基线)
  └─ T002 (前提验证) ── 前提不成立则停止
       │
       ├─────────────────┬─────────────────┐
       ▼                 ▼                 │
   US1 (P1)          US2 (P2)              │  两个故事可完全并行
   T003 测试          T008 测试             │
     ▼                 ▼                   │
   T004 ─▶ T005       T009                 │
   T006 [P]            ▼                   │
     ▼               T010 验证              │
   T007 验证                                │
       │                 │                 │
       └────────┬────────┘                 │
                ▼                          │
        T011 [P] T012 [P] T013 [P]  ◀──────┘
                ▼
              T014 (全量回归)
                ▼
              T015 (真实验证，必做)
                ▼
        T016~T019 (verify 修复)
                ▼
              T020 (真实复验)
                ▼
        T021~T028 (首轮 review 修复)
                ▼
        T029~T031 (第二轮 verify 修复)
                ▼
        T032~T035 (第二轮 review 修复)
                ▼
        T036~T039 (第三轮 review 修复)
                ▼
        T040~T044 (第四轮 review 修复)
                ▼
         T045~T050 (第五轮 review 修复)
                 ▼
               T051 (第六轮 verify 修复)
                 ▼
         T052~T057 (第六轮 review 修复)
                 ▼
         T058~T063 (第七轮 review 修复)
```

**故事内部依赖**：

- US1：T003 → T004 → T005 → T007；T006 可与 T004/T005 并行（不同文件）
- US2：T008 → T009 → T010（同一文件链，全串行）

**故事间依赖**：无。US1 与 US2 触及文件零重叠

---

## Parallel Execution Opportunities

| 并行组 | 任务 | 前提 |
|---|---|---|
| 两个用户故事 | US1 全部 ∥ US2 全部 | T002 通过 |
| US1 内部 | T006 ∥ (T004 → T005) | T003 完成 |
| Polish 文档 | T011 ∥ T012 ∥ T013 | 两个故事实现完成 |

**不可并行**：T004 与 T005 同改 `service.py`；T014 必须在初始实现之后；T015 在 T014 之后；
T020 必须在 T016~T019 与修复后的完整回归之后

---

## Implementation Strategy

### MVP 范围（建议的第一个可交付切片）

**Phase 1 + Phase 2 + Phase 3（US1）** = T001~T007。

完成即关闭"默认改 Exemplar 自己"这一唯一会造成实际损失的风险，此时可以停下来验收。
US2 修的是可靠性不一致，不会改错东西，往后放安全。

### 增量交付

1. T001~T002：确认基线与前提 → 可随时中止且无副作用
2. T003~T007：US1 完成 → **风险关闭，可交付**
3. T008~T010：US2 完成 → 两条 CLI 路径可靠性拉齐
4. T011~T015：文档同步、回归、真实验证 → 完整交付
5. T016~T063：verify/review 交替质量门槛与修复 → 失败路径、单向原子状态、后台资源与跨重启 ownership 闭环

### 关于 T015 的执行时机

T015 需要真实运行外部 CLI。若当下不便执行，**MUST 在 quickstart.md 的执行记录栏写明跳过原因**，
不得默认视为通过，也不得在交付说明中把"真实行为已验证"写成事实。

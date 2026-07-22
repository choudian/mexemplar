# Quickstart 验证：外部 Coding 可靠性修复

**Date**: 2026-07-21

按顺序执行。前三步是必须通过的自动化门槛，第四步是必须人工确认一次的真实行为。

---

## 1. 新增行为测试（fail-closed 与零残留）

```powershell
uv run python -m pytest tests/business/external_coding/test_target_repository_required.py -q
```

**期望**：全部通过。覆盖

- 未提供目标仓库 → 拒绝，且无 worktree、无分支、无会话行
- 目标位置不存在 → 拒绝，说明可行动
- 目标位置不是可用仓库（含空仓库 / HEAD 不可解析）→ 拒绝，说明可行动
- 目标位置合法 → 隔离工作区落在该仓库下
- 目标位置是 linked worktree → 放行并以该路径为基准
- 配置为绝对路径 → 落盘位置不受目标仓库影响
- artifact 根为相对路径 → 持久化及任务书中的所有 artifact 路径均为绝对路径
- mkdir/handoff/worktree/session 任一步失败 → 进入同一补偿边界；清理自身失败显式报错
- 显式指向 Exemplar 自身仓库 → **放行**（不得因指向自身而拒绝）

---

## 2. 工具契约与命令构造测试

```powershell
uv run python -m pytest tests/business/external_coding/test_external_coding_tools.py -q
```

**期望**：全部通过。覆盖

- `start_external_coding_session` 的 `targetWorktreePath` 在 `required` 中
- 参数说明含填参约束（绝对路径 / 必须是可用仓库 / 指向自身也需显式写出）
- codex 启动指令含明确读取指示，不含裸 `@` 前缀
- Claude Code 启动指令保持 `@` 引用写法
- 上述两条在 plan / implement / resume 三种情形下均成立
- Windows CLI 名称经 PATH/PATHEXT 解析但不启用 shell
- runner 的 `start()` 确实把解析后 argv 交给 `Popen`；状态/monitor 初始化失败会停进程
- Claude stream-json 携带 verbosity；Codex resume 父参数位于子命令前
- Codex headless plan / implement 分别以 `-o` 落盘 `PLAN.md` / `RESULT.md`
- attempt 先 reservation 后 spawn；结果落库失败停进程，poll 异常不制造 interrupted 假终态
- v33 持久化 PID 创建时间、未确认标记与 spawn 边界；单活索引拒绝重复 running attempt
- 重启后匹配存活 PID 可再次 stop；父进程消失或 PID 复用不误杀、不开放 resume
- terminal 状态身份冲突保持 running；旧 monitor 的 CAS 清理不删除 PID 复用后的新 owner
- failed/interrupted session/attempt 单事务投影；pre-spawn reservation 关单失败可恢复
- monitor 任意未预期异常进入统一守护恢复，不静默遗留无主进程
- v32 running 行升级后直接保持 unconfirmed；durable 创建时间缺失时状态文件不能补造身份
- running 观测使用 expected-status CAS，terminal 不可被迟到 poll 复活或清掉完成时间
- abandon/协议违规 stop 原子投影；terminal marker 可重放，满队列 reader 可取消回收
- PID 碰撞且新进程补偿终止失败时，两个 owner 仍按完整身份隔离管理
- reservation→spawn 交接使用 running + launch_started CAS；并发 abandon 获胜时 CLI 不启动
- reader 读取错误不会伪装 EOF，wait 超时走整棵进程树终止；domain 拒绝其可见 ownership/PID
  矛盾，Repository 与 SQLite guard 另拒绝完整 pre-spawn 非法组合
- session 首次写入结果未知时错误含恢复 session id；分支 probe 故障不伪装路径冲突
- adapter factory 在 launch CAS 前构造；失败仍按 pre-spawn 关单，`launch_started` 不可回退
- reader EOF/失败 sentinel 是 stream 完成权威；进程先退出、queue 暂空不会吞掉迟到读取错误
- Git timeout/OSError 与 HEAD 预期失败安全分类，未知异常不降级；恢复日志只含 session id 与异常类型

---

## 3. 全量回归

```powershell
uv run python -m pytest tests/business/external_coding tests/guardrails/test_external_coding_guardrails.py tests/guardrails/test_external_coding_composition_scope.py tests/integration/test_external_coding_closed_loop.py tests/data/test_external_coding_session_repository.py tests/data/test_external_coding_baseline_migration.py tests/data/test_migrations_v32.py tests/data/test_migrations_v33.py tests/desktop_api/test_external_coding_sessions_api.py tests/desktop_api/test_external_coding_ui_event.py tests/execution/test_external_coding_quota.py -q
```

**期望**：全绿，用例总数不少于 T001 变更前基线（实测 119 passed）。当前命令在 T001
原始范围上追加了后续 v32/v33 migration 回归，因此只比较不少于基线，不宣称测试集合未变。

> 若出现 teardown 相关的偶发失败，改为分文件执行并指定独立 `--basetemp` 复核——
> 这是本项目已知的测试隔离问题，不是本特性引入的回归。

---

## 4. 真实行为确认（必做一次，不可省略）

前三步只能证明代码按预期分支走，不能证明真实 CLI 场景下产物落在正确位置。
**必须实际执行一次并记录结果。**

### 4.1 前置

```powershell
claude --version
codex --version
```

### 4.2 准备一个目标仓库

准备一个 Exemplar 之外的 git 仓库作为目标（可临时新建并提交一次），记下其绝对路径。

### 4.3 正常启动

启动桌面应用，通过助理派一个极小的改动任务（例如给某个文档加一行），
委派信息中写明目标仓库的绝对路径。

**确认**：

- [x] 隔离 worktree 出现在**目标仓库**下，不在 Exemplar 目录下
- [x] Exemplar 仓库的 `git status` 无新增条目
- [x] `PLAN.md` 正常产出，内容确实对应本次任务目标（而非泛泛而谈）
- [x] 若本次选中的是 codex，其会话记录显示它拿到了任务书内容

### 4.4 拒绝路径

再派一次任务，委派信息中**不写**目标仓库路径。

**确认**：

- [x] 启动被拒绝，助理侧给出的说明能让人知道下一步该补什么
- [x] Exemplar 目录下无任何新增 worktree 或分支
- [x] 未产生新的会话记录

### 4.5 记录

把 4.3 与 4.4 的实际结果写回本文件末尾（含日期与所选 CLI）。
**跳过任何一项，都必须在此写明跳过原因**——不得默认视为通过。

---

## 执行记录

- 2026-07-21 / Codex / T001 变更前自动化基线：119 passed，43 warnings；命令与 T001 所列原始范围一致（当前第 3 步后来追加 v32/v33 migration 回归）/ 4.3、4.4 待 T015 执行
- 2026-07-21 / Codex / T014 变更后自动化回归：130 passed，43 warnings；较基线增加 11 项且无回归 / 4.3、4.4 待 T015 执行
- 2026-07-21 / Codex / T015 真实行为：使用 Exemplar 外临时 Git 仓库，经 `ExternalCodingSessionService` + `CliExternalCodingAdapter` + `ExternalCodingProcessRunner` 生产链启动；本机 CLI 为 Claude Code 2.1.216、Codex CLI 0.144.6。4.3 中目标仓库落盘、Exemplar `git status` 前后相同、命令摘要脱敏均通过；Codex 日志明确显示其读取 `prompts/plan-0.md` 与 `HANDOFF.md`，并包含 `README.md` 和精确目标句 `Validated by feature 035.`，故任务书送达通过。`PLAN.md` **未通过**：Codex 最终报告 artifact 写入被只读 sandbox / approval policy 拒绝，session 落 `interrupted`。4.4 三项全部通过：缺参返回可行动说明，session 数、worktree 集合、分支集合前后完全相同。跳过/失败说明：当前会话不能操作桌面 GUI，故未经助理 UI 派活，而是直跑同一 business + execution 生产路径；默认配置命令 `codex` 在 Windows Python subprocess 下因仅有 `.ps1/.cmd` shim 报 `WinError 2`，验证时改用统一配置支持的绝对 `codex.cmd`；Claude headless 路径因 2.1.216 要求 `--print + stream-json` 同时带 `--verbose` 而退出。这三项均为 T015 新暴露的既有运行时可靠性缺口，不计作 035 已通过事实。
- 2026-07-22 / Codex / T020 修复后真实复验：仍使用 Exemplar 外临时 Git 仓库，经同一 `ExternalCodingSessionService` + `CliExternalCodingAdapter` + `ExternalCodingProcessRunner` 生产链，以默认配置命令名 `codex` 启动（未改成绝对 `.cmd`）。真实进程进入 `plan_ready`，CLI `-o` 生成的有效 `PLAN.md` 含精确目标句 `Validated by feature 035 after remediation.`；worktree 位于目标仓库的 `.worktrees/coding/`，Exemplar `git status` 前后相同；持久化命令摘要中的 `--add-dir` 与 `-o` 参数均显示为 `<path>`。一次性 pytest 验收结果 `1 passed in 153.94s`。跳过说明：当前执行通道不能操作桌面 GUI，因此仍以工具 handler 下游完全相同的 production service/execution 链复验；工具 schema、owner 绑定与正式 Task 授权链由自动化 guard/integration 回归覆盖，未把 GUI 派活写成已人工验证。
- 2026-07-22 / T019 修复后自动化：第 3 步同范围回归 `135 passed, 43 warnings`；`uv run flake8 src/ tests/` 通过；本特性 9 个 Python 变更文件的 `black --check` 通过。全仓 `black --check src/ tests/` 仍报告 6 个本分支未修改的既有文件需格式化（`builtin_compositions.py`、`migrations.py`、`models_sqlite.py` 及 3 个 scheduling/frontend guard/integration 测试），为避免混入无关改动未自动重排；该例外不涉及 035 变更文件。
- 2026-07-22 / T021~T027 首轮 review remediation 定点回归：目标仓库、service attempt、CLI runner、Git、Repository 与 closed-loop 六组共 `62 passed`；覆盖相对 artifact、linked worktree、部分写入/清理失败、spawn 初始化、attempt 落库及 poll 观测异常。
- 2026-07-22 / T028 review remediation 全量门槛：第 3 步同范围 `152 passed, 43 warnings`；`uv run flake8 src/ tests/`、13 个 035 Python 变更文件 `black --check`、核心文件 `py_compile` 与 `git diff --check` 全部通过；模块 AI 三镜像 MD5 同为 `2D84BC69A17E80A572F52FDD2B11FE94`。
- 2026-07-22 / T029~T031 第二轮 verify remediation：新增真实 parent + child 进程树终止测试，CLI runner 定点 `17 passed`；第 3 步全量 `153 passed, 43 warnings`；flake8、13 个变更文件 Black、核心编译、diff check 与三镜像哈希再次通过。
- 2026-07-22 / T032~T035 第二轮 review remediation：stop 改为三态退出证明，终止未确认持久化 running ownership；补齐 monitor/startup 终止失败、三类启动异常摘要脱敏、session/attempt 投影顺序、PID ownership 补写失败及 artifact 路径不可变测试。定向 `44 passed`；第 3 步全量 `164 passed, 43 warnings`；全仓 flake8、13 个变更文件 Black、核心编译与 diff check 全部通过；模块 AI 三镜像 MD5 同为 `E1558C9B9C3879492FB53ADE46AC5567`。
- 2026-07-22 / T036~T039 第三轮 review remediation：SQLite v33 持久化 attempt PID 创建时间与未确认标记；重启后按完整身份再次 stop，身份未知或父进程消失保持 fail-closed；headless/interactive monitor 统一走 guarded wrapper，补状态/marker 双写失败和终态写入竞态测试。定向 `56 passed`；第 3 步扩大范围 `176 passed, 43 warnings`；全仓 flake8、16 个非既有格式债务 Python 变更文件 Black、核心编译与 diff check 全部通过；全仓 Black 仍只报告先前记录的 6 个既有文件；模块 AI 三镜像 MD5 同为 `C5458EAEDE6C6CA24DAC3446632CDBFF`。
- 2026-07-22 / T040~T044 第四轮 review remediation：registry 改为完整身份/状态路径键与对象 CAS，PID 复用碰撞先补偿新进程；terminal 状态必须匹配 durable PID + 创建时间；failed/interrupted session/attempt 改为 Repository 单事务；v33 增加 `launch_started` 与每 session 单 running attempt 索引，pre-spawn 关单失败可恢复。定向 `61 passed`；第 3 步扩大范围 `185 passed, 43 warnings`；全仓 flake8、16 个非既有格式债务 Python 变更文件 Black、核心编译与 diff check 全部通过；全仓 Black 仍只报告相同 6 个既有文件；模块 AI 三镜像 MD5 同为 `36F13A6043846E7ADB5E0DA91A02D212`。
- 2026-07-22 / T045~T050 第五轮 review remediation：v33 将旧 running attempt 回填为 unconfirmed，durable 创建时间缺失时禁止状态文件补造身份；running 观测改为 expected-status CAS，显式 stop 的 session/attempt 原子投影；monitor terminal 首写失败可由 poll 重放并释放 registry，满队列 reader 可取消；PID 碰撞且补偿终止失败时保留隔离双 owner。定向 `70 passed`；第 3 步扩大范围 `194 passed, 43 warnings`；全仓 flake8、16 个非既有格式债务 Python 变更文件 Black、核心编译与 diff check 全部通过；全仓 Black 仍只报告相同 6 个既有文件；模块 AI 三镜像 MD5 同为 `163B99A5F17DDC9A105D18B0EA912A97`。
- 2026-07-22 / T051 第六轮 verify remediation：terminal recovery payload 的 poll 重写再次失败时改为继续返回 running/unconfirmed 并保留 registry，下一次写入成功后才返回 terminal、释放 owner；连续失败→成功定向 `2 passed`，第 3 步扩大范围仍为 `194 passed, 43 warnings`；全仓 flake8、相关 Black、核心编译与 diff check 全部通过。
- 2026-07-22 / T052~T057 第六轮 review remediation：reservation→spawn 改为 running + unlaunched CAS，并发 abandon 获胜时不再启动 CLI；reader 读取错误与 EOF 分型且 wait 超时统一整树终止；首次 session 写入结果未知返回恢复 id，分支 probe 区分 Git 运行故障与未知异常；domain value 守其可见 ownership/PID 组合，Repository/SQLite 另守完整 pre-spawn 状态。定向 `95 passed`；第 3 步扩大范围 `202 passed, 43 warnings`；全仓 flake8、16 个非既有格式债务 Python 变更文件 Black、核心编译与 diff check 全部通过；全仓既有 Black 债务仍为相同 6 个文件；模块 AI 三镜像 MD5 同为 `0548B619F4013D0CAC78B41F890E4434`。
- 2026-07-22 / T058~T063 第七轮 review remediation：reader sentinel 成为唯一正常 stream 完成依据，进程先退出不再吞延迟读取错误；adapter factory 移至 launch CAS 前；Git process/HEAD 错误精确安全分类，未知首写结果日志可按 session id 关联；`launch_started` 从通用更新移除且 v33 UPDATE trigger 禁止 true→false。定向 `112 passed`；第 3 步扩大范围 `207 passed, 43 warnings`；全仓 flake8、16 个非既有格式债务 Python 变更文件 Black、核心编译与 diff check 全部通过；全仓既有 Black 债务仍为相同 6 个文件；模块 AI 三镜像 MD5 同为 `723A934F0095C20899176AC14F17C503`。

# Implementation Plan: 外部 Coding 可靠性修复

**Branch**: `035-external-coding-reliability` | **Date**: 2026-07-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/035-external-coding-reliability/spec.md`

## Summary

两处把"模型会自觉做对"当成保证的地方，改成显式硬边界，并收口 T015 暴露的三条
生产运行时缺口：

1. **目标仓库必填**（P1）——启动外部 coding session 时若未指明目标仓库，直接拒绝，不再回退到进程当前目录（当前回退目标就是 Exemplar 自身仓库）。同时把隔离 worktree 的落盘基准从进程 cwd 改为目标仓库。
2. **codex 任务书送达**（P2）——codex 分支的启动指令由裸 `@路径` 改为带动词的明确读取指示；Claude Code 分支保持不变（实测其自动预取有效）。
3. **失败补偿完整**——部分创建或 session 首次持久化失败时，同时回收 worktree、生成分支
   与本次 artifact；plan/result 路径并入首次 session 写入，消除二次更新的半初始化窗口。
4. **当前 CLI 可启动**——Windows 命令名先经 PATH/PATHEXT 解析但仍以 argv、无 shell 启动；
   Codex headless resume 使用当前子命令语法并以 `-o` 落阶段 artifact；Claude headless
   `stream-json` 补当前版本要求的 `--verbose`。
5. **进程与状态失败原子**——artifact 路径先绝对化；启动资源统一逆序补偿并验证删除；
   attempt 先 reservation 后 spawn；停止使用三态证明，无法确认时持久化 running ownership；
   failed/interrupted session 与 attempt 由 Repository 单事务投影，poll 失败保持 running；
   SQLite v33 持久化 PID 创建时间、未确认标记和 spawn 边界，单活索引禁止重复 CLI；
   registry 以完整身份/CAS 防 PID 复用，monitor 由统一顶层守护边界收口任意运行期异常；
   旧 running 行升级即 fail-closed，状态文件不得补造 durable identity；所有 running 观测
   以条件 CAS 保证终态单向，adapter 构造后 reservation→spawn 才以 CAS 取得启动权，且
   `launch_started` 不可回退；reader sentinel 是 stream 完成权威，读取错误显式进入整树
   守护终止，取消与 terminal 重放关闭后台资源及恢复窗口。

改动集中在既有 external coding business / execution / repository 边界，零新增表、配置键、
事件与密钥。

## Technical Context

**Language/Version**: Python 3.12（运行时），既有 `from __future__ import annotations` 风格
**Primary Dependencies**: 无新增第三方依赖。涉及标准库 `shutil.which` 与既有 `UnifiedConfigManager`、`ExternalCodingSessionRepository`、`ExternalCodingProcessRunner`
**Storage**: SQLite（`external_coding_sessions` / `external_coding_attempts`）——v33 在既有 attempt 表新增 `process_create_time` / `termination_unconfirmed` / `launch_started` 三个内部恢复字段、单活 partial unique index、跨字段 ownership guards 与 launch 单向 UPDATE guard；无新表
**Testing**: pytest。T001 变更前基线 119 个；T063 的 business / guardrails / integration / data / desktop_api / execution 扩大范围实测 `207 passed, 43 warnings`
**Target Platform**: Windows 11 桌面（Tauri shell + Python FastAPI sidecar）
**Project Type**: desktop-app（前后端分离，本特性触及 Python 后端 business / execution / data 边界）
**Performance Goals**: N/A——不涉及热路径。codex 侧明确文件读取指示只提升任务书送达确定性，
不承诺减少模型工具调用轮次
**Constraints**: 全部失败路径 fail-closed；可补偿失败零残留，补偿自身失败显式 cleanup-incomplete；不得产生无主进程或假终态；错误文案不得透出底层异常
**Scale/Scope**: 9 个既有源文件 + 测试与规格/活文档；无新模块、配置或公开契约

**无 NEEDS CLARIFICATION**——两处技术分歧（codex 走轻方案还是 stdin、是否建项目注册表）已在规格阶段收敛，理由记录于 research.md。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. 分层边界与事件协调 | 是否保持 `UI -> business -> execution -> data` 方向，跨模块通知是否走 `src/utils/events.py`？ | **PASS**。business 仍只向下调用 execution/data；可执行入口解析留在 `external_coding_process.py`，session 原子字段写入留在 Repository。无新增/修改事件、无反向依赖 |
| II. 数据边界与持久化纪律 | SQLite/DuckDB 职责是否明确，Repository 边界是否保持？ | **PASS**。session 首次写入经 `ExternalCodingSessionRepository.create_session()` 同时保存 plan/result 路径；进程 ownership 经 Repository 写 attempt，关联终态用单事务投影。v33 迁移只为既有 attempt 表增加三个内部字段、单活索引与 ownership insert/update guards，旧 running 行回填 `NULL/true/true`、旧 terminal 行回填 `NULL/false/true`；running 观测与 spawn 权交接通过 CAS 单向投影，无业务层裸 SQL |
| III. 统一配置与密钥安全 | 配置与密钥是否全部经 `UnifiedConfigManager`？ | **PASS，附带文档义务**。无新增配置键、无新增敏感字段。既有键 `external_coding.worktree_root`（默认 `.worktrees/coding`）**键名与默认值不变，但相对路径的展开基准由进程 cwd 改为目标仓库**——属行为语义变更，MUST 在 `docs/PROJECT_CONSTRAINTS.md` 与模块 AI 入口文档中写明，详见 Phase 1 文档清单。读取仍只经 `get_unified_config()` |
| IV. 可验证交付 | 确定性逻辑与静默失败风险点是否有自动化覆盖？ | **PASS（记录既有格式例外）**。除既有失败路径外，新增 v33 幂等升级/回退与 ownership trigger、旧 running fail-closed 回填、状态与 marker 双写失败、跨重启身份验证/再次 stop、缺失创建时间防身份洗白、PID 复用/CAS 与碰撞补偿失败、terminal 身份冲突/单向状态、显式 stop 原子回滚、reservation→spawn 竞态、monitor terminal 重放、reader 取消及读取错误测试；T020 另跑真实 Codex 生产路径。最新回归与静态门槛记录见 quickstart。全仓既有 Black 债务仍单列，不夹带无关重排 |
| V. 活文档与规格驱动交付 | 活文档是否识别待更新项，临时材料是否限于 `docs/local/`？ | **PASS**。已更新：`src/AGENTS.md` + `src/CLAUDE.md` + `src/GEMINI.md`（三镜像同内容）、`docs/PROJECT_CONSTRAINTS.md`。规格与计划受版本控制于本目录。历史过程设计草稿置于 `docs/local/`，并明确不作为当前真相 |

**结论：五项全部通过，无需 Complexity Tracking 记录例外。**

## Project Structure

### Documentation (this feature)

```text
specs/035-external-coding-reliability/
├── spec.md              # 已完成
├── plan.md              # 本文件
├── research.md          # Phase 0 输出
├── data-model.md        # Phase 1 输出
├── quickstart.md        # Phase 1 输出
├── contracts/           # Phase 1 输出（工具参数契约）
│   └── start-external-coding-session.md
├── checklists/
│   └── requirements.md  # 已完成，16 项全绿
└── tasks.md             # Phase 2（由 /speckit-tasks 生成，本命令不创建）
```

### Source Code (repository root)

本特性只触及 Python 后端 external coding 既有边界；前端、Tauri、desktop API 和录制层
均不改动。数据层增加 SQLite v33 的既有表列迁移。

```text
src/
├── business/
│   ├── external_coding/
│   │   ├── service.py          # 改：目标仓库/绝对 artifact + 启动/attempt 补偿
│   │   ├── cli_adapters.py     # 改：任务书指令 + 当前 CLI 语法 + headless artifact 输出
│   │   ├── models.py           # 改：进程创建时间与 ownership 内部结果字段
│   │   └── git_ops.py          # 改：可验证删除 worktree 与生成分支
│   └── agents/
│       └── tools/
│           └── external_coding_tools.py   # 改：targetWorktreePath 入 required + 参数说明改写
├── data/
│   ├── migrations.py           # 改：SQLite v33 ownership 字段、索引与写入 guards
│   ├── models_sqlite.py        # 改：attempt 内部 ownership 列与 check constraints
│   └── repos/external_coding_session_repository.py  # 改：artifact 与 ownership 持久化
└── execution/
    └── external_coding_process.py         # 改：PATH/PATHEXT + 路径脱敏 + spawn 补偿

tests/
└── business/
    └── external_coding/
        ├── test_external_coding_tools.py       # 扩充：schema 契约 + 命令构造
        ├── test_cli_adapters.py                # 扩充：CLI 语法、输出与 shim 解析
        ├── test_git_ops.py                     # 扩充：删除结果验证
        ├── test_service_attempts.py            # 扩充：reservation/落库/poll 故障
        └── test_target_repository_required.py  # 新增：fail-closed 与启动补偿行为
tests/data/test_migrations_v33.py               # 新增：v33 幂等升级/回退
```

**Structure Decision**: 沿用既有目录布局，不新建模块。三个被改文件都已存在且职责清晰——
`service.py` 负责启动编排与补偿，`git_ops.py` 负责 Git 原语，`cli_adapters.py` 负责命令
构造，execution runner 负责无 shell 启动和进程身份验证，Repository 负责单次持久化，迁移
只在 data 层演进 schema，工具 facade 负责参数契约。没有把兼容逻辑上移或跨层直连。

## Complexity Tracking

> Constitution Check 五项全部通过，无违规需要说明。本节留空。

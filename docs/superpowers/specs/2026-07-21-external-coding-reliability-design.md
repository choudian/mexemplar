# 外部 Coding 可靠性修复设计

日期：2026-07-21
状态：待实现

## 背景

两个缺陷都指向同一类问题：**系统把"模型会自觉做对"当成了保证**。修复思路一致——
把静默的软依赖变成显式的硬边界。

两条都经过本机实测确认，不是代码审读推断。

## 缺陷一：codex 收不到任务书

### 现状

`cli_adapters.py:152,193` 对两个 CLI 使用同一个 `@{prompt_path}` 写法传递任务。
`@` 是 Claude Code 的文件引用语法，写这行的意图是"CLI 会把它展开成内容"。

实测结果（拦截两个 CLI 实际发出的请求体）：

| CLI | 行为 | 结论 |
|---|---|---|
| Claude Code | user 消息是字面路径，但 CLI **自动预取**：抢先调 Read 工具，把文件内容作为 system 消息注入上下文 | `@` 有效，任务书确实送达 |
| Codex | user 消息只有字面路径，无任何预取；agent 自行决定调 shell 读取文件才拿到内容 | `@` 无效，靠 agent 自觉 |

即 `@` 语法只对 Claude Code 成立。

### 影响

`toolPreference` 默认 `auto`，按 quota 自动选工具。同一个任务落到 Claude Code 是任务书
直接送达，落到 codex 是给个地址让它自己找——**系统把这两条路当等价，用户也感知不到
本次落在哪条**。codex 侧每次额外消耗一轮工具调用，且在 `--add-dir` 授权异常时会拿不到
任务书。

### 修复

codex 分支的 prompt 参数从 `f"@{prompt_path}"` 改为一句带动词的指令：

```
Follow the instructions in this file: <prompt_path>
```

Claude Code 分支保持 `@` 不变——实测证明它有效。

**已知取舍**：这仍然依赖 agent 主动读文件，只是把"靠它猜"变成"明确告诉它读"，每次
仍多一轮工具调用。彻底方案是走标准输入直接投喂内容，但需改动
`external_coding_process.py` 的进程启动（headless 下当前 `stdin=DEVNULL`，见第 125 行）。
本次选择最轻方案，彻底方案留待 codex 侧出现实际问题时再做。

### 附带风险记录

Claude Code 的 `@` 依赖 background prefetch 机制。`--bare` 模式会跳过 prefetch——实测
带 `--bare` 时那条 Read 注入消失，Claude Code 同样退化成只收到裸路径。因此若将来为
提高确定性给 Claude Code 加上 `--bare`，`@` 会**静默失效**。需在该行留注释说明此耦合。

## 缺陷二：目标仓库默认指向 Exemplar 自己

### 现状

```python
repo_root = Path(target_worktree_path or Path.cwd()).resolve()   # service.py:144
```

`targetWorktreePath` 在工具 schema 中是**可选**参数，描述仅为"可选目标 worktree 路径"
（`external_coding_tools.py:36`），未说明缺省行为。缺省即 sidecar 进程的 cwd，也就是
Exemplar 自己的仓库。

### 为什么记忆解决不了

大脑记忆只注入主助理：`assistant_prompt_builder.py:45-62` 按 `AgentType.ASSISTANT`
构建 brain context。真正调用 `start_external_coding_session` 的是固定 executor 专员，
走另一条 prompt 路径，看不到这些记忆。

路径要传到专员手里，只能靠主助理委派时写进任务描述，于是形成三层软约束串联：

```
记忆（仅主助理可见）
  → 主助理委派时写进描述      软约束
  → 专员从描述读出路径        软约束
  → 填进工具参数              软约束
  → Path.cwd() 兜底接住       静默落到 Exemplar 自己
```

模型侧无论怎么改进都无法消除末端那个静默默认值——那由代码决定。

### 修复

**1. 删除兜底，改为必填。**

```python
if not target_worktree_path:
    raise ValueError("target worktree path is required")
repo_root = Path(target_worktree_path).resolve()
```

工具 schema 中 `targetWorktreePath` 移入 `required`，description 改写为明确的填参约束
（按项目惯例，填参约束写在工具 schema description 而非 system prompt）。

**注意不是禁止指向 Exemplar 自己**——用 external coding 开发 Exemplar 本身是正当用途。
要消除的只是"静默滑入"：填 Exemplar 可以，但必须显式填出来。

**2. 校验失败给可行动的错误。**

路径不存在、不是 git 仓库、HEAD 无法解析时，返回明确原因，不返回裸异常。现有
`self._git.head(repo_root, "HEAD")` 已会失败（`service.py:146-148`），只需改善错误文案。

**3. worktree 根目录跟随目标仓库。**

```python
worktree_root = Path(self._config.get_external_coding_worktree_root())  # ".worktrees/coding"
worktree_path = (worktree_root / coding_session_id).resolve()           # service.py:150-152
```

配置默认值是**相对路径**，`.resolve()` 相对进程 cwd 展开。即使目标仓库是 `D:\Foo`，
worktree 仍建在 `E:\code\Exemplar\.worktrees\coding\` 下。这是同一个问题的另一面：
产物默认堆在 Exemplar 目录里。

改为相对路径时以 `repo_root` 为基准展开：`repo_root / worktree_root / coding_session_id`；
配置为绝对路径时保持原样。这样各项目的 worktree 落在各自仓库下，`.gitignore` 也由各
项目自己管。

**无迁移负担**：`external_coding_sessions` 与 `external_coding_attempts` 当前均为 0 行，
不存在按旧规则落盘的历史 worktree 需要兼容。

## 测试

**缺陷一**：命令构造单测——codex 分支不含 `@` 前缀、含指令动词与路径；Claude Code
分支保持 `@`。覆盖 headless / interactive / resume 三种组合。

**缺陷二**：
- 不传 `targetWorktreePath` → 拒绝，且不创建 worktree、不写 session 行
- 传入非 git 目录 → 可行动错误
- 传入合法仓库 → worktree 落在该仓库下而非 Exemplar 下
- 配置为绝对路径时不受 repo_root 影响

现有 external coding 测试共 100 个用例（business + guardrails + integration + data +
desktop_api + execution），修改后必须全绿。

## 不做什么

- 不建项目注册表、不加设置 UI。等真正同时开发多个项目、嫌手报路径烦时再说。
- 不改 Claude Code 的 `@` 写法（实测有效）。
- 不做 codex 的 stdin 投喂（本次选轻方案）。
- 不动授权链（固定专员 + 已配组合 + 非空 current_task_id 的四重 fail-closed 保持不变）。

## 已验证的事实

- 两个 CLI 的 `@` 行为差异 — 拦截 Claude Code 与 codex 实际请求体实测
- `--bare` 会关闭 prefetch 导致 `@` 失效 — 同一实测的对照组
- CLI 参数全部合法 — `claude --help` / `codex exec --help` 逐项核对，
  `--effort` 合法值含 `max`，`codex exec resume --json` 存在
- headless 下 stdin 为 DEVNULL — `external_coding_process.py:125`
- brain 记忆只注入主助理 — `assistant_prompt_builder.py:45-62`
- 相关测试 100 个全部通过 — 实际执行 pytest 确认

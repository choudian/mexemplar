# Contract: PM / Programmer 双轨 prompt + ast.parse syntax gate

## 1. `build_pm_prompt(recording_mode: str) -> str`

```python
# src/business/agents/prompts/desktop_prompts.py

# 主仓现有常量名为 PM_SYSTEM_PROMPT；本模块统一以 _LEGACY 别名重导出，
# 让"双轨"语义在桌面 prompt 模块内部直观——legacy=既有浏览器 prompt。
from src.business.agents.prompts.pm_prompt import PM_SYSTEM_PROMPT as PM_SYSTEM_PROMPT_LEGACY

_PM_COMMON_HEADER = """..."""    # 桌面 prompt 通用头（角色 + 工具集说明）
_PM_DESKTOP_GUIDANCE = """..."""  # 桌面专属导航策略段
_PM_COMMON_FOOTER = """..."""    # 桌面 prompt 通用尾（输出格式 + 终态指令）

def build_pm_prompt(recording_mode: str) -> str:
    if recording_mode == "browser":
        return PM_SYSTEM_PROMPT_LEGACY    # 字节级保留（CC-003 + SC-006）
    elif recording_mode == "desktop":
        return _PM_COMMON_HEADER + _PM_DESKTOP_GUIDANCE + _PM_COMMON_FOOTER
    else:
        raise ValueError(f"Unknown recording_mode: {recording_mode}")
```

### `_PM_DESKTOP_GUIDANCE` 必含元素（FR-019）

- **导航策略**：先看头尾 → 按 `window_title` 聚焦 → 跳过冗余类型 → 关键节点用 `analyze_desktop_action`；
- **工具集说明**：5 通用工具（mode 已切到桌面）+ 3 桌面专属工具（`list_desktop_actions` / `analyze_desktop_action` / `read_action_clip`）；
- **不强制工具调用配额**（不在 prompt 内写"必须先调 X 再调 Y"，由 LLM 自决策）。

### Browser legacy 保留（CC-003 + SC-006）

- 主仓现有常量名为 `PM_SYSTEM_PROMPT`（位于 `src/business/agents/prompts/pm_prompt.py`），本契约中以 `PM_SYSTEM_PROMPT_LEGACY` 别名引用；语义"legacy=既有浏览器 prompt"由 desktop_prompts.py 内 `as PM_SYSTEM_PROMPT_LEGACY` 别名重导出落地，**不修改**主仓常量名；
- 别名重导出后字节级保留（不能修改一个字符）；
- 行为级守卫测试断言关键短语（如"录制分析"、"intent"、"talk_to_user"等）出现，避免无意识改动。

---

## 2. `build_programmer_prompt(recording_mode: str) -> str`

同形结构：

```python
def build_programmer_prompt(recording_mode: str) -> str:
    if recording_mode == "browser":
        return PROGRAMMER_SYSTEM_PROMPT_LEGACY    # 字节级保留
    elif recording_mode == "desktop":
        return _PROGRAMMER_COMMON_HEADER + _PROGRAMMER_DESKTOP_GUIDANCE + _PROGRAMMER_COMMON_FOOTER
    else:
        raise ValueError(f"Unknown recording_mode: {recording_mode}")
```

### `_PROGRAMMER_DESKTOP_GUIDANCE` 必含元素（FR-020）

- **"找捷径"元思维 1-2 个例子**：
  - 例 1：双击微信图标 → `start wechat:` URL 协议（不写"必须用 wechat: 协议"，仅引导思路）；
  - 例 2：从开始菜单启动 VSCode → `subprocess.run(["code", file])`（不强制具体命令）；
- **不写死对照表**（避免 LLM 机械套用）；
- **代码契约强约束**（FR-020）：
  - 函数签名：`async def execute() -> dict` 无参；
  - 返回：`{"ok": bool, "summary": str, "details": dict | None}`；
  - `recording_id` / PM intent 由 Programmer 在代码内部硬编码（不通过子进程边界传参，spec round 1 第 5 题）。

---

## 3. Orchestrator dispatch（FR-017）

```python
# src/business/orchestration/agent/orchestrator.py

import dataclasses
from src.business.agents.config import PM_CONFIG, PROGRAMMER_CONFIG
from src.business.agents.prompts.desktop_prompts import build_pm_prompt, build_programmer_prompt

def start_pm_agent(workflow):
    pm_config = dataclasses.replace(
        PM_CONFIG,
        prompt=build_pm_prompt(workflow.recording_mode),
    )
    return AgentLoop(config=pm_config, ...).run(...)

def start_programmer_agent(workflow):
    prog_config = dataclasses.replace(
        PROGRAMMER_CONFIG,
        prompt=build_programmer_prompt(workflow.recording_mode),
    )
    return AgentLoop(config=prog_config, ...).run(...)
```

**约束**：
- `dataclasses.replace` 是不可变拷贝，零状态泄漏（每次启动新 Agent 都构造新 config）；
- `agent_loop.format_system_prompt()` 不改造（FR-017）；
- `execution_strategy` 枚举增 `desktop` 取值（FR-018）。

---

## 4. ast.parse syntax gate + 自动反馈重试（FR-017a）

### 流程

```text
Programmer Agent 输出代码
        ↓
ast.parse(code)
        ├─ 语法 OK → 交给 Trial 子进程
        │
        └─ SyntaxError →
                ├─ retry_count < 2 →
                │       │
                │       构造反馈消息（FR-017a 模板）
                │       ↓
                │       注入 Programmer Agent conversation 作为新一轮 user message
                │       ↓
                │       Programmer 重新生成代码 → 回到 ast.parse
                │
                └─ retry_count == 2（共 3 次连续失败） →
                        ↓
                        终态失败：
                        - UI Toast 标题 "Programmer 输出代码持续语法错误"
                        - UI Toast 正文 = 末次 SyntaxError.msg + lineno
                        - 进程日志落 3 次代码 + 反馈消息 + 原始异常
                        - 用户视角延长的"Programmer 思考中..."状态结束
```

### 反馈消息模板

```text
你之前生成的代码在 line {lineno} 出现语法错误：{msg}

出错位置（含上下 2 行）：
{snippet}

请重新输出修复后的完整 `async def execute() -> dict` 函数。
```

**约束**：
- `{msg}` = `SyntaxError.msg`；
- `{lineno}` = `SyntaxError.lineno`；
- `{snippet}` = 出错行 ± 2 行代码片段（共 ≤ 5 行）；
- MUST NOT 暴露 `offset` / `filename` 等 SyntaxError 内部属性；
- MUST NOT 写"增量修复"或"修改第 X 行"指令——明确"重新输出完整函数"避免 LLM 误判。

### 测试切面（FR-017a 显式要求独立单元测试）

| Fixture | 期望行为 |
|---|---|
| 合法代码 | 一次通过 syntax gate，retry_count = 0 |
| 一次语法错二次通过 | retry_count = 1，反馈消息正确构造 |
| 连续 3 次语法错 | retry_count 累至 2 后触发终态失败，UI Toast + 进程日志均落 |
| 反馈消息模板渲染 | 给定 `SyntaxError(lineno=10, msg="invalid syntax")` 渲染输出包含 "line 10" + msg + 上下文片段 5 行 |
| 浏览器 mode 不走 syntax gate | 浏览器 mode Programmer 输出代码不进 syntax gate（仅桌面 mode 触发，避免破坏浏览器路径） |

---

## 5. 浏览器路径门卫（CC-003 + SC-006）

| 守卫 | 测试 |
|---|---|
| `PM_SYSTEM_PROMPT_LEGACY` 字节级保留 | hash 断言 `sha256(PM_SYSTEM_PROMPT_LEGACY) == <baseline_hash>` |
| 浏览器 mode `build_pm_prompt` 返回 `PM_SYSTEM_PROMPT_LEGACY` | identity 断言 `build_pm_prompt("browser") is PM_SYSTEM_PROMPT_LEGACY` |
| 关键短语断言 | 浏览器 prompt 中含 "录制分析" / "talk_to_user" / "intent" 等关键短语（可由 fixture 列表参数化） |
| 桌面 mode `build_pm_prompt` 含 `_PM_DESKTOP_GUIDANCE` | substring 断言 `"按 window_title 聚焦" in build_pm_prompt("desktop")` |
| Programmer 同形 | 同上 4 条断言但 Programmer prompt |

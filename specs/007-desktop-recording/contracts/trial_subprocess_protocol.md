# Contract: Trial 子进程协议

> 桌面 Trial 子进程启动 / wrapper / cwd / env 白名单 / 120s kill / stdout JSON 解析全套契约。

## 启动入口

```python
# src/execution/desktop_trial_runner.py

def run_desktop_trial(
    code: str,                   # Programmer 输出代码（已通过 ast.parse syntax gate）
    trial_id: str,               # UUID（与 recording_id / action_id 同套生成函数）
) -> TrialResult:
    """启动 Trial 子进程，等待结束或 120s 超时，返回 TrialResult。"""
```

**边界**：`src/execution/desktop_trial_runner.py` 负责创建 `data/trials/<trial_id>/`、设置 cwd/env、执行 subprocess、落 `stdout.log` / `stderr.log`；business/orchestrator 只负责编排 runner 调用与 blinker 事件；UI 只触发试用与展示 preview/result，MUST NOT 直接创建或写入 `data/trials/`。

## wrapper 模板

```python
WRAPPER_TEMPLATE = """
import asyncio, json, sys, traceback

{user_code}    # Programmer 输出代码（含 async def execute() -> dict）

async def _main():
    try:
        result = await execute()
        # 校验返回 shape
        if not isinstance(result, dict):
            return {{"ok": False, "summary": f"execute() 返回非 dict: {{type(result).__name__}}", "details": None}}
        return result
    except Exception as e:
        return {{
            "ok": False,
            "summary": f"{{type(e).__name__}}: {{e}}",
            "details": {{"traceback": traceback.format_exc()}}
        }}

if __name__ == "__main__":
    try:
        result = asyncio.run(_main())
    except Exception as e:
        result = {{
            "ok": False,
            "summary": f"{{type(e).__name__}}: {{e}}",
            "details": {{"traceback": traceback.format_exc()}}
        }}
    print(json.dumps(result, ensure_ascii=False))
"""
```

**约束**：
- `_main()` 内层 `try/except` 捕获 execute() 业务异常 → 包成 `{"ok": False, "summary": "...", "details": {"traceback": "..."}}`；
- `__main__` 外层 `try/except` 兜底 `asyncio.run` 自身异常（如 ImportError 在 module-level 抛出）；
- 任何 wrapper 自身崩溃（`asyncio` 模块缺失等）→ 落到 stderr，stdout 末行无有效 JSON（由 UI 兜底处理）；
- `print` 末行 JSON 走默认 stdout（被 PIPE 收集）。

## subprocess.Popen 参数

```python
import subprocess, sys

trial_dir = Path("data/trials") / trial_id
trial_dir.mkdir(parents=True, exist_ok=True)

env = build_whitelisted_env()    # 见下文 §env 白名单

proc = subprocess.Popen(
    [sys.executable, "-u", "-c", wrapper_code],
    stdin=subprocess.PIPE,        # 不写入但保留 PIPE 避免子进程阻塞
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(trial_dir),
    env=env,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,    # 让 taskkill /T 整树 kill
)

try:
    stdout_bytes, stderr_bytes = proc.communicate(timeout=120)
    timed_out = False
except subprocess.TimeoutExpired:
    proc.terminate()
    # taskkill 整树兜底
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
        timeout=5, capture_output=True,
    )
    stdout_bytes, stderr_bytes = proc.communicate(timeout=5)    # 收集 kill 后 buffer
    timed_out = True
```

## env 白名单

```python
WHITELISTED_ENV_VARS = {
    "PATH", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "TEMP", "TMP",
    "PYTHONPATH", "PYTHONHOME",
    "LANG", "LC_ALL",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "PROGRAMFILES", "PROGRAMFILES(X86)",
}

SENSITIVE_PATTERNS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "KEYRING")

def build_whitelisted_env() -> dict[str, str]:
    """构造 Trial 子进程 env，仅传白名单变量；含敏感子串变量必过滤。"""
    parent_env = os.environ
    result = {}
    for key, value in parent_env.items():
        # 第一道：仅传白名单
        if key not in WHITELISTED_ENV_VARS:
            continue
        # 第二道：白名单内若含敏感子串（理论上不会，双保险）也过滤
        key_upper = key.upper()
        if any(pat in key_upper for pat in SENSITIVE_PATTERNS):
            continue
        result[key] = value
    return result
```

**测试断言**：
- 父进程 env 含 `OPENAI_API_KEY=sk-xxx` → 子进程 env 不含；
- 父进程 env 含 `MY_TOKEN=abc` → 子进程 env 不含；
- 父进程 env 含 `PATH=...` → 子进程 env 含同值；
- 父进程 env 含 `SOMETHING_SECRET=xxx` → 子进程 env 不含；
- 大小写不敏感：`my_secret_thing` 也被过滤。

## stdout 末行 JSON 解析

```python
def parse_trial_stdout(stdout_bytes: bytes, stderr_bytes: bytes, exit_code: int) -> dict:
    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    lines = stdout_text.splitlines()
    if lines:
        last = lines[-1].strip()
        try:
            parsed = json.loads(last)
            if isinstance(parsed, dict) and "ok" in parsed and "summary" in parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    # 兜底：stdout 末行无有效 JSON
    stderr_tail = "\n".join(stderr_text.splitlines()[-5:])[:200]
    return {
        "ok": False,
        "summary": stderr_tail or "(无 stderr 输出)",
        "details": {"_fallback": "stdout_no_json"},
    }
```

**SC-003 判定**：只有 `exit_code == 0`、stdout 末行 JSON 解析成功、且解析结果 `ok is True` 三者同时满足，才算该场景"试用通过"。

## TrialResult dataclass

```python
@dataclass
class TrialResult:
    ok: bool                       # JSON ok 字段，超时时 False
    summary: str                   # JSON summary 字段，超时时固定 "试用超时"
    details: dict | None           # JSON details 字段
    exit_code: int | None           # 子进程退出码；超时且整树 kill 时可为 None 或 taskkill 后的最终 returncode
    timed_out: bool                # 是否触发 120s kill
    stdout_path: Path              # data/trials/<trial_id>/stdout.log
    stderr_path: Path              # data/trials/<trial_id>/stderr.log
    trial_id: str
```

## UI Toast 路由（FR-021 + FR-021a + spec round 4 第 4 题）

| 场景 | Toast 标题 | Toast 正文 |
|---|---|---|
| 子进程退出 + exit_code=0 + 末行 JSON ok=True | "试用成功" | `summary` 字段 |
| 子进程退出 + 末行 JSON ok=False | "试用失败" | `summary` 字段 |
| 子进程退出 + exit_code!=0 | "试用失败" | `summary` 字段；若 stdout 无有效 JSON 则走 stderr 兜底 |
| 子进程退出 + stdout 末行无有效 JSON | "试用失败" | stderr 末 5 行（≤ 200 字符） |
| 120s 超时 + taskkill | "试用超时" | (固定文案 "代码执行超过 120 秒已被终止") |

**约束**：
- 复用现有普通 Toast（`AuthToastSurface` 不复用，FR-021）；
- 自动消失 ≈ 5 秒、非模态、不抢焦点；
- **不接入** Windows 系统原生通知中心；
- **不写入对话历史**。

## 事前提示对话框（FR-021）

### 内容

```text
┌─ 试用提示 ─────────────────────────────────────────┐
│ 试用代码即将在桌面真实执行（最长 120s）            │
│                                                     │
│ ┌─ 代码预览（可滚动） ──────────────────────────┐  │
│ │ async def execute() -> dict:                   │  │
│ │     # ... Programmer 生成的代码 ...            │  │
│ │     return {"ok": True, "summary": "..."}     │  │
│ └──────────────────────────────────────────────┘  │
│                                                     │
│ 检测到的高危 API：                                 │
│   ▸ subprocess                                      │
│   ▸ pywinauto                                       │
│                                                     │
│ ┌────────────┐  ┌────────────┐                     │
│ │  开始       │  │  取消       │                     │
│ └────────────┘  └────────────┘                     │
└─────────────────────────────────────────────────────┘
```

### 高危 API 检测规则（与 SC-004 同套机械检测）

代码任一命中即标签化展示：
- `subprocess` 模块导入或 attr 调用；
- `os.startfile`；
- `webbrowser` 模块；
- Win32 协议 URL（如 `wechat:` / `mailto:`；匹配 URL-like `<scheme>:`，但 MUST 排除 Windows 盘符路径如 `C:\foo` / `D:/tmp`）；
- `pywin32` 高级 API（限定 `win32api` / `win32gui` / `win32com` / `win32process` / `win32service` / `win32clipboard` / `pythoncom` 等模块 import 或调用）；
- `pywinauto` 控件级 API（`pywinauto.Application`）。

### 按钮行为

- "开始" → 启动 Trial 子进程（按本契约执行）；
- "取消" → 放弃试用，回到 intent 页（`status='stopped'` 不变）。

## Trial 目录 cleanup

- 启动期 `RecordingRepository.ensure_startup_recovery()` 同期扫描 `data/trials/` 子目录；
- mtime > 7 天 → `shutil.rmtree(trial_dir)`；
- 7 天保留期内目录保留 `stdout.log` / `stderr.log` 供事后调试；
- 进程运行期不动（不在 Trial 退出时立即清理）。

## 测试切面

| 测试 | 验证 |
|---|---|
| `test_subprocess_starts` | 简单 `execute()` 返回 `{"ok": True}` → 子进程退出码 0 + `TrialResult.exit_code == 0` + 末行 JSON 正常 |
| `test_nonzero_exit_not_passed` | 子进程退出码非 0 时，即使 stdout 末行 JSON `ok=True`，SC-003 helper 仍判定不通过 |
| `test_async_exception_wrapped` | `execute()` 抛 `ValueError("boom")` → wrapper 包成 `{"ok": False, "summary": "ValueError: boom", "details": {"traceback": ...}}` |
| `test_120s_timeout_kill` | `execute()` 含 `await asyncio.sleep(150)` → 120s 后 `Popen.terminate()` + `taskkill /F /T` → `timed_out=True` + Toast "试用超时" |
| `test_grandchild_kill` | `execute()` `subprocess.Popen(["timeout", "200"])` → 父子孙树整树 kill |
| `test_env_whitelist_no_api_key` | 父 env 含 `OPENAI_API_KEY` → 子 env 不含；父 env 含 `PATH` → 子 env 含 |
| `test_env_whitelist_pattern_filter` | 父 env 含自定义 `MY_TOKEN_X` → 子 env 不含 |
| `test_cwd_isolation` | wrapper 内 `Path.cwd()` 返回 `data/trials/<trial_id>/` |
| `test_trial_dir_created_by_runner_not_ui` | UI mock 只触发试用；`desktop_trial_runner` 创建 `data/trials/<trial_id>/` 并落日志 |
| `test_stdout_no_json_fallback` | wrapper 自身崩溃 → stdout 无 JSON → UI Toast "试用失败" + stderr 末 5 行 |
| `test_stdout_log_persisted` | 试用结束后 `data/trials/<trial_id>/stdout.log` 与 `stderr.log` 落盘 |
| `test_high_risk_api_detection` | 代码含 `subprocess.run(["code", file])` → 事前对话框列出 "subprocess" 标签 |
| `test_cleanup_after_7_days` | mtime > 7 天的 trial 目录被启动期 cleanup 删除 |

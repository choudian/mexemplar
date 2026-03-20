# LLM Review 设计

本文档为架构 v2 优先级8的细化设计，定义 LLM Review 的触发时机、输入构造、Prompt 设计及与 Orchestrator 的集成方式。

依赖：[Agent Loop 设计](agent_loop_design.md)、[事件系统设计](event_system_design.md)、[程序员 Agent 设计](programmer_agent_design.md)

---

## 一、整体定位

LLM Review 是程序员生成代码后、工具入库前的一道质量关卡。

**核心约束：**
- **不是独立 Agent** — 就是一次 LLM 调用，没有 while 循环，没有工具集
- **只关注硬伤** — 5 类明确定义的问题，代码风格、注释质量、小瑕疵一律不管
- **最多打回 3 次** — 程序员最多犯 3 次错，第 4 次 Review 失败强制入库（pending），后面还有用户试用兜底
- **Review 失败不终止流程** — 打回给程序员修改，程序员带着完整历史上下文重新来

```
程序员提交代码（submit_code）
  → Orchestrator._run_review(code_data)
  → LLMReviewer.review(code, requirement)
      → 一次 LLM 调用
      → 返回 ReviewResult(passed, feedback)
  → passed=True → 工具入库（pending）→ 结束
  → passed=False，retry_count < 4 → 发回程序员修改 → 程序员重新运行
  → passed=False，retry_count >= 4 → 强制入库（pending）→ 结束
```

---

## 二、Review 的输入

Reviewer 接收两份数据：

### 2.1 代码

程序员通过 `submit_code` 提交的完整 Python 代码（`async def execute(**kwargs)` 格式）。

### 2.2 需求信息

从 `submit_code` 的 `code_data` 中提取，包含：
- **description** — 程序员写的工具功能描述（一句话，表达工具的目的，用于理解代码意图）
- **parameters** — 完整参数列表（用于验证参数是否全部被使用）

`code_data` 来自程序员调用 `submit_code` 时的 `signal_tool.args`，Orchestrator 在 `_on_programmer_completed` 中已拿到该结构。**无需额外查询，直接透传给 LLMReviewer。**

**注意**：`submit_code` 的 schema 中没有原始 PM 的 goal 字段，`description` 是程序员自己写的工具功能描述，语义上等价于"这个工具做什么"，足以让 Reviewer 理解代码意图。

### 2.3 为什么不传录制数据

程序员从录制数据中挖出的技术细节（API 端点、响应字段结构、CSS 选择器等）体现在代码里，但 Reviewer 无法重新验证这些数据。

**解决方案：Prompt 划禁区。** 明确告知 Reviewer 这些技术决策已由程序员在录制数据中验证过，不在审查范围内，不得质疑。

---

## 三、Prompt 设计

### 3.1 完整 Prompt

```
你是 Exemplar 的代码审查员。程序员刚刚生成了一个工具代码，请审查是否存在明显的硬伤。

## 工具信息

工具描述：{description}

参数列表：
{parameters_text}

## 待审查代码

```python
{code}
```

## 审查范围

只关注以下 5 类硬伤，发现任意一类才判定不通过：

1. **语法错误** — 代码无法被 Python 解析执行
2. **参数漏用** — 参数列表中的参数有未在代码中使用的（参数名未出现在代码里）
3. **函数签名错误** — 入口函数不是 `async def execute(**kwargs)`
4. **返回格式错误** — 没有返回 `{"success": ..., "message": ..., "data": ...}` 格式的字典
5. **必崩逻辑** — 存在明显会导致运行时崩溃的逻辑（如对 None 直接调用方法、明确的除零等）

代码有小问题、风格不完美、注释不够完整、实现方式不够优雅，都不是打回的理由。

## 不在审查范围内

**以下内容不要质疑**，这些是程序员从录制数据中验证过的技术决策：
- 具体的 URL、API 路径、请求参数名称和格式
- HTTP 响应体的字段结构（如 `response.json()["data"]["items"]`）
- CSS 选择器、DOM 元素属性、页面结构
- 选择 Playwright 还是 requests 的技术方案
- 任何具体的数值、字符串常量

## 输出格式

以 JSON 格式返回，不要包含其他内容：
{"passed": true/false, "feedback": "通过时一句话说明代码可用；不通过时说明具体是哪条硬伤、在代码的哪里"}
```

### 3.2 parameters_text 格式化

`_format_parameters_text` 是 `LLMReviewer` 内部的私有辅助函数，在 `review()` 方法中调用，不在 Orchestrator 层处理：

```python
def _format_parameters_text(self, parameters: list[dict]) -> str:
    """将参数列表格式化为 Reviewer 可读的文本。LLMReviewer 内部使用。"""
    if not parameters:
        return "（无参数）"
    lines = []
    for p in parameters:
        required = "必填" if p.get("required", True) else "选填"
        lines.append(f"- {p['name']}（{required}）：{p.get('description', '')}")
    return "\n".join(lines)
```

### 3.3 Prompt 注入方式

使用 `str.replace()` 逐一替换占位符，不用 `.format()`：

```python
prompt = (
    REVIEW_PROMPT_TEMPLATE
    .replace("{description}", requirement.get("description", ""))
    .replace("{parameters_text}", self._format_parameters_text(requirement.get("parameters", [])))
    .replace("{code}", code)
)
```

**原因**：代码中可能含有 `{` `}` 字符（字典字面量、f-string 等），`.format()` 会将其当成模板变量并抛出 `KeyError`。

---

## 四、输出格式

返回自然语言 feedback，不做类型结构化。

**理由：**
- Orchestrator 对所有失败类型的处理都一样（发回程序员修改），类型信息对路由无影响
- 程序员是 LLM，读自然语言 feedback 和读结构化字段理解能力相同
- 结构化增加 Reviewer 的输出字段，多一个字段就多一个出错点

**`ReviewResult` 结构保持不变：**
```python
@dataclass
class ReviewResult:
    passed: bool
    feedback: str
```

---

## 五、打回消息格式

Review 失败时，Orchestrator 将 feedback 作为 `user_input` 发给程序员：

```python
self.run_agent(
    "programmer",
    f"[LLM Review 第 {retry_count} 次，共最多 3 次]\n\n审查意见：{review_result.feedback}",
    workflow_id,
)
```

加上轮次前缀让程序员知道还有几次机会，不会无限等待。程序员 session 复用，完整的分析历史和上一版代码都在上下文里，Reviewer 的意见作为新 user message 接上。

---

## 六、retry_count 管理

### 6.1 存储方式：内存

```python
self._review_counts: Dict[str, int] = {}  # key: workflow_id
```

**不持久化到数据库。** 理由：
- Review 循环在分钟级内完成，Orchestrator 重启概率极低
- 极端情况重启后计数归零，程序员多改几轮，有试用兜底，代价可接受
- 持久化需要新增数据库字段，维护成本不值

### 6.2 计数规则

retry_count 在每次 Review 失败后递增，**表示已失败的次数**：

| retry_count 值 | 含义 | 动作 |
|--------------|------|------|
| 0 | 尚未失败过 | — |
| 1 | 第 1 次失败 | 打回程序员（还剩 2 次机会） |
| 2 | 第 2 次失败 | 打回程序员（还剩 1 次机会） |
| 3 | 第 3 次失败 | 打回程序员（最后 1 次机会） |
| 4 | 第 4 次失败 | 强制入库，清除计数 |

```python
retry_count = self._review_counts.get(workflow_id, 0)
review_result = self._llm_reviewer.review(code, requirement)

if review_result.passed:
    self._review_counts.pop(workflow_id, None)
    self._save_tool(code_data, workflow_id, from_session_id)
else:
    retry_count += 1
    self._review_counts[workflow_id] = retry_count

    if retry_count < 4:   # 最多打回 3 次（retry_count 1/2/3 时打回）
        self.run_agent("programmer", f"[LLM Review 第 {retry_count} 次，共最多 3 次]\n\n审查意见：{review_result.feedback}", workflow_id)
    else:                  # retry_count == 4，强制入库
        self._review_counts.pop(workflow_id, None)
        self._save_tool(code_data, workflow_id, from_session_id)
```

### 6.3 强制入库说明

第 4 次 Review 失败后的代码以 `pending` 状态入库，与正常通过的代码没有状态区别。后面的试用 Agent 是真正的功能验证关卡，LLM Review 只是提前拦截明显的硬伤，不是最终裁判。

---

## 七、与 Orchestrator 的集成

### 7.1 LLMReviewer 接口

```python
class LLMReviewer:
    def review(self, code: str, requirement: dict) -> ReviewResult:
        """
        Args:
            code: 程序员提交的完整 Python 代码
            requirement: 需求信息，包含 description 和 parameters 字段
                - description: 工具功能描述（来自 submit_code）
                - parameters: 完整参数列表（来自 submit_code）

        Returns:
            ReviewResult(passed, feedback)
        """
```

### 7.2 _run_review 调用方式

```python
def _run_review(self, code_data: dict, from_session_id: str, workflow_id: str) -> None:
    code = code_data["code"]
    requirement = {
        "description": code_data.get("description", ""),
        "parameters": code_data.get("parameters", []),
    }
    retry_count = self._review_counts.get(workflow_id, 0)
    review_result = self._llm_reviewer.review(code, requirement)
    # ... 后续逻辑按 6.2 执行
```

### 7.3 Review 失败时的事件

```python
emit(
    "review_failed",
    sender=self,
    workflow_id=workflow_id,
    session_id=from_session_id,
    code=code,
    feedback=review_result.feedback,
    retry_count=retry_count,
    forced_save=(retry_count >= 4),  # 标记是否为强制入库
)
```

---

## 八、边界情况

### 8.1 Review 服务异常

LLM 调用失败（网络超时、API 错误等）时，默认通过，不阻断流程：

```python
except Exception as e:
    logger.error(f"[LLMReviewer] Review 调用失败: {e}")
    return ReviewResult(passed=True, feedback=f"Review 服务异常，默认通过: {e}")
```

### 8.2 JSON 解析失败

Reviewer 返回的不是合法 JSON 时，降级处理：
1. 尝试从 markdown 代码块中提取 JSON
2. 仍失败则关键词匹配（"passed: false"、"failed"）
3. 都失败则默认通过

### 8.3 参数漏用的判断方式

Reviewer 通过 LLM 自然语言理解判断参数是否被使用，不是机械的字符串搜索——LLM 能识别 `kwargs.get("keyword")` 和直接引用 `keyword` 都算"使用了该参数"。

---

## 九、文件结构

```
src/
  business/orchestration/
    llm_reviewer.py          # 修改：接收 requirement 参数，更新 Prompt，加 _format_parameters_text
    agent_orchestrator.py    # 修改：_run_review 传入 requirement；打回阈值 < 4；打回消息加轮次前缀
```

---

## 十、与架构 v2 的关系

### 一致的决策

- 不是独立 Agent，就是一次 LLM 调用
- 只关注硬伤（逻辑错误、参数漏用、明显 bug），不管代码风格
- 最多打回 3 次，超过直接入库（pending），后面还有用户试用兜底

### 本设计新增/细化的决策

| 决策 | 架构 v2 原文 | 本设计 |
|------|-------------|--------|
| Reviewer 输入 | 未明确 | 代码 + description + parameters（均来自 submit_code.args，无需额外查询） |
| 录制数据相关决策 | 未明确 | Prompt 划禁区：URL、API路径、响应字段结构、CSS选择器不质疑 |
| 检查项 | "逻辑错误、参数漏用、明显 bug" | 细化为 5 类：语法错误、参数漏用、函数签名、返回格式、必崩逻辑 |
| 打回次数阈值 | "最多打回 3 次" | retry_count < 4（程序员最多犯 3 次错，第 4 次失败强制入库） |
| 输出格式 | 未明确 | 自然语言 feedback，不结构化 |
| 打回消息 | 未明确 | 加轮次前缀（第 N 次，共最多 3 次），让程序员感知进度 |
| retry_count 存储 | 未明确 | 内存存储（Dict[workflow_id, int]），不持久化 |
| Review 异常 | 未明确 | 默认通过，不阻断流程 |
| Prompt 注入方式 | 未明确 | str.replace() 替换占位符，避免代码中花括号触发 format 异常 |

---

*基于架构 v2 细化，记录时间：2026-03-20*

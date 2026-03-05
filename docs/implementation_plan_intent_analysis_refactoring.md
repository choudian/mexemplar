# 实施计划：改进意图分析和代码生成

## 📋 需求重述

改进意图分析和代码生成的提示词和流程，解决以下问题：

1. **统一输出结构**：意图分析输出"执行蓝图"，包含代码生成所需的完整信息
2. **隐含需求挖掘**：主动识别用户未明确表达的隐含需求（如搜索结果如何处理）
3. **问题分级机制**：High/Medium/Low 三级，避免无限提问
4. **停止条件**：没有 High 问题或 Medium ≤2 时停止提问
5. **去技术化表达**：确认问题用自然语言，避免技术术语
6. **支持打断**：用户可随时打断，基于已有信息生成最终蓝图

---

## 🚀 实施阶段

### 阶段1：数据结构设计

#### 步骤1.1：定义执行蓝图数据结构

在 `src/business/agent/state.py` 中添加：

```python
@dataclass
class ExecutionBlueprint:
    """执行蓝图：代码生成需要的完整信息"""
    tool_name: str
    tool_summary: str
    category: str
    input_parameters: List[ParameterSpec]
    output_spec: OutputSpec
    execution_steps: List[ExecutionStep]
    execution_environment: ExecutionEnvironment
    implicit_requirements: List[str]
    edge_cases: List[str]

@dataclass
class ParameterSpec:
    name: str
    label: str
    type: str
    required: bool
    default_value: Any = None
    description: str = ""
    example: str = ""
    validation: str = ""

@dataclass
class OutputSpec:
    data_type: str
    description: str
    fields: Dict[str, FieldSpec] = None
    item_type: str = None
    item_fields: Dict[str, FieldSpec] = None

@dataclass
class ExecutionStep:
    step_number: int
    step_name: str
    action_type: str
    description: str
    parameters: Dict[str, Any]
    locator_info: LocatorInfo = None

@dataclass
class ExecutionEnvironment:
    required_libraries: List[str]
    python_version: str = "3.11"
    platform_config: Dict[str, Any] = None

@dataclass
class FieldSpec:
    type: str
    description: str
    required: bool = True
```

#### 步骤1.2：修改 IntentAnalysisResult

在 `state.py` 中修改：

```python
@dataclass
class IntentAnalysisResult:
    # 保留原有字段
    pattern_recognition: PatternRecognition
    surface_operations: List[str]
    deep_intent: str
    final_goal: str
    user_needs: str
    parameterization_analysis: List[ParameterizationItem]
    confirmation_questions: List[ConfirmationQuestion]

    # 新增执行蓝图
    execution_blueprint: ExecutionBlueprint

    # 保留原有字段（向下兼容）
    tool_description: ToolDescription = None
    libraries_needed: List[str] = None
    complexity: str = None
    error_handling_needed: List[str] = None
    special_considerations: List[str] = None
```

#### 步骤1.3：修改 ConfirmationQuestion

增加 `priority` 字段：

```python
@dataclass
class ConfirmationQuestion:
    id: str
    question: str
    context: str
    options: List[Dict[str, str]]
    recommended: str
    priority: str  # "high" | "medium" | "low"
```

---

### 阶段2：修改意图分析提示词

#### 步骤2.1：增加问题分级机制

在 `src/business/agent/prompts/intent_analysis.py` 中增加：

```python
【确认问题生成规则】

问题优先级分为三级：
- High（高优先级）：必须生成确认问题
- Medium（中优先级）：可选生成，最多保留 2 个
- Low（低优先级）：不生成，直接使用推荐值

【High 优先级判断标准】
如果问题影响以下任一要素，则为 High 优先级：
- 函数参数的增减（例如：是否需要 max_results 参数）
- 函数返回值结构（例如：返回数组还是对象）
- 主要执行逻辑分支（例如：是否需要循环、是否需要跳转页面）
- 代码执行方式（例如：是单次操作还是批量操作）

【Medium 优先级判断标准】
如果问题只影响以下要素，则为 Medium 优先级：
- 错误处理方式
- 超时配置
- 翻页逻辑
- 容错机制

【Low 优先级判断标准】
如果问题满足以下任一条件，则为 Low 优先级，不生成确认问题：
- 有明确的最佳实践（如重试次数 3 次、超时 30 秒）
- 不影响核心功能
- 可以在代码中用默认值

【提问停止条件】
当满足以下任一条件时，停止生成确认问题：
1. 没有 High 优先级问题
2. High 优先级问题已全部解决，且 Medium 优先级问题 ≤ 2 个

【推荐值示例】
- 重试次数：3次
- 等待超时：30秒
- 浏览器模式：非 headless
- 截图保存：不保存
```

#### 步骤2.2：增加隐含需求挖掘

在提示词中增加：

```python
步骤3：挖掘隐含需求

【隐含需求挖掘原则】
- 用户录制的操作是"示例"，你要生成的是"通用工具"
- 对于每个操作模式，必须主动思考可能的隐含需求

【搜索模式的隐含需求】
必须确认：
1. 搜索结果如何处理？
   - 提取数据：提取几条？哪些字段？
   - 点击详情：进入哪个结果页？提取什么？
   - 仅浏览：返回什么信息？

2. 是否需要翻页？如果需要，翻几页？

3. 搜索失败如何处理？（无结果/超时/验证码）

【列表采集模式的隐含需求】
必须确认：
1. 采集数量上限？采集所有还是限制数量？
2. 采集哪些字段？
3. 是否需要进入详情页？
4. 分页如何处理？

【表单填写模式的隐含需求】
必须确认：
1. 提交后如何处理结果？
   - 返回提交状态
   - 跳转到结果页
   - 截图确认
2. 表单验证失败如何处理？

如果不确定，必须生成确认问题（High 优先级）。但用户打断后，必须基于已有信息，给出一个合理的默认值。
```

#### 步骤2.3：增加执行蓝图输出格式

```python
步骤6：生成执行蓝图

执行蓝图中必须包含：
1. 工具名称和描述
2. 完整的输入参数列表（包括类型、默认值、验证规则）
3. 输出规范（返回什么数据、数据结构）
4. 详细的执行步骤（每个步骤的操作类型和参数）
5. 执行环境要求（需要的库）
6. 隐含需求列表
7. 边界情况列表

【输出格式】

```json
{
  "execution_blueprint": {
    "tool_name": "工具名称",
    "tool_summary": "一句话描述工具功能",
    "category": "browser_automation",

    "input_parameters": [
      {
        "name": "参数名",
        "label": "参数显示标签",
        "type": "string",
        "required": true,
        "default_value": "默认值",
        "description": "参数描述",
        "example": "示例值",
        "validation": "验证规则"
      }
    ],

    "output_spec": {
      "data_type": "array",
      "description": "输出描述",
      "item_type": "object",
      "item_fields": {
        "title": {"type": "string", "description": "标题"},
        "url": {"type": "string", "description": "链接"},
        "snippet": {"type": "string", "description": "摘要"}
      }
    },

    "execution_steps": [
      {
        "step_number": 1,
        "step_name": "步骤名称",
        "action_type": "browser_navigate",
        "description": "步骤描述",
        "parameters": {
          "url": "https://www.baidu.com"
        }
      }
    ],

    "execution_environment": {
      "required_libraries": ["playwright", "asyncio"],
      "python_version": "3.11",
      "platform_config": {
        "browser": "chromium",
        "headless": false
      }
    },

    "implicit_requirements": [
      "需要等待搜索结果加载完成",
      "需要处理搜索结果为空的情况"
    ],

    "edge_cases": [
      "搜索结果为空",
      "网络超时",
      "元素定位失败"
    ]
  }
}
```
```

#### 步骤2.4：增加确认问题表达规范

```python
【确认问题表达规范】

问题表达原则：
1. 完全去技术化，用普通用户能理解的语言
2. 每个选项都要有清晰的说明和具体例子
3. 使用"你想做什么？"这类表述，而不是技术术语

【问题表达模板】

```json
{
  "question": "用自然语言描述问题（你想做什么？）",
  "context": "为什么需要这个问题（用自然语言解释）",
  "options": [
    {
      "value": "内部值",
      "label": "用户看到的选项",
      "description": "这个选项的具体作用（自然语言）",
      "example": "具体例子（让用户有代入感）"
    }
  ],
  "recommended": "推荐的选项值",
  "priority": "high"
}
```

【禁止使用的技术术语】

❌ 不允许使用：
- 函数、参数、返回值
- 循环、遍历、迭代
- 数组、列表、字典
- API、接口、请求
- 选择器、DOM、XPath

✅ 可以使用：
- 结果、信息、数据
- 列表、条目、项目
- 页面、链接、标题
- 提交、输入、选择

【示例对比】

❌ 错误示例：
```json
{
  "question": "函数返回值是什么结构？",
  "options": [
    {"label": "数组", "description": "返回一个数组对象"}
  ]
}
```

✅ 正确示例：
```json
{
  "question": "搜索结果出来后，你想得到什么？",
  "options": [
    {
      "label": "一个结果列表",
      "description": "我会把搜索结果整理成一个列表给你",
      "example": "比如搜索'Python'，会返回10条相关结果的信息"
    }
  ]
}
```
```

---

### 阶段3：修改意图分析节点

#### 步骤3.1：解析执行蓝图

在 `src/business/agent/nodes/intent_analysis.py` 的 `_build_full_analysis` 函数中增加：

```python
# 解析执行蓝图
blueprint_data = result.get("execution_blueprint", {})
execution_blueprint = _build_execution_blueprint(blueprint_data)
```

#### 步骤3.2：构建执行蓝图对象

添加 `_build_execution_blueprint` 函数：

```python
def _build_execution_blueprint(data: Dict[str, Any]) -> ExecutionBlueprint:
    """从 LLM 响应构建执行蓝图"""
    return ExecutionBlueprint(
        tool_name=data.get("tool_name", ""),
        tool_summary=data.get("tool_summary", ""),
        category=data.get("category", "browser_automation"),
        input_parameters=_build_parameters(data.get("input_parameters", [])),
        output_spec=_build_output_spec(data.get("output_spec", {})),
        execution_steps=_build_execution_steps(data.get("execution_steps", [])),
        execution_environment=_build_execution_env(data.get("execution_environment", {})),
        implicit_requirements=data.get("implicit_requirements", []),
        edge_cases=data.get("edge_cases", [])
    )
```

---

### 阶段4：修改意图确认节点

#### 步骤4.1：打断时生成最终执行蓝图

在 `src/business/agent/nodes/intent_confirmation.py` 中，当用户打断时调用 `_generate_final_blueprint` 函数：

```python
def _generate_final_blueprint(
    current_intent: IntentData,
    user_answers: Dict[str, str]
) -> ExecutionBlueprint:
    """基于已有信息生成最终执行蓝图

    用户打断时调用：
    - 合并用户确认的答案
    - 为未确认的隐含需求给出合理默认值
    - 完善执行蓝图的完整性
    """
    blueprint = current_intent.full_analysis.execution_blueprint

    # 根据用户答案更新蓝图
    blueprint = _apply_user_answers(blueprint, user_answers, current_intent.full_analysis.confirmation_questions)

    # 补充未确认的隐含需求
    blueprint = _fill_implicit_requirements(blueprint)

    # 补充边界情况
    blueprint = _fill_edge_cases(blueprint)

    return blueprint
```

#### 步骤4.2：展示最终执行蓝图

在 `_build_interrupt_data` 中增加最终执行蓝图的展示（去技术化）：

```python
def _build_final_blueprint_display(blueprint: ExecutionBlueprint) -> str:
    """构建最终执行蓝图的展示文本（去技术化）"""
    parts = []

    parts.append(f"**工具名称**：{blueprint.tool_name}")
    parts.append(f"\n**这个工具会做什么**：\n{blueprint.tool_summary}")

    parts.append("\n**你需要输入**：")
    for param in blueprint.input_parameters:
        required = "（必填）" if param.required else f"（可选，默认：{param.default_value}）"
        parts.append(f"• {param.label} {required}")

    parts.append("\n**你会得到**：")
    parts.append(blueprint.output_spec.description)

    if blueprint.implicit_requirements:
        parts.append("\n**注意事项**：")
        for req in blueprint.implicit_requirements:
            parts.append(f"• {req}")

    return "\n".join(parts)
```

---

### 阶段5：修改代码生成节点

#### 步骤5.1：从执行蓝图获取信息

修改 `src/business/agent/nodes/code_generation.py`：

```python
def code_generation_node(state: AgentState) -> Dict[str, Any]:
    """代码生成节点"""
    current_intent = state.get("current_intent")

    # 从执行蓝图获取所有信息
    blueprint = current_intent.full_analysis.execution_blueprint

    # 生成提示词
    prompt = get_code_generation_prompt(
        blueprint=blueprint,
        recording_data=state.get("recording_data")
    )

    # 调用 LLM 生成代码...
```

#### 步骤5.2：简化代码生成提示词

修改 `src/business/agent/prompts/code_generation.py`：

```python
def get_code_generation_prompt(
    blueprint: ExecutionBlueprint,
    recording_data: Dict[str, Any]
) -> str:
    """生成代码生成提示词

    基于执行蓝图生成代码，不再做需求分析
    """
    prompt = """你是一个 Python 程序员。
根据以下【执行蓝图】，生成可执行的 Playwright 代码。

【执行蓝图】
工具名称：{tool_name}
功能描述：{tool_summary}

输入参数：
{input_parameters}

输出规范：
{output_spec}

执行步骤：
{execution_steps}

执行环境：
- 需要的库：{libraries}

隐含需求：
{implicit_requirements}

【代码要求】
1. 代码必须独立运行（不依赖 src 模块）
2. 使用 playwright.async_api
3. 函数签名：async def execute(**kwargs) -> Dict[str, Any]
4. 返回格式：{"success": bool, "data": any, "message": str}
5. 处理隐含需求和边界情况

请生成完整的 Python 代码：
"""

    return prompt.format(
        tool_name=blueprint.tool_name,
        tool_summary=blueprint.tool_summary,
        input_parameters=_format_parameters(blueprint.input_parameters),
        output_spec=_format_output(blueprint.output_spec),
        execution_steps=_format_steps(blueprint.execution_steps),
        libraries=", ".join(blueprint.execution_environment.required_libraries),
        implicit_requirements="\n".join(blueprint.implicit_requirements)
    )
```

---

## 📊 依赖关系

```
阶段1（数据结构） → 阶段2（提示词） → 阶段3（意图分析节点） → 阶段4（确认节点） → 阶段5（代码生成节点）
```

各阶段必须按顺序完成，因为：
- 阶段2 需要阶段1 定义的数据结构
- 阶段3 需要阶段2 修改的提示词输出格式
- 阶段4 需要阶段3 构建的执行蓝图
- 阶段5 需要阶段4 最终确认的执行蓝图

---

## ⚠️ 风险评估

| 风险 | 级别 | 缓解措施 |
|-----|-----|---------|
| LLM 不遵循问题分级规则 | Medium | 增加示例，强化停止条件的说明 |
| 确认问题仍然技术化 | Medium | 提供正反示例，明确禁止术语列表 |
| 执行蓝图信息不完整 | High | 在打断时增加补全逻辑，给出合理默认值 |
| 两次 LLM 调用信息传递不畅 | Low | 执行蓝图包含完整信息，代码生成不再分析 |
| 向下兼容问题 | Medium | 保留旧字段，逐步迁移 |

---

## 📈 复杂度评估

| 阶段 | 复杂度 | 预计时间 |
|-----|-------|---------|
| 阶段1：数据结构设计 | Low | 0.5-1小时 |
| 阶段2：修改提示词 | Medium | 1-2小时 |
| 阶段3：修改意图分析节点 | Medium | 1-2小时 |
| 阶段4：修改确认节点 | High | 2-3小时 |
| 阶段5：修改代码生成节点 | Medium | 1-2小时 |
| 测试验证 | High | 2-3小时 |
| **总计** | **Medium-High** | **8-13小时** |

---

## ✅ 验收标准

1. 意图分析能正确输出执行蓝图
2. 确认问题按照 High/Medium/Low 分级
3. 没有 High 问题时停止提问
4. 确认问题使用自然语言，无技术术语
5. 用户打断后能生成完整的最终执行蓝图
6. 代码生成能从执行蓝图获取所有必要信息
7. 最终生成的工具功能符合用户预期
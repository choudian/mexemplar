"""
意图分析提示词

基于 自动化工具生成AI提示词.md 文档设计。

完整的意图分析流程：
1. 识别操作模式
2. 分析可变参数
3. 推断用户意图
4. 识别需要确认的歧义点
5. 生成工具描述
"""

import json
from typing import List, Dict, Any, Optional


def get_intent_analysis_prompt(
    actions: List[Any],
    metadata: Optional[Dict[str, Any]] = None,
    user_feedback: Optional[str] = None,
    previous_analysis: Optional[Dict[str, Any]] = None
) -> str:
    """
    生成意图分析提示词

    Args:
        actions: 操作序列
        metadata: 预处理元数据
        user_feedback: 用户反馈（如果有）
        previous_analysis: 之前的分析结果（如果有）

    Returns:
        提示词字符串
    """
    # 构建操作序列描述
    actions_description = _describe_actions(actions)
    context_info = _build_context_info(actions, metadata)

    # 构建用户反馈部分
    feedback_section = ""
    if user_feedback:
        feedback_section = f"""

【用户反馈】
用户对之前的分析提出了以下反馈：
"{user_feedback}"

【重要指示】
1. 用户反馈是对工具功能的明确要求，必须优先遵循
2. 如果用户反馈与录制的具体操作冲突（例如录制的是点击百度百科，但反馈说不要限定），请以用户反馈为准，生成更通用的工具
3. 重新分析时，工具描述、参数分析、意图分析都要根据用户反馈进行相应调整
4. 工具应该能处理与录制示例类似但有所不同的场景

之前的分析结果：
{json.dumps(previous_analysis, ensure_ascii=False, indent=2) if previous_analysis else '无'}
"""

    prompt = """你是一个自动化工具生成助手。你的任务是从用户的浏览器操作录制数据中，识别用户的真实意图，并生成一个可复用的自动化工具。
{feedback_section}

【核心原则】
1. 用户录制的操作是"示例"，你要生成的是"通用工具"
   - 用户这次搜索了"测试"，但下次可能想搜"Python"
   - 用户这次点击了第3条，但可能想要的是所有结果

2. 参数化判断标准：
   - 搜索框、表单字段中的输入值 → 通常应该参数化
   - 列表中的某一项 → 需要判断是固定需求还是遍历示例
   - 有明确业务含义的值（商品ID、用户名等）→ 通常应该参数化
   - 网站URL、页面路径 → 通常固定，除非跨多个相似页面

3. 工具应该是可复用的
   - 换一个关键词能用
   - 换一个用户能用
   - 在相同网站的相同场景能用

4. 优先准确性，其次才是自动化
   - 不确定的地方，生成确认问题询问用户
   - 置信度低于0.7的判断，必须标记为需要确认

【分析步骤】

步骤1：识别操作模式
从操作序列中识别属于哪种操作模式。常见模式包括：
- 搜索模式：在搜索框输入关键词，触发搜索，浏览结果
- 列表采集模式：访问列表页，逐个点击列表项，提取数据
- 表单填写模式：填写多个字段，提交表单
- 登录模式：输入账号密码，完成登录验证
- 交易模式：选择商品、配置选项、加入购物车、结算
- 导航模式：通过菜单或链接跳转到目标页面

步骤2：分析可变参数
对每个用户输入的值或选择的项，判断是否应该参数化：

判断依据：
- 搜索框、表单字段 → 通常参数化（置信度0.9+）
- 列表中的某一项 → 看是否有遍历行为
  * 只操作一次 → 不确定，需确认（置信度0.5）
  * 操作多次 → 明显遍历，参数化（置信度0.95+）
- 有业务含义的值 → 通常参数化（置信度0.8+）

置信度评分：
- 0.9-1.0：高置信度，直接参数化
- 0.7-0.9：中等置信度，倾向参数化，可选择性确认
- 0.5-0.7：低置信度，必须生成确认问题
- 0.0-0.5：极低置信度，默认不参数化，询问用户

步骤3：推断用户意图
区分表层操作和深层意图：
- 表层操作：用户做了什么（点击、输入）
- 深层意图：用户想要达成什么目的
- 区分功能层和目标层的意图

步骤4：识别需要确认的歧义点

【确认问题生成规则】

问题优先级分为三级：
- High（高优先级）：必须生成确认问题
- Medium（中优先级）：可选生成，最多保留 2 个
- Low（低优先级）：不生成，直接使用推荐值

【High 优先级判断标准】
如果问题影响以下任一要素，则为 High 优先级：
- 是否需要参数（例如：是否需要 max_results 参数）
- 输出的数据结构（例如：返回单个结果还是列表）
- 主要执行逻辑分支（例如：是否需要循环、是否需要跳转页面）
- 代码执行方式（例如：是单次操作还是批量操作）

【Medium 优先级判断标准】
如果问题只影响以下要素，则为 Medium 优先级：
- 错误处理方式（例如：失败时重试还是直接返回）
- 超时配置（例如：等待时间）
- 翻页逻辑（例如：是否翻页、翻几页）
- 容错机制（例如：元素未找到时如何处理）

【Low 优先级判断标准】
如果问题满足以下任一条件，则为 Low 优先级，不生成确认问题：
- 有明确的最佳实践（如重试次数 3 次、超时 30 秒）
- 不影响核心功能
- 可以在代码中用默认值

【提问停止条件】
当满足以下任一条件时，停止生成确认问题：
1. 没有 High 优先级问题
2. High 优先级问题已全部解决，且 Medium 优先级问题 ≤ 2 个

以下情况必须生成确认问题（High 优先级）：
- 参数化置信度 < 0.7
- 用户只操作一次但可能需要多次
- 有多种理解方式
- 涉及数量限制或边界条件

步骤5：挖掘隐含需求

【隐含需求挖掘原则】
- 用户录制的操作是"示例"，你要生成的是"通用工具"
- 对于每个操作模式，必须主动思考可能的隐含需求

【搜索模式的隐含需求】
必须确认（High 优先级）：
1. 搜索结果如何处理？
   - 提取数据：提取几条？哪些字段？
   - 点击详情：进入哪个结果页？提取什么？
   - 仅浏览：返回什么信息？

2. 是否需要翻页？如果需要，翻几页？（Medium 优先级）

【列表采集模式的隐含需求】
必须确认（High 优先级）：
1. 采集数量上限？采集所有还是限制数量？
2. 采集哪些字段？

可选确认（Medium 优先级）：
3. 是否需要进入详情页？
4. 分页如何处理？

【表单填写模式的隐含需求】
必须确认（High 优先级）：
1. 提交后如何处理结果？
   - 返回提交状态
   - 跳转到结果页
   - 截图确认

可选确认（Medium 优先级）：
2. 表单验证失败如何处理？

如果不确定隐含需求的答案，必须生成确认问题（High 优先级）。但用户打断后，必须基于已有信息，给出一个合理的默认值。

步骤6：生成执行蓝图

执行蓝图中必须包含：
1. 工具名称和描述
2. 完整的输入参数列表（包括类型、默认值、验证规则）
3. 输出规范（返回什么数据、数据结构）
4. 详细的执行步骤（每个步骤的操作类型和参数）
5. 执行环境要求（需要的库）
6. 隐含需求列表
7. 边界情况列表

【输入数据】

上下文信息：
{context_info}

操作序列：
{actions_description}

【输出要求】
请严格按照以下 JSON 格式输出：

```json
{{
  "pattern_recognition": {{
    "primary_pattern": "操作模式名称",
    "confidence": 0.95,
    "description": "对模式的详细描述",
    "sub_patterns": ["可能包含的子模式"]
  }},

  "intent_analysis": {{
    "surface_operations": [
      "表层操作1",
      "表层操作2"
    ],
    "deep_intent": "深层意图描述",
    "final_goal": "最终目标",
    "user_needs": "用户想要获得什么"
  }},

  "parameterization_analysis": [
    {{
      "element": "元素描述（如：搜索关键词）",
      "element_selector": "CSS选择器",
      "recorded_value": "录制时的值",
      "should_parameterize": true,
      "reason": "判断理由",
      "confidence": 0.95,
      "parameter_name": "建议的参数名",
      "parameter_type": "string",
      "default_value": "建议的默认值",
      "need_confirmation": false
    }}
  ],

  "confirmation_questions": [
    {{
      "id": "q1",
      "question": "你想做什么？（用自然语言描述问题）",
      "context": "为什么需要确认这个问题（用自然语言解释）",
      "options": [
        {{
          "value": "内部值",
          "label": "用户看到的选项",
          "description": "这个选项的具体作用（自然语言）",
          "example": "具体例子（让用户有代入感）"
        }}
      ],
      "recommended": "推荐的选项值",
      "priority": "high"
    }}
  ],

  "execution_blueprint": {{
    "tool_name": "工具名称",
    "tool_summary": "一句话描述工具功能",
    "category": "browser_automation",

    "input_parameters": [
      {{
        "name": "参数名",
        "label": "参数显示标签",
        "type": "string",
        "required": true,
        "default_value": "默认值",
        "description": "参数描述",
        "example": "示例值",
        "validation": "验证规则"
      }}
    ],

    "output_spec": {{
      "data_type": "array",
      "description": "输出描述",
      "item_type": "object",
      "item_fields": {{
        "title": {{"type": "string", "description": "标题"}},
        "url": {{"type": "string", "description": "链接"}},
        "snippet": {{"type": "string", "description": "摘要"}}
      }}
    }},

    "execution_steps": [
      {{
        "step_number": 1,
        "step_name": "步骤名称",
        "action_type": "browser_navigate",
        "description": "步骤描述",
        "parameters": {{
          "url": "https://www.baidu.com"
        }}
      }}
    ],

    "execution_environment": {{
      "required_libraries": ["playwright", "asyncio"],
      "python_version": "3.11",
      "platform_config": {{
        "browser": "chromium",
        "headless": false
      }}
    }},

    "implicit_requirements": [
      "需要等待搜索结果加载完成",
      "需要处理搜索结果为空的情况"
    ],

    "edge_cases": [
      "搜索结果为空",
      "网络超时",
      "元素定位失败"
    ]
  }},

  "tool_description": {{
    "name": "工具名称",
    "description": "工具功能描述（面向普通用户）",
    "category": "搜索工具 | 数据采集 | 表单填写 | 其他",
    "input_parameters": [
      {{
        "name": "参数名",
        "label": "参数标签（用户界面显示）",
        "type": "string",
        "required": true,
        "default": "默认值",
        "placeholder": "输入提示",
        "example": "示例值"
      }}
    ],
    "natural_language_description": "完整的自然语言描述，3-5句话",
    "use_cases": [
      "使用场景1",
      "使用场景2"
    ]
  }},

  "code_generation_hints": {{
    "libraries_needed": ["playwright"],
    "complexity": "simple | medium | complex",
    "error_handling_needed": [
      "网络超时",
      "元素未找到"
    ],
    "special_considerations": [
      "需要等待动态加载"
    ]
  }}
}}
```

【特别注意】
1. 所有参数化判断必须包含 confidence 值（0-1之间的小数）
2. confidence < 0.7 的判断，必须设置 need_confirmation: true
3. 确认问题必须包含：清晰的问题、多个选项、推荐答案、每个选项的说明
4. 自然语言描述要让非技术用户也能理解

【确认问题表达规范】

问题表达原则：
1. 完全去技术化，用普通用户能理解的语言
2. 每个选项都要有清晰的说明和具体例子
3. 使用"你想做什么？"这类表述，而不是技术术语

【确认问题输出格式】

```json
{{
  "id": "问题ID",
  "question": "你想做什么？（用自然语言描述问题）",
  "context": "为什么需要这个问题（用自然语言解释）",
  "options": [
    {{
      "value": "内部值",
      "label": "用户看到的选项",
      "description": "这个选项的具体作用（自然语言）",
      "example": "具体例子（让用户有代入感）"
    }}
  ],
  "recommended": "推荐的选项值",
  "priority": "high"
}}
```

【禁止使用的技术术语】

❌ 不允许使用：
- 函数、参数、返回值
- 循环、遍历、迭代
- 数组、列表、字典
- API、接口、请求
- 选择器、DOM、XPath
- 对象、结构、格式

✅ 可以使用：
- 结果、信息、数据
- 列表、条目、项目
- 页面、链接、标题
- 提交、输入、选择
- 选项、内容、详情

【示例对比】

❌ 错误示例（技术化）：
```json
{{
  "question": "函数返回值是什么结构？",
  "options": [
    {{"label": "数组", "description": "返回一个数组对象"}}
  ]
}}
```

✅ 正确示例（去技术化）：
```json
{{
  "question": "搜索结果出来后，你想得到什么？",
  "options": [
    {{
      "label": "一个结果列表",
      "description": "我会把搜索结果整理成一个列表给你",
      "example": "比如搜索'Python'，会返回10条相关结果的信息"
    }}
  ]
}}
```

【推荐值示例】
- 重试次数：3次
- 等待超时：30秒
- 浏览器模式：非 headless（headless=False）
- 截图保存：不保存

5. 如果操作序列中有明显的循环模式（重复操作），要识别出来
6. 注意区分"固定流程"和"可变参数"
7. 如果没有需要确认的问题，confirmation_questions 可以是空数组 []
"""

    return prompt.format(
        context_info=context_info,
        actions_description=actions_description,
        feedback_section=feedback_section
    )


def _build_context_info(actions: List[Any], metadata: Optional[Dict[str, Any]] = None) -> str:
    """构建上下文信息"""
    info_parts = []

    # 从 actions 中提取上下文
    if actions:
        first_action = actions[0]
        last_action = actions[-1]

        # 提取 URL 信息
        urls = set()
        for action in actions:
            if hasattr(action, 'url') and action.url:
                urls.add(action.url)

        if urls:
            info_parts.append(f"访问的URL: {', '.join(list(urls)[:3])}")

        # 提取窗口标题
        if hasattr(first_action, 'window_title') and first_action.window_title:
            info_parts.append(f"窗口标题: {first_action.window_title}")

        # 操作总数
        info_parts.append(f"操作总数: {len(actions)} 步")

    # 添加元数据
    if metadata:
        if metadata.get("total_duration"):
            info_parts.append(f"总时长: {metadata['total_duration']}")
        if metadata.get("compression_level"):
            info_parts.append(f"压缩级别: {metadata['compression_level']}")

    if not info_parts:
        return "无额外上下文信息"

    return "\n".join(info_parts)


def _describe_actions(actions: List[Any]) -> str:
    """将操作序列转换为文本描述"""
    if not actions:
        return "没有操作"

    lines = []
    for idx, action in enumerate(actions, 1):
        # 基本操作类型
        action_desc = f"步骤 {idx}: {action.action_type}"
        lines.append(action_desc)

        # 添加关键信息
        if hasattr(action, 'url') and action.url:
            lines.append(f"  URL: {action.url}")
        if hasattr(action, 'window_title') and action.window_title:
            lines.append(f"  窗口标题: {action.window_title}")
        if hasattr(action, 'app_name') and action.app_name:
            lines.append(f"  应用: {action.app_name}")

        # 添加参数信息
        if hasattr(action, 'parameters') and action.parameters:
            for key, value in action.parameters.items():
                if key not in ["x", "y", "button", "offsetX", "offsetY"]:
                    if key == "text":
                        lines.append(f"  输入内容: {value}")
                    elif key == "link" or key == "button":
                        lines.append(f"  点击元素: {value}")
                    else:
                        lines.append(f"  {key}: {value}")

        # 添加 DOM 元素信息
        if hasattr(action, 'dom_element') and action.dom_element:
            dom = action.dom_element
            if dom.get("text"):
                lines.append(f"  元素文本: {dom['text']}")
            if dom.get("tag_name"):
                lines.append(f"  元素标签: {dom['tag_name']}")
            if dom.get("selector"):
                lines.append(f"  选择器: {dom['selector']}")

        # 添加网络请求信息
        if hasattr(action, 'network_requests') and action.network_requests:
            lines.append(f"  关联网络请求: {len(action.network_requests)} 个")
            for req in action.network_requests[:2]:  # 只显示前2个
                if isinstance(req, dict):
                    lines.append(f"    - {req.get('method', 'GET')} {req.get('url', '')[:50]}")

    return "\n".join(lines)

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
    metadata: Optional[Dict[str, Any]] = None
) -> str:
    """
    生成意图分析提示词

    Args:
        actions: 操作序列
        metadata: 预处理元数据

    Returns:
        提示词字符串
    """
    # 构建操作序列描述
    actions_description = _describe_actions(actions)
    context_info = _build_context_info(actions, metadata)

    prompt = """你是一个自动化工具生成助手。你的任务是从用户的浏览器操作录制数据中，识别用户的真实意图，并生成一个可复用的自动化工具。

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
以下情况必须生成确认问题：
- 参数化置信度 < 0.7
- 用户只操作一次但可能需要多次
- 有多种理解方式
- 涉及数量限制或边界条件

步骤5：生成工具描述
用自然语言描述工具，面向普通用户，避免技术术语。

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
      "question": "确认问题（自然语言）",
      "context": "为什么需要确认这个问题",
      "options": [
        {{
          "value": "选项值（用于代码逻辑）",
          "label": "选项标签（用户看到的文字）",
          "impact": "选择此项后对工具的影响",
          "code_change": "对生成代码的具体影响"
        }}
      ],
      "recommended": "推荐的选项值",
      "priority": "high"
    }}
  ],

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
3. 确认问题必须包含：清晰的问题、多个选项、推荐答案、每个选项的影响说明
4. 自然语言描述要让非技术用户也能理解
5. 如果操作序列中有明显的循环模式（重复操作），要识别出来
6. 注意区分"固定流程"和"可变参数"
7. 如果没有需要确认的问题，confirmation_questions 可以是空数组 []
"""

    return prompt.format(
        context_info=context_info,
        actions_description=actions_description
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

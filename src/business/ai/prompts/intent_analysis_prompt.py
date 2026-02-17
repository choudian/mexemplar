"""
意图分析提示词

用于从录制数据中提取用户意图信息
"""

# ============================================================================
# 意图分析提示词（主版本）
# ============================================================================

INTENT_ANALYSIS_PROMPT = """你是一个用户意图分析专家。请分析用户的录制操作，提取核心意图信息。

# 核心原则
1. 用户中心：从用户视角理解操作目的，而不是技术视角
2. 简洁准确：核心操作应该简洁明了，避免冗余
3. 层次清晰：区分主要操作和辅助操作
4. 目标导向：聚焦用户想要达成的最终目标

---

# 输入信息

## 录制会话信息
录制ID: {recording_id}
录制模式: {recording_mode}
开始时间: {start_time}
结束时间: {end_time}
总时长: {duration}秒

## 操作序列
{actions_summary}

## 操作详情
{actions_details}

---

# 分析任务

请提取以下信息：

## 1. 核心操作列表 (core_operations)
从操作序列中提取核心步骤，每个操作包含：
- operation: 操作描述（简短，动词开头，如"打开网站"、"点击登录"）
- action_index: 对应的操作索引（从0开始）
- importance: 重要性评分（0.0-1.0）
- parameters: 关键参数（如果有）

**规则**：
- 只保留用户主动触发的操作（click、input、submit）
- 过滤自动操作（scroll、window_switch、background requests）
- 合并连续的同类操作（如多次输入合并为一个表单填写）

## 2. 操作目标 (target)
用户操作的网站或应用名称：
- 网站模式：提取域名或品牌名（如"百度"、"淘宝"）
- 桌面模式：提取应用名称（如"Excel"、"微信"）
- 格式：简洁名称（2-6个字）

## 3. 业务场景 (business_scenario)
识别业务场景类型：
- **用户认证**：登录、注册、登出
- **数据查询**：搜索、筛选、查看详情
- **数据录入**：表单填写、创建记录、上传文件
- **数据处理**：编辑、删除、导出、批量操作
- **数据采集**：爬虫、数据抓取、信息收集
- **流程自动化**：多步骤工作流、审批流程
- **其他**：无法归类到以上场景

**格式**：返回场景名称 + 简短说明

## 4. 预期结果 (expected_results)
用户期望达成的目标（按优先级排序）：
- 主要目标：用户最想达成的结果
- 次要目标：附加的期望结果

**格式**：简洁的描述列表（每条5-15字）

## 5. 智能参数 (suggested_parameters)
识别可作为工具参数的关键信息：
- 用户输入的文本内容（搜索词、表单数据）
- 选择的选项（下拉框、单选框）
- 点击的目标（列表项、按钮、链接）
- 特定的数值或日期

**格式**：
- name: 参数名（英文，snake_case）
- type: 参数类型（text, number, date, url, selection等）
- description: 参数说明
- default_value: 默认值（从录制中提取）
- required: 是否必填

---

# Few-Shot 示例

## 示例1：百度搜索
**输入**：
```
操作1: click（访问百度首页）
操作2: input（在搜索框输入"Python教程"）
操作3: click（点击"百度一下"按钮）
操作4: 网络请求 GET https://www.baidu.com/s?wd=Python教程
```

**输出**：
```json
{{
  "core_operations": [
    {{
      "operation": "打开百度首页",
      "action_index": 0,
      "importance": 0.6,
      "parameters": {{}}
    }},
    {{
      "operation": "输入搜索关键词",
      "action_index": 1,
      "importance": 1.0,
      "parameters": {{"keyword": "Python教程"}}
    }},
    {{
      "operation": "点击搜索按钮",
      "action_index": 2,
      "importance": 0.9,
      "parameters": {{}}
    }}
  ],
  "target": "百度",
  "business_scenario": "数据查询 - 在搜索引擎中查找信息",
  "expected_results": [
    "获取搜索结果列表",
    "找到相关的Python教程资源"
  ],
  "suggested_parameters": [
    {{
      "name": "search_keyword",
      "type": "text",
      "description": "搜索关键词",
      "default_value": "Python教程",
      "required": true
    }}
  ],
  "confidence": 0.95,
  "reasoning": "用户在百度搜索引擎中输入关键词并点击搜索，目标是获取相关搜索结果"
}}
```

## 示例2：用户登录
**输入**：
```
操作1: click（访问登录页面）
操作2: input（输入用户名"admin"）
操作3: input（输入密码"******"））
操作4: click（点击登录按钮）
操作5: 网络请求 POST https://example.com/api/login
```

**输出**：
```json
{{
  "core_operations": [
    {{
      "operation": "打开登录页面",
      "action_index": 0,
      "importance": 0.5,
      "parameters": {{}}
    }},
    {{
      "operation": "输入用户名",
      "action_index": 1,
      "importance": 1.0,
      "parameters": {{"username": "admin"}}
    }},
    {{
      "operation": "输入密码",
      "action_index": 2,
      "importance": 1.0,
      "parameters": {{"password": "******"}}
    }},
    {{
      "operation": "点击登录按钮",
      "action_index": 3,
      "importance": 0.9,
      "parameters": {{}}
    }}
  ],
  "target": "example.com",
  "business_scenario": "用户认证 - 用户登录系统",
  "expected_results": [
    "成功登录系统",
    "跳转到用户首页"
  ],
  "suggested_parameters": [
    {{
      "name": "username",
      "type": "text",
      "description": "用户名或邮箱",
      "default_value": "admin",
      "required": true
    }},
    {{
      "name": "password",
      "type": "text",
      "description": "登录密码",
      "default_value": null,
      "required": true
    }}
  ],
  "confidence": 0.98,
  "reasoning": "用户在登录页面输入凭据并提交，目标是完成身份验证"
}}
```

## 示例3：数据抓取
**输入**：
```
操作1: click（访问商品列表页）
操作2: scroll（向下滚动页面）
操作3: scroll（继续滚动）
操作4: click（点击第一个商品）
操作5: 网络请求 GET https://shop.example.com/api/products?page=1
操作6: 网络请求 GET https://shop.example.com/api/product/123
```

**输出**：
```json
{{
  "core_operations": [
    {{
      "operation": "打开商品列表页",
      "action_index": 0,
      "importance": 0.7,
      "parameters": {{}}
    }},
    {{
      "operation": "浏览商品列表",
      "action_index": 1,
      "importance": 0.4,
      "parameters": {{}}
    }},
    {{
      "operation": "点击查看商品详情",
      "action_index": 3,
      "importance": 0.9,
      "parameters": {{"product_index": 0}}
    }}
  ],
  "target": "电商平台",
  "business_scenario": "数据采集 - 抓取商品信息",
  "expected_results": [
    "获取商品列表数据",
    "提取商品详细信息",
    "保存到本地或数据库"
  ],
  "suggested_parameters": [
    {{
      "name": "page_number",
      "type": "number",
      "description": "页码",
      "default_value": 1,
      "required": false
    }},
    {{
      "name": "product_index",
      "type": "number",
      "description": "商品索引（从0开始）",
      "default_value": 0,
      "required": false
    }}
  ],
  "confidence": 0.85,
  "reasoning": "用户浏览商品列表并点击查看详情，有数据采集的特征（滚动+点击+API请求）"
}}
```

## 示例4：表单填写
**输入**：
```
操作1: click（点击新建按钮）
操作2: input（输入标题"周报"））
操作3: input（输入内容"本周完成..."））
操作4: click（选择部门"技术部"））
操作5: click（点击提交按钮）
操作6: 网络请求 POST https://oa.example.com/api/report/create
```

**输出**：
```json
{{
  "core_operations": [
    {{
      "operation": "点击新建按钮",
      "action_index": 0,
      "importance": 0.6,
      "parameters": {{}}
    }},
    {{
      "operation": "填写标题",
      "action_index": 1,
      "importance": 0.9,
      "parameters": {{"title": "周报"}}
    }},
    {{
      "operation": "填写内容",
      "action_index": 2,
      "importance": 0.9,
      "parameters": {{"content": "本周完成..."}}
    }},
    {{
      "operation": "选择部门",
      "action_index": 3,
      "importance": 0.7,
      "parameters": {{"department": "技术部"}}
    }},
    {{
      "operation": "提交表单",
      "action_index": 4,
      "importance": 1.0,
      "parameters": {{}}
    }}
  ],
  "target": "OA系统",
  "business_scenario": "数据录入 - 创建周报",
  "expected_results": [
    "成功创建周报记录",
    "系统显示提交成功提示"
  ],
  "suggested_parameters": [
    {{
      "name": "title",
      "type": "text",
      "description": "周报标题",
      "default_value": "周报",
      "required": true
    }},
    {{
      "name": "content",
      "type": "text",
      "description": "周报内容",
      "default_value": null,
      "required": true
    }},
    {{
      "name": "department",
      "type": "selection",
      "description": "部门名称",
      "default_value": "技术部",
      "required": false
    }}
  ],
  "confidence": 0.92,
  "reasoning": "用户填写多个表单字段并提交，目标是创建一条新的业务记录"
}}
```

---

# 输出格式

请严格按照以下 JSON 格式输出（不要使用 markdown 代码块，不要添加任何解释文字）：

```json
{{
  "core_operations": [
    {{
      "operation": "操作描述",
      "action_index": 0,
      "importance": 0.0-1.0,
      "parameters": {{}}
    }}
  ],
  "target": "目标网站/应用",
  "business_scenario": "场景类型 - 说明",
  "expected_results": [
    "主要目标",
    "次要目标"
  ],
  "suggested_parameters": [
    {{
      "name": "parameter_name",
      "type": "text|number|date|url|selection",
      "description": "参数说明",
      "default_value": "默认值或null",
      "required": true|false
    }}
  ],
  "confidence": 0.0-1.0,
  "reasoning": "分析推理过程"
}}
```

请开始分析：
"""


# ============================================================================
# 意图确认提示词（用于多轮对话）
# ============================================================================

INTENT_CONFIRMATION_PROMPT = """你是一个用户意图优化专家。请根据用户的反馈，调整意图分析结果。

# 原始分析结果
{original_intent}

# 用户反馈
{user_feedback}

# 对话历史
{conversation_history}

---

# 任务

根据用户反馈，优化意图分析结果：

## 反馈类型

1. **操作调整**：
   - 添加缺失的操作
   - 删除无关的操作
   - 修改操作描述
   - 调整操作顺序

2. **参数补充**：
   - 添加新的参数
   - 修改参数类型或说明
   - 调整默认值

3. **目标修正**：
   - 更正操作目标
   - 调整业务场景
   - 补充预期结果

4. **自然对话**：
   - 用户可能用自然语言描述需求
   - 需要理解并转化为结构化信息

---

# 输出格式

请返回优化后的意图分析结果（JSON格式，不要使用 markdown 代码块）：

```json
{{
  "core_operations": [...],
  "target": "...",
  "business_scenario": "...",
  "expected_results": [...],
  "suggested_parameters": [...],
  "confidence": 0.0-1.0,
  "reasoning": "根据用户反馈进行了哪些调整"
}}
```

## Few-Shot 示例

### 示例1：添加操作
**原始意图**：
```json
{{
  "core_operations": [
    {{"operation": "输入搜索关键词", "action_index": 1, "importance": 1.0}},
    {{"operation": "点击搜索按钮", "action_index": 2, "importance": 0.9}}
  ],
  "target": "百度"
}}
```

**用户反馈**：
```
还需要添加"打开浏览器"这个步骤
```

**优化结果**：
```json
{{
  "core_operations": [
    {{"operation": "打开浏览器", "action_index": -1, "importance": 0.5, "parameters": {{}}}},
    {{"operation": "输入搜索关键词", "action_index": 1, "importance": 1.0, "parameters": {{}}}},
    {{"operation": "点击搜索按钮", "action_index": 2, "importance": 0.9, "parameters": {{}}}}
  ],
  "target": "百度",
  "confidence": 0.95,
  "reasoning": "根据用户反馈，在操作序列开始处添加了'打开浏览器'步骤"
}}
```

### 示例2：参数补充
**原始意图**：
```json
{{
  "suggested_parameters": [
    {{"name": "keyword", "type": "text", "description": "搜索关键词"}}
  ]
}}
```

**用户反馈**：
```
我需要限定搜索时间范围，比如只搜索最近一周的内容
```

**优化结果**：
```json
{{
  "suggested_parameters": [
    {{"name": "keyword", "type": "text", "description": "搜索关键词", "required": true}},
    {{"name": "time_range", "type": "selection", "description": "时间范围", "default_value": "最近一周", "required": false, "options": ["最近一天", "最近一周", "最近一月", "全部"]}}
  ],
  "confidence": 0.9,
  "reasoning": "根据用户反馈，添加了时间范围参数，支持按时间筛选搜索结果"
}}
```

### 示例3：自然语言理解
**原始意图**：
```json
{{
  "core_operations": [
    {{"operation": "输入搜索关键词", "action_index": 1}},
    {{"operation": "点击搜索按钮", "action_index": 2}}
  ],
  "target": "百度"
}}
```

**用户反馈**：
```
我希望能够记住密码，下次不用重新输入
```

**优化结果**：
```json
{{
  "core_operations": [
    {{"operation": "输入搜索关键词", "action_index": 1, "importance": 1.0, "parameters": {{}}}},
    {{"operation": "点击搜索按钮", "action_index": 2, "importance": 0.9, "parameters": {{}}}},
    {{"operation": "勾选记住密码", "action_index": 3, "importance": 0.7, "parameters": {{"remember_password": true}}}}
  ],
  "target": "百度",
  "expected_results": [
    "获取搜索结果列表",
    "系统记住密码以便下次自动登录"
  ],
  "suggested_parameters": [
    {{"name": "remember_password", "type": "boolean", "description": "是否记住密码", "default_value": true, "required": false}}
  ],
  "confidence": 0.85,
  "reasoning": "用户希望添加记住密码功能，因此在操作列表中添加了勾选操作，并添加了相应的布尔参数"
}}
```

请开始优化：
"""


# ============================================================================
# 辅助函数：格式化录制数据
# ============================================================================

def format_recording_data(session_data: dict) -> dict:
    """
    格式化录制数据用于提示词

    Args:
        session_data: 录制会话数据

    Returns:
        格式化后的数据字典
    """
    actions = session_data.get("actions", [])

    # 生成操作摘要
    actions_summary = []
    for i, action in enumerate(actions):
        action_type = action.get("action_type", "unknown")
        url = action.get("url", "")
        app_name = action.get("app_name", "")

        # 根据操作类型生成摘要
        if action_type == "click":
            target = url or app_name or "页面元素"
            summary = f"操作{i+1}: click（点击 {target}）"
        elif action_type == "keyboard_input":
            value = action.get("parameters", {}).get("value", "")
            # 隐藏敏感信息
            if any(keyword in str(value).lower() for keyword in ["password", "passwd", "pwd", "密码"]):
                value = "******"
            summary = f"操作{i+1}: input（输入 {value}）"
        elif action_type == "scroll":
            summary = f"操作{i+1}: scroll（滚动页面）"
        elif action_type == "window_switch":
            title = action.get("window_title", "")
            summary = f"操作{i+1}: window_switch（切换到 {title}）"
        else:
            summary = f"操作{i+1}: {action_type}"

        actions_summary.append(summary)

    # 生成操作详情
    actions_details = []
    for i, action in enumerate(actions):
        detail = f"### 操作{i+1}\n"
        detail += f"- 类型: {action.get('action_type', 'unknown')}\n"
        detail += f"- 时间戳: {action.get('timestamp', 0)}\n"

        # 添加模式特定信息
        if action.get("recording_mode") == "browser":
            url = action.get("url")
            if url:
                detail += f"- URL: {url}\n"

            dom_element = action.get("dom_element")
            if dom_element:
                tag = dom_element.get("tag", "")
                text = dom_element.get("text", "")
                detail += f"- DOM元素: <{tag}>{text}</{tag}>\n"

            network_requests = action.get("network_requests")
            if network_requests:
                detail += f"- 网络请求: {len(network_requests)}个\n"
                for req in network_requests[:3]:  # 最多显示3个
                    detail += f"  - {req.get('method', 'GET')} {req.get('url', '')}\n"
        else:
            app_name = action.get("app_name", "")
            window_title = action.get("window_title", "")
            detail += f"- 应用: {app_name}\n"
            detail += f"- 窗口: {window_title}\n"

        # 添加参数
        parameters = action.get("parameters", {})
        if parameters:
            detail += f"- 参数: {parameters}\n"

        actions_details.append(detail)

    return {
        "recording_id": session_data.get("recording_id", ""),
        "recording_mode": session_data.get("recording_mode", "unknown"),
        "start_time": session_data.get("start_time", ""),
        "end_time": session_data.get("end_time", ""),
        "duration": session_data.get("end_time", 0) - session_data.get("start_time", 0),
        "actions_summary": "\n".join(actions_summary),
        "actions_details": "\n".join(actions_details),
    }


def format_conversation_history(history: list) -> str:
    """
    格式化对话历史

    Args:
        history: 对话历史列表，每项包含 {"role": "user/assistant", "content": "..."}

    Returns:
        格式化后的对话历史字符串
    """
    if not history:
        return "（无对话历史）"

    formatted = []
    for i, turn in enumerate(history):
        role = turn.get("role", "user")
        content = turn.get("content", "")
        role_label = "用户" if role == "user" else "助手"
        formatted.append(f"## 第{i+1}轮对话\n{role_label}: {content}\n")

    return "\n".join(formatted)

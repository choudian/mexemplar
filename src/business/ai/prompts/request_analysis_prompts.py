"""
网络请求分析的提示词模板
"""

# 用于判断单个请求是否有意义
JUDGMENT_PROMPT_TEMPLATE = """你是一个网络请求分析专家。请判断这个网络请求对自动化任务是否有意义。

【请求信息】
URL: {url}
方法: {method}
请求体: {request_body}

【响应信息】
状态码: {status_code}
响应类型: {content_type}
响应体（前500字符）: {response_body_preview}

【关联的用户操作】
操作类型: {action_type}
元素信息: {element_info}
时间戳: {timestamp}

【依赖关系】
这个请求使用了 {dependency_count} 个之前请求的数据

【判断标准】
1. 触发源：是否由用户操作直接触发？
2. 数据价值：响应是否包含业务数据（JSON、HTML）而非静态资源？
3. 可复现性：是否可以直接复现（无需复杂认证）？
4. 是否加密：响应数据是否被加密？

【过滤规则（严格遵守）】
⚠️ 以下类型的请求必须标记为无意义（is_meaningful=false）：

1. **静态资源**：
   - 文件扩展名：.js, .css, .png, .jpg, .jpeg, .gif, .svg, .ico, .woff, .woff2, .ttf, .eot
   - URL路径：包含 /static/, /assets/, /cdn/, /public/

2. **心跳/健康检查**：
   - URL包含：heartbeat, ping, keepalive, health, alive, monitor

3. **数据埋点/统计**：
   - URL包含：analytics, tracking, telemetry, gtag, collect, pixel, beacon
   - 域名：google-analytics.com, doubleclick.net, facebook.com/tr

4. **广告和推广**：
   - 广告网络域名：googlesyndication.com, doubleclick.net, baidustatic.com,
     cpro.baidu.com, mmstat.com, alimama.com, tgclick.qq.com, alicdn.com
   - 广告文件路径：包含 /ad/, /adv/, /广告/, /推广/
   - 广告尺寸参数：300x250, 728x90, 160x600, 336x280（常见广告位尺寸）
   - 广告关键词：banner, sidebar, popup（与静态资源结合时）

5. **明显无响应**：
   - 响应体为空或小于10字符
   - 状态码：204（无内容）、404（未找到）

6. **第三方脚本**：
   - 明显的第三方统计脚本（非业务相关）

✅ **例外情况**：
- 如果依赖关系数 >= 3（被3个以上请求依赖），即使类型可疑也保留
- 如果响应明确包含业务数据结构（如 {{"items": [...]}}），可以保留

【Few-Shot 示例】
示例1（静态资源 → 过滤）：
请求：GET https://cdn.example.com/app.js
→ {{"is_meaningful": false, "reason": "静态JavaScript文件，不包含业务数据", "category": "other", "confidence": 0.95}}

示例2（埋点请求 → 过滤）：
请求：POST https://analytics.google.com/collect
→ {{"is_meaningful": false, "reason": "数据埋点请求，用于统计分析", "category": "analytics", "confidence": 0.9}}

示例3（心跳请求 → 过滤）：
请求：GET https://api.example.com/heartbeat
→ {{"is_meaningful": false, "reason": "心跳检查请求，不包含业务数据", "category": "heartbeat", "confidence": 0.95}}

示例3.5（广告请求 → 过滤）：
请求：GET https://baidustatic.com/cpro/ui/bjh.js
→ {{"is_meaningful": false, "reason": "百度联盟广告脚本", "category": "advertising",
   "confidence": 0.95}}

示例3.6（广告请求 → 过滤）：
请求：GET https://googleads.g.doubleclick.net/pagead/ads?client=ca-pub-12345
→ {{"is_meaningful": false, "reason": "Google AdSense 广告请求", "category": "advertising",
   "confidence": 0.95}}

示例3.7（广告文件 → 过滤）：
请求：GET https://example.com/ads/banner_300x250.jpg
→ {{"is_meaningful": false, "reason": "广告图片文件（包含广告关键词和尺寸）",
   "category": "advertising", "confidence": 0.9}}

示例4（业务API → 保留）：
请求：GET https://api.example.com/users/123
响应：{{"id": 123, "name": "张三", "email": "test@example.com"}}
→ {{"is_meaningful": true, "reason": "用户数据API，响应包含完整的业务信息",
   "category": "api_call", "confidence": 0.95, "is_replayable": true}}

示例5（数据采集 → 保留）：
请求：GET https://www.baidu.com/s?wd=test
响应：HTML页面包含搜索结果
→ {{"is_meaningful": true, "reason": "用户主动搜索，响应包含搜索结果数据",
   "category": "data_fetch", "confidence": 0.9, "is_replayable": true}}

【输出格式】
重要：请直接返回纯 JSON 格式，不要使用 markdown 代码块，不要添加任何解释文字。

{{
    "is_meaningful": true/false,
    "reason": "判断理由（简短）",
    "confidence": 0.0-1.0,
    "category": "api_call/data_fetch/analytics/heartbeat/other",
    "is_replayable": true/false
}}

请开始分析："""

# ============================================================================
# V2: 基于模式识别和多维度评分的智能过滤提示词
# ============================================================================

JUDGMENT_PROMPT_V2_TEMPLATE = """你是一个浏览器操作数据过滤助手。你的任务是判断给定的浏览器事件或网络请求是否与用户的核心操作相关。

# 核心原则
1. 保守策略：不确定时选择保留（宁可多保留，不要误杀）
2. 关注用户主动操作：用户点击、输入、提交的相关数据都保留
3. 关注数据流向：如果一个请求的数据可能被后续操作使用，就保留
4. 过滤明确无关的：广告、统计、推荐等与当前任务无关的内容

---

# 输入信息

## 用户操作上下文
当前页面：{current_page}
核心操作：{core_actions}
最近3步操作：
1. {recent_action_1}
2. {recent_action_2}
3. {recent_action_3}

## 待判断的数据
**请求ID**: {request_id} （⚠️ 重要：你必须在返回结果中包含这个 request_id）
类型：{data_type}
URL: {url}
方法: {method}
请求体: {request_body}
状态码: {status_code}
响应类型: {content_type}
响应体（前500字符）: {response_body_preview}

发生时机：{timing}

## 后续操作预览（如果有）
{subsequent_operations}

## 依赖关系
这个请求被 {used_by_count} 个后续请求依赖

---

# 判断步骤

## 步骤1：检查特殊模式

### 模式A：表单数据源（必须保留）
特征：
- GET请求返回数组结构，如 `[{{"id": 1, "name": "北京"}}]`
- 在用户点击下拉框、单选框等元素时触发
- 后续提交请求的参数值存在于此响应中

示例：
```json
GET /api/cities
响应: [{{"id": 1, "name": "北京"}}, {{"id": 2, "name": "上海"}}]
触发时机: 用户点击"城市"下拉框
后续使用: POST /api/submit {{city: 1}}
```

### 模式B：搜索/查询操作（必须保留）
特征：
- 请求URL或参数包含：search, query, keyword, q, find
- 在用户输入或点击搜索按钮后触发
- 响应通常是列表结构，包含搜索结果

### 模式C：分步操作链（必须保留）
特征：
- 第一个请求返回 token、sessionId、taskId、orderId 等唯一标识
- 后续请求需要带上这些ID
- 形成多步骤的操作链

### 模式D：统计埋点（必须过滤）
特征：
- URL包含：track, analytics, stat, log, beacon, pixel, event
- 通常是POST或GET请求，发送用户行为数据
- 不返回业务数据，或返回 `{{success: true}}` 这种简单响应

### 模式E：广告/推荐内容（可以过滤）
特征：
- URL包含：ad, advertisement, recommend, promotion, suggest
- 或者域名是已知的广告网络（如doubleclick.net）
- 用户没有主动点击或请求这些内容
- 通常在页面加载后自动触发

### 模式F：资源预加载（可以过滤）
特征：
- 请求在用户操作之前就发起了
- 加载的是下一个页面的数据，但用户还没跳转
- URL可能包含 prefetch, preload

---

## 步骤2：计算各维度得分

### 维度1：触发方式（权重40%）
- **1.0分**：用户主动触发（点击、输入、提交、选择）
- **0.8分**：用户操作的直接结果（表单提交响应、页面跳转后加载）
- **0.5分**：页面加载时自动触发（需进一步判断）
- **0.2分**：定时器/轮询触发（setInterval、定时刷新）
- **0.0分**：预加载/推测性加载（prefetch、preload）

### 维度2：数据用途（权重30%）
- **1.0分**：数据被后续操作使用（下拉框选项、表单数据源、联动数据）
- **0.8分**：用户操作的结果数据（搜索结果、查询结果、提交响应）
- **0.5分**：数据展示但未交互（可能相关也可能不相关）
- **0.0分**：数据未被使用（加载了但没有展示，或与用户目标无关）

### 维度3：业务语义（权重20%）
- **1.0分**：核心业务操作（search, query, submit, login, checkout, order, pay）
- **0.9分**：表单数据源（返回选项列表、字段联动、验证接口）
- **0.5分**：页面内容加载（取决于是否是用户的目标内容）
- **0.1分**：辅助功能（用户偏好设置、主题配置）
- **0.0分**：明确无关（track, analytics, stat, log, beacon, pixel, ad, advertisement）

### 维度4：时序关联（权重10%）
- **1.0分**：用户操作后0-2秒内发生（高度可能是用户操作触发）
- **0.7分**：用户操作后2-5秒内发生（可能是异步加载）
- **0.4分**：时间间隔5-30秒（可能相关也可能不相关）
- **0.0分**：时间间隔30秒以上（大概率与当前操作无关）

---

## 步骤3：综合判断

### 计算综合得分
```
total_score = trigger_score × 0.4
            + data_usage_score × 0.3
            + semantic_score × 0.2
            + time_score × 0.1
```

### 判断规则
- **total_score ≥ 0.7** → 相关（保留）
- **total_score ≤ 0.3** → 不相关（过滤）
- **0.3 < total_score < 0.7** → 不确定，**保留**（保守策略）

### 置信度设定
- 匹配到明确模式（A-F） → confidence = 0.9
- total_score ≥ 0.8 或 ≤ 0.2 → confidence = 0.8
- 其他 → confidence = 0.5

---

# 输出格式

请严格按照以下 JSON 格式输出（不要使用 markdown 代码块，不要添加任何解释文字）：

{{
  "request_id": "⚠️ 必须返回上面输入的 request_id",
  "is_relevant": true/false,
  "confidence": 0.0-1.0,
  "category": "core_operation/data_source/side_effect/noise/resource",
  "reason": "一句话说明判断理由",
  "risk_level": "safe_to_filter/uncertain/keep",
  "pattern_matched": "模式A/模式B/模式C/模式D/模式E/模式F/none",
  "data_flow": {{
    "is_data_source": true/false,
    "used_by_requests": [],
    "depends_on_requests": []
  }},
  "scores": {{
    "trigger_method": 0.0-1.0,
    "data_usage": 0.0-1.0,
    "business_semantic": 0.0-1.0,
    "time_correlation": 0.0-1.0
  }}
}}

# Few-Shot 示例

## 示例1：模式A（表单数据源）
输入：
- URL: GET /api/cities
- 响应: [{{"id": 1, "name": "北京"}}, {{"id": 2, "name": "上海"}}]
- 触发时机: 用户点击"城市"下拉框
- 后续使用: POST /api/submit {{city: 1}}

输出：
```json
{{
  "is_relevant": true,
  "confidence": 0.95,
  "category": "data_source",
  "reason": "城市下拉框的数据源，后续提交使用了此数据",
  "risk_level": "keep",
  "pattern_matched": "模式A",
  "data_flow": {{
    "is_data_source": true,
    "used_by_requests": ["POST /api/submit"],
    "depends_on_requests": []
  }},
  "scores": {{
    "trigger_method": 1.0,
    "data_usage": 1.0,
    "business_semantic": 0.9,
    "time_correlation": 1.0
  }}
}}
```

## 示例2：模式D（统计埋点）
输入：
- URL: POST /api/track/click
- 参数: {{event: "search_button_click", timestamp: 1234567890}}
- 响应: {{success: true}}

输出：
```json
{{
  "is_relevant": false,
  "confidence": 0.95,
  "category": "noise",
  "reason": "统计埋点请求，与业务流程无关",
  "risk_level": "safe_to_filter",
  "pattern_matched": "模式D",
  "data_flow": {{
    "is_data_source": false,
    "used_by_requests": [],
    "depends_on_requests": []
  }},
  "scores": {{
    "trigger_method": 0.2,
    "data_usage": 0.0,
    "business_semantic": 0.0,
    "time_correlation": 0.7
  }}
}}
```

## 示例3：模式B（搜索操作）
输入：
- URL: GET /api/search?keyword=测试
- 响应: {{total: 100, results: [{{title: "...", url: "..."}}]}}
- 触发时机: 用户点击搜索按钮后0.2秒

输出：
```json
{{
  "is_relevant": true,
  "confidence": 0.98,
  "category": "core_operation",
  "reason": "用户搜索操作的核心请求",
  "risk_level": "keep",
  "pattern_matched": "模式B",
  "data_flow": {{
    "is_data_source": false,
    "used_by_requests": [],
    "depends_on_requests": []
  }},
  "scores": {{
    "trigger_method": 1.0,
    "data_usage": 0.8,
    "business_semantic": 1.0,
    "time_correlation": 1.0
  }}
}}
```

请开始分析："""

# 用于批量分析的简化提示词
BATCH_ANALYSIS_PROMPT_TEMPLATE = """分析以下 {count} 个网络请求，判断哪些是有意义的。

{requests_summary}

【任务】
对于每个请求，返回：
{{
    "request_id": "请求ID",
    "is_meaningful": true/false,
    "reason": "简短理由"
}}

请开始分析："""

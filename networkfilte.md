好！我们聚焦在**小模型过滤阶段的提示词设计**。

---

## 核心设计思路

小模型过滤的目标：**快速判断一个请求/事件是否与用户的核心操作相关**

关键约束：
1. 小模型能力有限，不能让它做太复杂的推理
2. 要给它足够的上下文，但不能太多（token限制）
3. 要让它输出结构化结果，方便后续处理

---

## 提示词模板

```markdown
# 角色定义
你是一个浏览器操作数据过滤助手。你的任务是判断给定的浏览器事件或网络请求是否与用户的核心操作相关。

# 核心原则
1. 保守策略：不确定时选择保留（宁可多保留，不要误杀）
2. 关注用户主动操作：用户点击、输入、提交的相关数据都保留
3. 关注数据流向：如果一个请求的数据可能被后续操作使用，就保留
4. 过滤明确无关的：广告、统计、推荐等与当前任务无关的内容

---

# 输入信息

## 用户操作上下文
{user_context}

当前页面：{current_page}
核心操作：{core_actions}
最近3步操作：
1. {recent_action_1}
2. {recent_action_2}  
3. {recent_action_3}

## 待判断的数据
类型：{data_type}  # 可选值：xhr_request, fetch_request, dom_event, resource_load
详情：
{data_details}

发生时机：{timing}  # 如："在用户点击提交按钮后0.2秒"

## 后续操作预览（如果有）
{subsequent_operations}  # 接下来的1-2步操作，帮助判断当前数据是否有用

---

# 判断维度

## 维度1：触发方式（权重40%）
- ✓ 用户主动触发（点击、输入、提交等）→ 高度相关
- ✓ 用户操作的直接结果（表单提交、页面跳转等）→ 高度相关
- ⚠ 页面加载时自动触发 → 需要进一步判断
- ✗ 定时器/轮询触发 → 可能无关
- ✗ 页面打开时预加载 → 可能无关

## 维度2：数据用途（权重30%）
- ✓ 数据被后续操作使用（如下拉选项、表单数据源）→ 高度相关
- ✓ 用户操作的结果数据（搜索结果、提交响应）→ 高度相关
- ⚠ 数据展示在页面上，但用户未与之交互 → 可能相关
- ✗ 数据未在当前操作流程中使用 → 可能无关

## 维度3：业务语义（权重20%）
- ✓ 搜索、查询、提交、登录等核心业务操作 → 高度相关
- ✓ 表单数据源（下拉选项、联动数据）→ 高度相关
- ⚠ 页面内容加载（取决于是否是用户目标）→ 需判断
- ✗ 广告、推荐、统计、埋点 → 无关
- ✗ 资源加载（CSS、JS、图片、字体）→ 无关

## 维度4：时序关联（权重10%）
- ✓ 在用户操作前0-2秒内发生 → 可能是操作触发的
- ✓ 在用户操作后0-5秒内发生 → 可能是操作结果
- ⚠ 时间间隔较大（5-30秒）→ 可能无关，但要看具体情况
- ✗ 时间间隔很大（30秒+）→ 大概率无关

---

# 特殊模式识别

## 模式A：表单数据源
**特征**：
- GET请求返回数组结构，如 [{id, name}] 或 [{code, label}]
- 在用户点击下拉框、单选框等元素时触发
- 后续提交请求的参数值存在于此响应中

**判断**：高度相关，必须保留

**示例**：
```
GET /api/cities → [{id:1, name:"北京"}, {id:2, name:"上海"}]
用户点击城市下拉框触发
后续 POST /api/submit {city: 1} ← 这个1来自上面的响应
```

## 模式B：搜索/查询
**特征**：
- 请求URL或参数包含：search, query, keyword, q 等
- 在用户输入或点击搜索按钮后触发
- 响应通常是列表结构

**判断**：高度相关，必须保留

## 模式C：分步操作
**特征**：
- 第一个请求返回 token、sessionId、taskId 等
- 后续请求需要带上这些ID
- 形成操作链

**判断**：高度相关，整条链都要保留

## 模式D：统计埋点
**特征**：
- URL包含：track, analytics, stat, log, beacon, pixel
- 通常是POST或GET请求，发送用户行为数据
- 不返回业务数据，或返回 {success: true} 这种简单响应

**判断**：无关，可以过滤

## 模式E：广告/推荐
**特征**：
- URL包含：ad, advertisement, recommend, promotion
- 或者域名是已知的广告网络
- 用户没有主动点击这些内容

**判断**：无关，可以过滤

## 模式F：资源预加载
**特征**：
- 请求在用户操作之前就发起了
- 加载的是下一个页面的数据，但用户还没跳转
- URL可能包含 prefetch, preload

**判断**：可能无关，除非用户确实跳转到了那个页面

---

# 输出格式

请严格按照以下JSON格式输出：

```json
{
  "is_relevant": true | false,
  "confidence": 0.85,
  "category": "core_operation | data_source | side_effect | noise | resource",
  "reason": "一句话说明判断理由",
  "risk_level": "safe_to_filter | uncertain | keep",
  "pattern_matched": "模式A | 模式B | 模式C | 模式D | 模式E | 模式F | none",
  "data_flow": {
    "is_data_source": false,
    "used_by_requests": [],
    "depends_on_requests": []
  },
  "scores": {
    "trigger_method": 0.8,
    "data_usage": 0.6,
    "business_semantic": 0.9,
    "time_correlation": 0.7
  }
}
```

**字段说明**：

- `is_relevant`: 最终判断（true=保留，false=过滤）
- `confidence`: 判断的置信度（0-1之间，<0.6表示不确定）
- `category`: 
  - `core_operation`: 核心操作（必须保留）
  - `data_source`: 数据源（必须保留）
  - `side_effect`: 副作用（可能保留）
  - `noise`: 噪音（可以过滤）
  - `resource`: 资源加载（可以过滤）
- `reason`: 判断理由（一句话，便于调试和优化）
- `risk_level`: 
  - `safe_to_filter`: 安全过滤，不会影响后续分析
  - `uncertain`: 不确定，建议保留
  - `keep`: 必须保留
- `pattern_matched`: 匹配到的模式（帮助理解判断依据）
- `data_flow`: 数据流信息
  - `is_data_source`: 是否是其他请求的数据源
  - `used_by_requests`: 被哪些请求使用（请求ID列表）
  - `depends_on_requests`: 依赖哪些请求（请求ID列表）
- `scores`: 各维度得分（0-1之间，便于调试）

---

# 判断逻辑

1. **先检查特殊模式**
   如果匹配到模式D（统计埋点）或模式E（广告）→ 直接判定为无关
   如果匹配到模式A（表单数据源）或模式B（搜索）→ 直接判定为相关

2. **计算各维度得分**
   - 触发方式得分 × 0.4
   - 数据用途得分 × 0.3
   - 业务语义得分 × 0.2
   - 时序关联得分 × 0.1
   
3. **综合判断**
   - 总分 ≥ 0.7 → is_relevant = true
   - 总分 ≤ 0.3 → is_relevant = false
   - 0.3 < 总分 < 0.7 → is_relevant = true（保守策略，不确定时保留）

4. **置信度设定**
   - 匹配到明确模式 → confidence = 0.9
   - 总分很高（≥0.8）或很低（≤0.2）→ confidence = 0.8
   - 总分居中 → confidence = 0.5

---

# 示例

## 示例1：表单数据源（应该保留）

**输入**：
```
用户操作上下文：用户正在填写注册表单
当前页面：/register
核心操作：填写注册信息并提交
最近3步操作：
1. 点击"城市"下拉框
2. （当前待判断的请求发生）
3. 选择"北京"

待判断的数据：
类型：xhr_request
详情：
  URL: GET /api/cities
  响应: [{"id": 1, "name": "北京"}, {"id": 2, "name": "上海"}]
  
发生时机：在用户点击"城市"下拉框后0.1秒

后续操作预览：
1. 用户选择"北京"
2. 点击提交按钮
3. 发送 POST /api/register {city: 1, name: "张三"}
```

**输出**：
```json
{
  "is_relevant": true,
  "confidence": 0.95,
  "category": "data_source",
  "reason": "这是城市下拉框的数据源，后续提交请求的city参数值1来自此响应",
  "risk_level": "keep",
  "pattern_matched": "模式A",
  "data_flow": {
    "is_data_source": true,
    "used_by_requests": ["POST /api/register"],
    "depends_on_requests": []
  },
  "scores": {
    "trigger_method": 1.0,
    "data_usage": 1.0,
    "business_semantic": 0.9,
    "time_correlation": 1.0
  }
}
```

## 示例2：统计埋点（应该过滤）

**输入**：
```
用户操作上下文：用户正在搜索内容
当前页面：/search
核心操作：搜索关键词"测试"
最近3步操作：
1. 在搜索框输入"测试"
2. 点击搜索按钮
3. （当前待判断的请求发生）

待判断的数据：
类型：xhr_request
详情：
  URL: POST /api/track/click
  参数: {event: "search_button_click", timestamp: 1234567890}
  响应: {success: true}
  
发生时机：在用户点击搜索按钮后0.05秒

后续操作预览：
1. 页面跳转到搜索结果页
2. 用户浏览搜索结果
```

**输出**：
```json
{
  "is_relevant": false,
  "confidence": 0.95,
  "category": "noise",
  "reason": "这是统计埋点请求，只记录用户行为，不影响业务流程",
  "risk_level": "safe_to_filter",
  "pattern_matched": "模式D",
  "data_flow": {
    "is_data_source": false,
    "used_by_requests": [],
    "depends_on_requests": []
  },
  "scores": {
    "trigger_method": 0.8,
    "data_usage": 0.0,
    "business_semantic": 0.0,
    "time_correlation": 0.9
  }
}
```

## 示例3：搜索请求（应该保留）

**输入**：
```
用户操作上下文：用户想查找关于"测试"的内容
当前页面：/search
核心操作：搜索关键词"测试"
最近3步操作：
1. 在搜索框输入"测试"
2. 点击搜索按钮
3. （当前待判断的请求发生）

待判断的数据：
类型：xhr_request
详情：
  URL: GET /api/search?keyword=测试&page=1
  响应: {total: 100, results: [{title: "...", url: "..."}]}
  
发生时机：在用户点击搜索按钮后0.2秒

后续操作预览：
1. 搜索结果展示在页面上
2. 用户点击第3条结果
```

**输出**：
```json
{
  "is_relevant": true,
  "confidence": 0.98,
  "category": "core_operation",
  "reason": "这是用户搜索操作的核心请求，返回搜索结果数据",
  "risk_level": "keep",
  "pattern_matched": "模式B",
  "data_flow": {
    "is_data_source": true,
    "used_by_requests": [],
    "depends_on_requests": []
  },
  "scores": {
    "trigger_method": 1.0,
    "data_usage": 1.0,
    "business_semantic": 1.0,
    "time_correlation": 1.0
  }
}
```

## 示例4：推荐内容（应该过滤）

**输入**：
```
用户操作上下文：用户查看搜索结果详情
当前页面：/article/12345
核心操作：阅读搜索结果文章
最近3步操作：
1. 从搜索结果页点击第3条
2. 页面跳转到文章详情
3. （当前待判断的请求发生）

待判断的数据：
类型：xhr_request
详情：
  URL: GET /api/recommend/related?articleId=12345
  响应: {items: [{id: 111, title: "推荐文章1"}, ...]}
  
发生时机：在页面加载后2秒

后续操作预览：
1. 用户继续阅读当前文章
2. 用户关闭页面
```

**输出**：
```json
{
  "is_relevant": false,
  "confidence": 0.8,
  "category": "side_effect",
  "reason": "这是页面自动加载的推荐内容，用户没有与之交互，与核心操作无关",
  "risk_level": "safe_to_filter",
  "pattern_matched": "模式E",
  "data_flow": {
    "is_data_source": false,
    "used_by_requests": [],
    "depends_on_requests": []
  },
  "scores": {
    "trigger_method": 0.2,
    "data_usage": 0.0,
    "business_semantic": 0.2,
    "time_correlation": 0.5
  }
}
```

## 示例5：不确定的情况（保守保留）

**输入**：
```
用户操作上下文：用户正在浏览商品列表
当前页面：/products
核心操作：查看商品信息
最近3步操作：
1. 进入商品列表页
2. 滚动页面
3. （当前待判断的请求发生）

待判断的数据：
类型：xhr_request
详情：
  URL: GET /api/user/preferences
  响应: {theme: "dark", language: "zh-CN"}
  
发生时机：在页面加载后1秒

后续操作预览：
（未知，用户还没有进行下一步操作）
```

**输出**：
```json
{
  "is_relevant": true,
  "confidence": 0.4,
  "category": "side_effect",
  "reason": "无法确定此请求与核心操作的关系，保守策略选择保留",
  "risk_level": "uncertain",
  "pattern_matched": "none",
  "data_flow": {
    "is_data_source": false,
    "used_by_requests": [],
    "depends_on_requests": []
  },
  "scores": {
    "trigger_method": 0.3,
    "data_usage": 0.5,
    "business_semantic": 0.5,
    "time_correlation": 0.6
  }
}
```

---

# 注意事项

1. **保守策略**：置信度低于0.6时，默认选择保留
2. **避免过度解读**：不要试图理解加密数据，遇到加密就标记为uncertain
3. **关注数据流**：特别注意返回 [{id, name}] 这种结构的请求，很可能是数据源
4. **时序很重要**：用户操作后立即发生的请求，大概率相关
5. **URL模式识别**：URL路径和参数名称包含很多语义信息
```

---

## 使用时的填充模板

```python
def build_filter_prompt(data_item, context):
    """
    构建小模型过滤的提示词
    
    参数:
        data_item: 待判断的数据（请求或事件）
        context: 上下文信息
    """
    
    # 提取用户最近的核心操作
    recent_actions = context.get_recent_actions(n=3)
    
    # 获取后续操作（如果有）
    subsequent_ops = context.get_subsequent_operations(n=2)
    
    # 填充模板
    prompt = f"""
# 输入信息

## 用户操作上下文
当前页面：{context.current_page}
核心操作：{context.primary_goal}
最近3步操作：
{format_actions(recent_actions)}

## 待判断的数据
类型：{data_item.type}
详情：
{format_data_details(data_item)}

发生时机：{data_item.timing_description}

## 后续操作预览（如果有）
{format_subsequent_ops(subsequent_ops)}

请按照上述规则判断这个数据是否相关，并输出JSON格式的结果。
"""
    
    return prompt
```

---

## 优化建议

### 1. 动态调整判断阈值

根据数据量和后续处理能力，调整过滤的激进程度：

```python
# 如果原始数据太多（>1000条），可以提高过滤阈值
if total_data_count > 1000:
    filter_threshold = 0.5  # 总分低于0.5就过滤
else:
    filter_threshold = 0.3  # 总分低于0.3才过滤
```

### 2. 批量判断优化

如果请求很多，可以让小模型一次判断多个相似的：

```python
# 把相同URL模式的请求分组
# 比如多个 /api/track/* 的请求，可以一起判断
grouped_requests = group_by_url_pattern(requests)

for pattern, group in grouped_requests:
    if len(group) > 5:
        # 批量判断
        prompt = f"以下{len(group)}个请求都是{pattern}模式，请统一判断是否相关"
```

### 3. 增加规则预判断

在调用小模型前，先用规则快速判断：

```python
def should_skip_llm(data_item):
    """某些明显的情况不需要调用小模型"""
    
    # 100%是资源加载
    if data_item.type in ['image', 'css', 'js', 'font']:
        return True, {"is_relevant": False, "confidence": 1.0}
    
    # 100%是统计
    if any(kw in data_item.url for kw in ['analytics', 'track', 'beacon']):
        return True, {"is_relevant": False, "confidence": 0.95}
    
    # 100%是核心操作
    if data_item.type == 'form_submit':
        return True, {"is_relevant": True, "confidence": 1.0}
    
    return False, None  # 需要小模型判断
```

### 4. 增加反馈循环

记录小模型的判断结果，以及最终大模型的使用情况：

```python
# 如果小模型判断为"无关"，但大模型分析时发现需要这个数据
# → 记录下来，优化小模型的提示词

feedback_log = {
    "request_id": "req_123",
    "small_model_decision": "filter",
    "actual_usage": "used_by_big_model",
    "reason": "原来这个请求是表单数据源，小模型没识别出来"
}
```

---

## 总结

这个提示词的关键设计点：

1. **分层判断**：4个维度，每个维度有明确的评分标准
2. **模式识别**：6种常见模式，帮助快速判断
3. **保守策略**：不确定时选择保留，避免误杀
4. **结构化输出**：JSON格式，包含详细的判断依据
5. **可调试**：输出各维度得分，方便后续优化

你可以先用这个提示词测试一下，看看效果如何。如果有具体的case（比如某个请求被错误过滤或保留），我们可以针对性地调整。
# 代码层面业务流程图

**最后更新**: 2026-01-23
**目的**: 详细说明各个功能在代码层面的执行流程，涉及哪些类和方法

---

## 📋 目录

- [浏览器录制流程](#浏览器录制流程)
- [AI 工作流生成流程](#ai-工作流生成流程)
- [事件驱动处理流程](#事件驱动处理流程)
- [工具执行流程](#工具执行流程)
- [数据压缩与智能过滤流程](#数据压缩与智能过滤流程)

---

## 浏览器录制流程

### 完整调用链

```
用户代码
  ↓
src/recording/recorder.py: Recorder.start_recording()
  ↓
src/recording/browser_recorder.py: BrowserRecorder.start_recording()
  ↓
src/recording/websocket_server.py: WebSocketServer.start()
  ├─→ 启动 WebSocket 服务器 (ws://127.0.0.1:8765)
  └─→ 启动消息处理线程
  ↓
playwright.sync_api.sync_playwright()
  ↓
browser.new_page(加载扩展)
  ↓
浏览器扩展连接 WebSocket
  ↓
src/recording/websocket_server.py: WebSocketServer.handler()
  ├─→ 接收消息
  └─→ 写入队列文件
  ↓
用户停止录制
  ↓
src/recording/browser_recorder.py: BrowserRecorder.stop_recording()
  ├─→ 发送 STOP_RECORDING 命令
  ├─→ 关闭浏览器
  ├─→ 关闭 WebSocket
  └─→ 读取队列文件
  ↓
src/data/duckdb_manager.py: DuckDBManager.save_recording_session()
  ├─→ 保存到 recording_sessions 表
  ├─→ 保存 actions
  ├─→ 保存 network_requests
  └─→ 保存 sibling_snapshots
  ↓
返回 RecordingSession 对象
```

### 关键类和方法

#### 1. Recorder (recorder.py)

```python
class Recorder:
    def start_recording(self) -> None:
        """开始录制"""
        if self.recording_mode == 'browser':
            self.browser_recorder.start_recording()

    def stop_recording(self) -> RecordingSession:
        """停止录制并返回会话"""
        if self.recording_mode == 'browser':
            return self.browser_recorder.stop_recording()
```

#### 2. BrowserRecorder (browser_recorder.py)

```python
class BrowserRecorder:
    def start_recording(self) -> None:
        """启动浏览器录制"""
        # 1. 创建录制 ID
        self.recording_id = str(uuid.uuid4())

        # 2. 启动 WebSocket 服务器
        self.websocket_server = WebSocketServer(self.recording_id)
        self.websocket_server.start()

        # 3. 启动 Playwright 浏览器
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=False,
            args=['--load-extension=' + self.extension_path]
        )

    def stop_recording(self) -> RecordingSession:
        """停止录制"""
        # 1. 发送停止命令
        self.websocket_server.send_command('STOP_RECORDING')

        # 2. 读取队列文件
        events = self._read_queue_file()

        # 3. 转换为 Action 对象
        actions = self._convert_events_to_actions(events)

        # 4. 保存到 DuckDB
        self.duckdb_manager.save_recording_session(
            self.recording_id, actions
        )

        # 5. 创建 RecordingSession
        return RecordingSession(
            recording_id=self.recording_id,
            status='stopped',
            actions=actions,
            ...
        )
```

#### 3. WebSocketServer (websocket_server.py)

```python
class WebSocketServer:
    async def handler(self, websocket, path):
        """处理 WebSocket 连接和消息"""
        async for message in websocket:
            data = json.loads(message)

            # 写入队列文件
            self.queue_file.write(json.dumps(data) + '\n')

            # 如果是命令响应
            if data.get('type') == 'command_response':
                self.responses[data['command_id']] = data
```

### 数据流

```
浏览器扩展 (content_script_simple.js)
  ↓ captureEvent()
浏览器扩展 (websocket_client.js)
  ↓ WebSocket.send()
Python WebSocket 服务器
  ↓ 队列文件 (data/queues/<recording_id>_actions.jsonl)
BrowserRecorder._read_queue_file()
  ↓ Action 对象列表
DuckDBManager.save_recording_session()
  ↓ recording_sessions, actions, network_requests, sibling_snapshots 表
```

---

## AI 工作流生成流程

### 完整调用链

```
录制完成事件
  ↓
src/utils/events.py: signal('recording_completed').send(session)
  ↓
src/business/ai/workflow_orchestrator.py: WorkflowOrchestrator._on_recording_completed()
  ↓
src/business/ai/workflow_orchestrator.py: process_recording_v2()
  ↓
src/business/ai/data_preprocessor.py: DataPreprocessorV2.preprocess_with_analysis()
  ├─→ 规则过滤
  ├─→ 操作合并
  └─→ 网络请求分析
  ↓
src/business/ai/request_intelligence_analyzer.py: RequestIntelligenceAnalyzer.analyze_requests()
  ├─→ 规则引擎过滤
  ├─→ 加密检测
  └─→ 依赖分析
  ↓
src/business/ai/network_analyzer.py: NetworkAnalyzer.analyze_recording()
  ├─→ 判断 API 可复现性
  └─→ 提取响应结构
  ↓
src/business/ai/list_operation_analyzer.py: ListOperationAnalyzer.analyze()
  ├─→ 识别列表操作
  └─→ 生成匹配策略
  ↓
src/business/ai/semantic_analyzer.py: SemanticAnalyzer.generate_workflow()
  ├─→ 使用 PromptsV2 构建提示词
  └─→ 调用 Claude API
  ↓
src/business/ai/llm_client.py: ClaudeClient.call_api()
  ↓
Anthropic Claude API
  ↓
src/business/ai/semantic_analyzer.py: 解析响应
  ↓
src/data/repositories.py: ToolRepository.save()
  ↓
src/data/database.py: DatabaseManager.add_tool()
  ↓
SQLite tools 表
```

### 关键类和方法

#### 1. WorkflowOrchestrator (workflow_orchestrator.py)

```python
class WorkflowOrchestrator:
    def process_recording_v2(self, session: RecordingSession) -> Tool:
        """处理录制会话生成工具"""

        # 1. 数据预处理（包含分析和压缩）
        preprocessing_result = self.data_preprocessor.preprocess_with_analysis(
            session.actions,
            session.network_requests,
            compression_level=self.compression_level
        )

        # 2. 网络请求分析
        network_analysis = self.network_analyzer.analyze_recording(
            preprocessing_result.actions,
            preprocessing_result.network_requests
        )

        # 3. 列表操作分析
        list_analysis = self.list_operation_analyzer.analyze(
            preprocessing_result.actions,
            network_analysis
        )

        # 4. 语义分析和代码生成
        tool_definition = self.semantic_analyzer.generate_workflow(
            preprocessing_result.actions,
            network_analysis,
            list_analysis
        )

        # 5. 保存工具
        self.tool_repository.save(tool_definition)

        return tool_definition
```

#### 2. DataPreprocessorV2 (data_preprocessor.py)

```python
class DataPreprocessorV2:
    def preprocess_with_analysis(
        self,
        actions: List[Action],
        network_requests: List[NetworkRequestDetail],
        compression_level: CompressionLevel
    ) -> PreprocessingResult:
        """数据预处理（包含智能分析）"""

        # 1. 基础压缩
        actions = self._merge_consecutive_inputs(actions, compression_level)
        actions = self._filter_duplicate_actions(actions)

        # 2. 智能网络请求过滤
        if compression_level in [CompressionLevel.MODERATE, CompressionLevel.AGGRESSIVE]:
            filtered_requests = self.request_analyzer.analyze_requests(
                actions, network_requests
            )
        else:
            # 仅使用规则引擎
            filtered_requests = self._rule_based_filter(network_requests)

        # 3. 压缩数据
        compressed_actions = []
        for action in actions:
            compressed = self._compress_action(action, filtered_requests)
            compressed_actions.append(compressed)

        return PreprocessingResult(
            actions=compressed_actions,
            network_requests=filtered_requests,
            metadata={
                'original_action_count': len(actions),
                'compressed_action_count': len(compressed_actions),
                'compression_ratio': len(compressed_actions) / len(actions)
            }
        )
```

#### 3. RequestIntelligenceAnalyzer (request_intelligence_analyzer.py)

```python
class RequestIntelligenceAnalyzer:
    def analyze_requests(
        self,
        actions: List[Action],
        requests: List[NetworkRequestDetail]
    ) -> List[NetworkRequestDetail]:
        """智能分析网络请求"""

        valid_requests = []

        for request in requests:
            # 1. 规则引擎过滤（快速）
            if not self._rule_engine_check(request):
                continue

            # 2. 加密检测
            if self.encryption_detector.is_encrypted(request):
                continue

            # 3. 依赖分析
            if not self.dependency_analyzer.is_independent(request):
                continue

            # 4. 数据压缩模型分析（可选）
            if self.use_compression_model:
                should_keep = self._llm_analyze_request(request)
                if not should_keep:
                    continue

            valid_requests.append(request)

        return valid_requests
```

#### 4. SemanticAnalyzer (semantic_analyzer.py)

```python
class SemanticAnalyzer:
    def generate_workflow(
        self,
        actions: List[Action],
        network_analysis: List[NetworkRequestAnalysis],
        list_analysis: List[ListOperationAnalysis]
    ) -> Tool:
        """使用 LLM 生成工作流"""

        # 1. 构建提示词
        prompt = self.prompts_v2.build_prompt(
            actions=actions,
            network_analysis=network_analysis,
            list_analysis=list_analysis
        )

        # 2. 调用 Claude API
        response = self.llm_client.call_api(
            model='claude-sonnet-4-5-20250929',
            prompt=prompt,
            max_tokens=4000
        )

        # 3. 解析响应
        tool_definition = self._parse_llm_response(response)

        return tool_definition
```

### 数据流

```
RecordingSession (DuckDB)
  ↓ WorkflowOrchestrator.process_recording_v2()
DataPreprocessorV2.preprocess_with_analysis()
  ↓ 压缩后的 Action + 网络请求
RequestIntelligenceAnalyzer.analyze_requests()
  ↓ 过滤后的网络请求
NetworkAnalyzer.analyze_recording()
  ↓ 网络请求分析（可复现性、结构）
ListOperationAnalyzer.analyze()
  ↓ 列表操作分析
SemanticAnalyzer.generate_workflow()
  ↓ 构建提示词
ClaudeClient.call_api()
  ↓ LLM 响应
SemanticAnalyzer._parse_llm_response()
  ↓ Tool 对象
ToolRepository.save()
  ↓ SQLite tools 表
```

---

## 事件驱动处理流程

### 完整调用链

```
BrowserRecorder.stop_recording()
  ↓
src/utils/events.py: signal('recording_completed').send(session)
  ↓
WorkflowOrchestrator.__init__() 中的监听器
  ↓ signal('recording_completed').connect(_on_recording_completed)
  ↓
WorkflowOrchestrator._on_recording_complete(session)
  ↓
process_recording_v2(session)
  ↓
emit('workflow_processing_started', session_id)
  ↓
... (处理流程) ...
  ↓
emit('workflow_processing_completed', tool_data)
  ↓
ToolRepository.save(tool)
  ↓
emit('tool_created', tool_data)
```

### 关键类和方法

#### 1. 事件定义 (events.py)

```python
from blinker import signal

# 定义事件
recording_completed = signal('recording_completed')
workflow_processing_started = signal('workflow_processing_started')
workflow_processing_progress = signal('workflow_processing_progress')
workflow_processing_completed = signal('workflow_processing_completed')
tool_created = signal('tool_created')
tool_executed = signal('tool_executed')
```

#### 2. WorkflowOrchestrator 订阅事件 (workflow_orchestrator.py)

```python
class WorkflowOrchestrator:
    def __init__(self, auto_process=True, compression_level=CompressionLevel.MODERATE):
        self.auto_process = auto_process
        self.compression_level = compression_level

        # 订阅录制完成事件
        if self.auto_process:
            signal('recording_completed').connect(
                self._on_recording_completed
            )

    def _on_recording_completed(self, session: RecordingSession):
        """录制完成事件处理"""
        logger.info(f"收到录制完成事件: {session.recording_id}")

        # 自动处理录制
        try:
            tool = self.process_recording_v2(session)
            logger.info(f"✅ 工具生成成功: {tool.tool_name}")
        except Exception as e:
            logger.error(f"❌ 工具生成失败: {e}")
```

#### 3. 发送进度事件

```python
class WorkflowOrchestrator:
    def process_recording_v2(self, session: RecordingSession) -> Tool:
        # 发送处理开始事件
        signal('workflow_processing_started').send(
            session_id=session.recording_id
        )

        try:
            # 步骤 1: 数据预处理
            signal('workflow_processing_progress').send(
                session_id=session.recording_id,
                percent=20,
                step_name='数据预处理',
                message='正在压缩和过滤数据...'
            )

            preprocessing_result = self.data_preprocessor.preprocess_with_analysis(...)

            # 步骤 2: 网络请求分析
            signal('workflow_processing_progress').send(
                session_id=session.recording_id,
                percent=40,
                step_name='网络请求分析',
                message='正在分析网络请求...'
            )

            network_analysis = self.network_analyzer.analyze_recording(...)

            # ... 其他步骤 ...

            # 发送完成事件
            signal('workflow_processing_completed').send(
                tool_id=tool.tool_id,
                tool_name=tool.tool_name,
                session_id=session.recording_id
            )

            return tool

        except Exception as e:
            logger.error(f"处理失败: {e}")
            raise
```

### 事件流

```
BrowserRecorder.stop_recording()
  ↓ emit('recording_completed')
  ↓
WorkflowOrchestrator._on_recording_completed() [监听器]
  ↓ emit('workflow_processing_started')
  ↓
DataPreprocessor.preprocess()
  ↓ emit('workflow_processing_progress', 20%)
  ↓
NetworkAnalyzer.analyze()
  ↓ emit('workflow_processing_progress', 40%)
  ↓
SemanticAnalyzer.generate_workflow()
  ↓ emit('workflow_processing_progress', 80%)
  ↓
ToolRepository.save()
  ↓ emit('workflow_processing_completed')
  ↓ emit('tool_created')
```

---

## 工具执行流程

### 完整调用链

```
用户请求执行工具
  ↓
src/execution/executor.py: Executor.execute_tool()
  ↓
src/execution/action_executor.py: ActionExecutor.execute()
  ↓
src/execution/execution_context.py: ExecutionContext.resolve_parameters()
  ↓
src/execution/parameter_resolver.py: ParameterResolver.resolve()
  ↓
src/drivers/locator/multi_layer_locator.py: MultiLayerLocator.locate_element()
  ├─→ DOM/UI Automation 定位
  ├─→ 坐标定位
  └─→ 图像识别定位
  ↓
src/drivers/windows/windows_driver.py: WindowsDriver.click()
  ↓
执行操作
  ↓
src/execution/retry_handler.py: RetryHandler.handle_retry()
  ↓
返回执行结果
```

### 关键类和方法

#### 1. Executor (executor.py)

```python
class Executor:
    def execute_tool(self, tool_id: str, parameters: Dict) -> ExecutionResult:
        """执行工具"""

        # 1. 加载工具定义
        tool = self.tool_repository.get_by_id(tool_id)

        # 2. 创建执行上下文
        context = ExecutionContext(
            tool=tool,
            parameters=parameters,
            variables={}
        )

        # 3. 执行每个 Action
        results = []
        for action in tool.actions:
            result = self.action_executor.execute(action, context)
            results.append(result)

            # 更新上下文变量
            context.variables.update(result.output_variables)

        # 4. 返回执行结果
        return ExecutionResult(
            success=all(r.success for r in results),
            results=results
        )
```

#### 2. ActionExecutor (action_executor.py)

```python
class ActionExecutor:
    def execute(self, action: Action, context: ExecutionContext) -> ActionResult:
        """执行单个 Action"""

        # 1. 解析参数
        resolved_params = self.parameter_resolver.resolve(
            action.parameters,
            context
        )

        # 2. 获取驱动
        driver = self.driver_factory.get_driver(action.recording_mode)

        # 3. 定位元素
        element = self.locator.locate_element(
            driver,
            action.dom_element
        )

        # 4. 执行操作
        if action.action_type == 'click':
            result = driver.click(element)
        elif action.action_type == 'input':
            result = driver.input(element, resolved_params['text'])
        # ... 其他操作类型 ...

        # 5. 处理重试
        if not result.success:
            result = self.retry_handler.handle_retry(
                action, context, result
            )

        return result
```

#### 3. MultiLayerLocator (multi_layer_locator.py)

```python
class MultiLayerLocator:
    def locate_element(self, driver, dom_element: Dict):
        """多层次定位元素"""

        # 层次 1: DOM/UI Automation 定位
        if dom_element.get('css_selector'):
            element = driver.find_element_by_css(dom_element['css_selector'])
            if element:
                return element

        if dom_element.get('xpath'):
            element = driver.find_element_by_xpath(dom_element['xpath'])
            if element:
                return element

        # 层次 2: 坐标定位
        if dom_element.get('coordinates'):
            element = driver.find_element_by_coordinates(
                dom_element['coordinates']
            )
            if element:
                return element

        # 层次 3: 图像识别定位
        if dom_element.get('visual_features'):
            element = self.image_matcher.find_by_image(
                driver.screenshot(),
                dom_element['visual_features']
            )
            if element:
                return element

        raise ElementNotFoundError(f"无法定位元素: {dom_element}")
```

### 数据流

```
Tool (SQLite)
  ↓ Executor.execute_tool()
ExecutionContext (参数解析)
  ↓ ActionExecutor.execute()
MultiLayerLocator.locate_element()
  ↓ 尝试 3 种定位策略
Driver (Playwright/pywinauto)
  ↓ 执行操作
RetryHandler.handle_retry()
  ↓ ActionResult
ExecutionResult
```

---

## 数据压缩与智能过滤流程

### 完整调用链

```
WorkflowOrchestrator.process_recording_v2()
  ↓
DataPreprocessorV2.preprocess_with_analysis()
  ├─→ _merge_consecutive_inputs()
  ├─→ _filter_duplicate_actions()
  └─→ RequestIntelligenceAnalyzer.analyze_requests()
  ↓
RequestIntelligenceAnalyzer._rule_engine_check()
  ├─→ 检查域名
  ├─→ 检查 URL 模式
  ├─→ 检查内容类型
  └─→ 检查响应大小
  ↓
EncryptionDetector.is_encrypted()
  ├─→ Base64 检测
  ├─→ 熵值分析
  └─→ 加密模式识别
  ↓
DependencyAnalyzer.is_independent()
  ├─→ Cookie 依赖分析
  ├─→ Token 依赖分析
  └─→ 引用分析
  ↓
(如果启用) LLMClient.call_api()
  ↓ LangChainLLMClient
  ↓ 数据压缩模型分析
  ↓
返回过滤后的网络请求列表
```

### 关键类和方法

#### 1. RequestIntelligenceAnalyzer (request_intelligence_analyzer.py)

```python
class RequestIntelligenceAnalyzer:
    def __init__(self, config: Dict):
        # 初始化各个组件
        self.encryption_detector = EncryptionDetector()
        self.dependency_analyzer = DependencyAnalyzer()
        self.rule_engine = RuleEngine()

        # 数据压缩模型（可选）
        self.use_compression_model = config.get('use_compression_model', False)
        if self.use_compression_model:
            self.llm_client = LangChainLLMClient(config['compression_model'])

    def analyze_requests(
        self,
        actions: List[Action],
        requests: List[NetworkRequestDetail]
    ) -> List[NetworkRequestDetail]:
        """智能分析网络请求"""

        valid_requests = []
        edge_cases = []  # 边缘案例

        for request in requests:
            # 1. 规则引擎快速过滤
            if not self._rule_engine_check(request):
                continue

            # 2. 加密检测
            if self.encryption_detector.is_encrypted(request):
                continue

            # 3. 依赖分析
            if not self.dependency_analyzer.is_independent(request):
                continue

            # 4. 数据压缩模型分析边缘案例
            if self.use_compression_model:
                is_edge_case = self._is_edge_case(request)
                if is_edge_case:
                    edge_cases.append(request)
                    continue

            valid_requests.append(request)

        # 5. 对边缘案例使用数据压缩模型
        if edge_cases and self.use_compression_model:
            model_valid = self._llm_analyze_edge_cases(edge_cases)
            valid_requests.extend(model_valid)

        return valid_requests
```

#### 2. RuleEngine (request_intelligence_analyzer.py)

```python
class RequestIntelligenceAnalyzer:
    def _rule_engine_check(self, request: NetworkRequestDetail) -> bool:
        """规则引擎检查（30+ 条规则）"""

        url = request.url.lower()
        content_type = request.response_headers.get('content-type', '').lower()

        # 规则 1: 排除静态资源
        static_extensions = [
            '.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg',
            '.ico', '.woff', '.woff2', '.ttf', '.eot'
        ]
        if any(url.endswith(ext) for ext in static_extensions):
            return False

        # 规则 2: 排除常见追踪/分析域名
        excluded_domains = [
            'google-analytics.com', 'googletagmanager.com',
            'facebook.com/tr', 'doubleclick.net', 'stats.g.doubleclick.net'
        ]
        if any(domain in url for domain in excluded_domains):
            return False

        # 规则 3: 只接受 JSON 响应
        if 'application/json' not in content_type:
            return False

        # 规则 4: 排除过小的响应
        if request.response_size < 100:
            return False

        # ... 更多规则 ...

        return True
```

#### 3. EncryptionDetector (encryption_detector.py)

```python
class EncryptionDetector:
    def is_encrypted(self, request: NetworkRequestDetail) -> bool:
        """检测响应是否加密"""

        # 1. Base64 检测
        if self._is_base64(request.response_body):
            return True

        # 2. 熵值分析
        entropy = self._calculate_entropy(request.response_body)
        if entropy > 7.5:  # 高熵值表示可能加密
            return True

        # 3. 加密模式识别
        if self._has_encryption_patterns(request.response_body):
            return True

        return False

    def _calculate_entropy(self, data: bytes) -> float:
        """计算熵值"""
        if not data:
            return 0

        byte_counts = collections.Counter(data)
        total_bytes = len(data)

        entropy = 0
        for count in byte_counts.values():
            probability = count / total_bytes
            entropy -= probability * math.log2(probability)

        return entropy
```

#### 4. DependencyAnalyzer (dependency_analyzer.py)

```python
class DependencyAnalyzer:
    def is_independent(self, request: NetworkRequestDetail) -> bool:
        """检查请求是否独立（无依赖）"""

        # 1. Cookie 依赖
        if self._has_cookie_dependency(request):
            return False

        # 2. Token 依赖
        if self._has_token_dependency(request):
            return False

        # 3. 动态引用依赖
        if self._has_dynamic_reference(request):
            return False

        return True

    def _has_cookie_dependency(self, request: NetworkRequestDetail) -> bool:
        """检查是否有 Cookie 依赖"""
        request_headers = request.request_headers

        # 如果请求需要 Cookie
        if 'cookie' in request_headers:
            return True

        # 如果响应设置 Cookie
        set_cookie = request.response_headers.get('set-cookie')
        if set_cookie:
            return True

        return False
```

### 数据流

```
原始网络请求列表
  ↓ RequestIntelligenceAnalyzer.analyze_requests()
规则引擎过滤（30+ 条规则）
  ↓ 快速排除明显无效的请求
加密检测
  ↓ 排除加密的响应
依赖分析
  ↓ 排除有依赖的请求
边缘案例识别
  ↓ LLM 客户端（数据压缩模型）
  ↓ LangChain 统一接口
  ↓ Anthropic/OpenAI API
过滤后的网络请求列表
  ↓ NetworkAnalyzer.analyze_recording()
可复现 API 列表
```

---

## 总结

### 文件位置索引

| 模块 | 关键文件 |
|------|---------|
| **录制** | `src/recording/recorder.py`, `src/recording/browser_recorder.py` |
| **WebSocket** | `src/recording/websocket_server.py` |
| **AI 处理** | `src/business/ai/workflow_orchestrator.py` |
| **数据预处理** | `src/business/ai/data_preprocessor.py` |
| **智能过滤** | `src/business/ai/request_intelligence_analyzer.py` |
| **网络分析** | `src/business/ai/network_analyzer.py` |
| **列表分析** | `src/business/ai/list_operation_analyzer.py` |
| **代码生成** | `src/business/ai/semantic_analyzer.py`, `src/business/ai/llm_client.py` |
| **执行引擎** | `src/execution/executor.py`, `src/execution/action_executor.py` |
| **元素定位** | `src/drivers/locator/multi_layer_locator.py` |
| **事件系统** | `src/utils/events.py` |
| **数据存储** | `src/data/duckdb_manager.py`, `src/data/repositories.py` |

### 调用关系图

```
BrowserRecorder
  ↓ emit('recording_completed')
WorkflowOrchestrator
  ↓ DataPreprocessorV2
    ↓ RequestIntelligenceAnalyzer
      ↓ EncryptionDetector, DependencyAnalyzer
  ↓ NetworkAnalyzer
  ↓ ListOperationAnalyzer
  ↓ SemanticAnalyzer
    ↓ LLMClient
  ↓ ToolRepository
    ↓ SQLite
```

---

**维护说明**:
- 每次代码重构时更新本文档
- 保持调用链的准确性
- 添加新的流程时遵循相同的格式

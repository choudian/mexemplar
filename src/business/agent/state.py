"""
LangGraph Agent 状态定义

定义 Agent 在执行过程中需要维护的状态数据。
"""

from typing import Annotated, Optional, Dict, List, Any
from langgraph.graph import add_messages
from langgraph.graph import MessagesState
from dataclasses import dataclass, field


@dataclass
class PatternRecognition:
    """操作模式识别结果"""
    primary_pattern: str = ""  # 操作模式名称（搜索、列表采集、表单填写等）
    confidence: float = 0.0  # 置信度 0-1
    description: str = ""  # 模式描述
    sub_patterns: List[str] = field(default_factory=list)  # 子模式


@dataclass
class ParameterizationItem:
    """参数化分析项"""
    element: str = ""  # 元素描述
    element_selector: str = ""  # CSS选择器
    recorded_value: str = ""  # 录制时的值
    should_parameterize: str = "uncertain"  # true | false | "uncertain"
    reason: str = ""  # 判断理由
    confidence: float = 0.0  # 置信度 0-1
    parameter_name: str = ""  # 建议的参数名
    parameter_type: str = "string"  # string | number | boolean | list
    default_value: str = ""  # 建议的默认值
    need_confirmation: bool = False  # 是否需要用户确认


@dataclass
class FieldSpec:
    """字段规范"""
    type: str  # string | number | boolean | url | selector
    description: str
    required: bool = True


@dataclass
class OutputSpec:
    """输出规范"""
    data_type: str  # object | array | string | number | boolean
    description: str

    # 如果是 object，定义字段
    fields: Dict[str, FieldSpec] = None

    # 如果是 array，定义元素类型
    item_type: str = None  # array元素的类型
    item_fields: Dict[str, FieldSpec] = None  # array元素的字段


@dataclass
class ParameterSpec:
    """参数规范"""
    name: str  # 参数名（代码中使用）
    label: str  # 显示标签（用户界面显示）
    type: str  # string | number | boolean | url | selector
    required: bool
    default_value: Any = None  # 默认值
    description: str = ""  # 参数描述
    example: str = ""  # 示例值
    validation: str = ""  # 验证规则


@dataclass
class LocatorInfo:
    """定位信息（用于浏览器场景）"""
    locator_type: str = ""  # xpath | css_selector | coordinate
    value: str = ""
    fallback: List[str] = field(default_factory=list)


@dataclass
class ExecutionStep:
    """执行步骤"""
    step_number: int
    step_name: str
    action_type: str  # browser_navigate | browser_click | browser_input | ...
    description: str
    parameters: Dict[str, Any]
    locator_info: Optional[LocatorInfo] = None


@dataclass
class ExecutionEnvironment:
    """执行环境要求"""
    required_libraries: List[str]
    python_version: str = "3.11"

    # 场景特定配置
    platform_config: Dict[str, Any] = None


@dataclass
class ExecutionBlueprint:
    """执行蓝图：代码生成需要的完整信息"""
    # 工具基本信息
    tool_name: str
    tool_summary: str
    category: str  # browser_automation | desktop_automation | ...

    # 输入参数
    input_parameters: List[ParameterSpec]

    # 输出规范
    output_spec: OutputSpec

    # 执行步骤
    execution_steps: List[ExecutionStep]

    # 执行环境
    execution_environment: ExecutionEnvironment

    # 隐含需求
    implicit_requirements: List[str]

    # 边界情况
    edge_cases: List[str]


@dataclass
class ConfirmationQuestion:
    """确认问题"""
    id: str = ""  # 问题ID
    question: str = ""  # 确认问题（自然语言）
    context: str = ""  # 为什么需要确认这个问题
    options: List[Dict[str, str]] = field(default_factory=list)  # 选项列表
    recommended: str = ""  # 推荐的选项值
    priority: str = "medium"  # high | medium | low


@dataclass
class ToolDescription:
    """工具描述"""
    name: str = ""
    description: str = ""  # 工具功能描述（面向普通用户）
    category: str = ""  # 搜索工具 | 数据采集 | 表单填写 | 其他
    input_parameters: List[Dict[str, Any]] = field(default_factory=list)
    natural_language_description: str = ""  # 完整的自然语言描述
    use_cases: List[str] = field(default_factory=list)
    estimated_time: str = ""
    requires_login: bool = False
    requires_human_intervention: bool = False
    intervention_points: List[str] = field(default_factory=list)


@dataclass
class IntentAnalysisResult:
    """意图分析结果（完整版）"""
    # 模式识别
    pattern_recognition: PatternRecognition = field(default_factory=PatternRecognition)

    # 意图分析
    surface_operations: List[str] = field(default_factory=list)  # 表层操作
    deep_intent: str = ""  # 深层意图
    final_goal: str = ""  # 最终目标
    user_needs: str = ""  # 用户想要获得什么

    # 参数化分析
    parameterization_analysis: List[ParameterizationItem] = field(default_factory=list)

    # 确认问题
    confirmation_questions: List[ConfirmationQuestion] = field(default_factory=list)

    # 执行蓝图（代码生成所需的完整信息）
    execution_blueprint: ExecutionBlueprint = None

    # 工具描述（向下兼容）
    tool_description: ToolDescription = field(default_factory=ToolDescription)

    # 代码生成提示（向下兼容）
    libraries_needed: List[str] = field(default_factory=list)
    complexity: str = "simple"  # simple | medium | complex
    error_handling_needed: List[str] = field(default_factory=list)
    special_considerations: List[str] = field(default_factory=list)


@dataclass
class IntentData:
    """意图分析结果数据（简化版，用于状态传递）"""
    intent_type: str  # 'browser_automation' | 'api_call' | 'hybrid'
    description: str  # 用户意图描述
    parameters: Dict[str, Any] = field(default_factory=dict)  # 参数定义
    confidence: float = 0.0  # 置信度 0-1
    raw_analysis: Dict[str, Any] = field(default_factory=dict)  # 原始分析结果

    # 新增：完整分析结果
    full_analysis: Optional[IntentAnalysisResult] = None

    # 新增：用户对确认问题的回答
    user_confirmations: Dict[str, str] = field(default_factory=dict)  # {question_id: selected_value}


@dataclass
class ToolDraft:
    """草稿工具数据"""
    tool_id: Optional[str] = None
    tool_name: str = ""
    description: str = ""
    execution_code: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    execution_strategy: str = "browser"  # 'api' | 'browser' | 'hybrid'


class AgentState(MessagesState):
    """
    Agent 状态定义

    继承 MessagesState，自动累积对话消息。

    状态字段说明：
    - messages: 对话消息历史（自动累积）
    - recording_data: 压缩后的录制数据（输入）
    - current_intent: 当前意图分析结果
    - tool_draft: 当前生成的工具草稿
    - execution_result: 工具执行结果
    - error_info: 错误信息（如果有）
    - requires_user_confirmation: 是否需要用户确认
    - conversation_type: 对话类型
    - confirmation_progress: 分页确认进度状态
    """

    # 录制数据（输入）
    recording_data: Optional[Dict[str, Any]] = None

    # 意图分析结果
    current_intent: Optional[IntentData] = None

    # 工具草稿
    tool_draft: Optional[ToolDraft] = None

    # 工具执行结果
    execution_result: Optional[Dict[str, Any]] = None

    # 错误信息
    error_info: Optional[Dict[str, Any]] = None

    # 用户确认标志
    requires_user_confirmation: bool = False

    # 对话类型
    conversation_type: str = "tool_generation"  # 'tool_generation' | 'task_execution' | 'chat'

    # 工具库（用于任务执行）
    available_tools: List[Dict[str, Any]] = field(default_factory=list)

    # 匹配到的工具
    matched_tool: Optional[Dict[str, Any]] = None

    # 工具执行参数
    tool_parameters: Optional[Dict[str, Any]] = None

    # 分页确认进度状态
    # 用于跟踪意图确认的分页问答进度
    confirmation_progress: Dict[str, Any] = field(default_factory=lambda: {
        "current_index": 0,       # 当前问题索引
        "total_questions": 0,     # 总问题数
        "answers": {},            # {question_id: selected_value}
        "completed": False,       # 是否全部完成
        "invalidated": False,     # 是否被用户打断废弃
        "invalidated_answers": {}  # 被废弃的回答（用于追溯）
    })

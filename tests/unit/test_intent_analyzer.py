"""
意图分析器单元测试
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from src.business.intent.intent_analyzer import IntentAnalyzer
from src.business.ai.prompts.intent_analysis_models import (
    IntentAnalysisResult,
    Intent,
    CoreOperation,
    SuggestedParameter,
    ParameterType,
)


@pytest.fixture
def mock_llm_client():
    """模拟 LLM 客户端"""
    client = MagicMock()
    client.call_llm = AsyncMock()
    return client


@pytest.fixture
def sample_recording_session():
    """示例录制会话数据"""
    return {
        "recording_id": "test-recording-001",
        "recording_mode": "browser",
        "start_time": 1234567890.0,
        "end_time": 1234567950.0,
        "actions": [
            {
                "action_type": "click",
                "recording_mode": "browser",
                "url": "https://www.baidu.com",
                "timestamp": 1234567891.0,
                "parameters": {},
            },
            {
                "action_type": "keyboard_input",
                "recording_mode": "browser",
                "url": "https://www.baidu.com",
                "timestamp": 1234567892.0,
                "parameters": {"value": "Python教程"},
            },
            {
                "action_type": "click",
                "recording_mode": "browser",
                "url": "https://www.baidu.com",
                "dom_element": {"tag": "button", "text": "百度一下"},
                "timestamp": 1234567893.0,
                "parameters": {},
            },
        ],
    }


@pytest.fixture
def sample_intent_analysis_response():
    """示例意图分析响应"""
    return """{
  "core_operations": [
    {
      "operation": "打开百度首页",
      "action_index": 0,
      "importance": 0.6,
      "parameters": {}
    },
    {
      "operation": "输入搜索关键词",
      "action_index": 1,
      "importance": 1.0,
      "parameters": {"keyword": "Python教程"}
    },
    {
      "operation": "点击搜索按钮",
      "action_index": 2,
      "importance": 0.9,
      "parameters": {}
    }
  ],
  "target": "百度",
  "business_scenario": "数据查询 - 在搜索引擎中查找信息",
  "expected_results": [
    "获取搜索结果列表",
    "找到相关的Python教程资源"
  ],
  "suggested_parameters": [
    {
      "name": "search_keyword",
      "type": "text",
      "description": "搜索关键词",
      "default_value": "Python教程",
      "required": true
    }
  ],
  "confidence": 0.95,
  "reasoning": "用户在百度搜索引擎中输入关键词并点击搜索，目标是获取相关搜索结果"
}"""


@pytest.mark.asyncio
async def test_analyze_intent_success(
    mock_llm_client, sample_recording_session, sample_intent_analysis_response
):
    """测试成功分析意图"""
    # 设置模拟响应
    mock_llm_client.call_llm.return_value = sample_intent_analysis_response

    # 创建分析器
    analyzer = IntentAnalyzer(mock_llm_client)

    # 执行分析
    result = await analyzer.analyze_intent(sample_recording_session)

    # 验证结果
    assert result.recording_id == "test-recording-001"
    assert result.target == "百度"
    assert result.business_scenario == "数据查询 - 在搜索引擎中查找信息"
    assert result.confidence == 0.95
    assert len(result.core_operations) == 3
    assert len(result.expected_results) == 2
    assert len(result.suggested_parameters) == 1

    # 验证核心操作
    op1 = result.core_operations[0]
    assert op1.operation == "打开百度首页"
    assert op1.action_index == 0
    assert op1.importance == 0.6

    op2 = result.core_operations[1]
    assert op2.operation == "输入搜索关键词"
    assert op2.importance == 1.0
    assert op2.parameters == {"keyword": "Python教程"}

    # 验证参数
    param = result.suggested_parameters[0]
    assert param.name == "search_keyword"
    assert param.type == ParameterType.TEXT
    assert param.description == "搜索关键词"
    assert param.default_value == "Python教程"
    assert param.required is True


@pytest.mark.asyncio
async def test_analyze_intent_llm_error(mock_llm_client, sample_recording_session):
    """测试 LLM 调用失败的情况"""
    # 设置模拟抛出异常
    mock_llm_client.call_llm.side_effect = Exception("LLM API error")

    # 创建分析器
    analyzer = IntentAnalyzer(mock_llm_client)

    # 执行分析
    result = await analyzer.analyze_intent(sample_recording_session)

    # 验证返回默认结果
    assert result.confidence == 0.0
    assert result.status == "failed"
    assert "分析过程出错" in result.reasoning
    assert len(result.core_operations) == 0


@pytest.mark.asyncio
async def test_analyze_intent_invalid_json(
    mock_llm_client, sample_recording_session
):
    """测试 LLM 返回无效 JSON 的情况"""
    # 设置模拟响应为无效 JSON
    mock_llm_client.call_llm.return_value = "This is not a valid JSON"

    # 创建分析器
    analyzer = IntentAnalyzer(mock_llm_client)

    # 执行分析，应该返回默认结果（因为错误被捕获）
    result = await analyzer.analyze_intent(sample_recording_session)

    # 验证返回默认结果
    assert result.confidence == 0.0
    assert result.status == "failed"
    assert "不是有效的 JSON" in result.reasoning


@pytest.mark.asyncio
async def test_refine_intent(
    mock_llm_client, sample_recording_session, sample_intent_analysis_response
):
    """测试优化意图"""
    # 设置初次分析响应
    mock_llm_client.call_llm.return_value = sample_intent_analysis_response

    # 创建分析器
    analyzer = IntentAnalyzer(mock_llm_client)

    # 先执行初次分析
    original_intent = await analyzer.analyze_intent(sample_recording_session)

    # 设置优化响应
    refined_response = """{
  "core_operations": [
    {
      "operation": "打开浏览器",
      "action_index": -1,
      "importance": 0.5,
      "parameters": {}
    },
    {
      "operation": "输入搜索关键词",
      "action_index": 1,
      "importance": 1.0,
      "parameters": {}
    },
    {
      "operation": "点击搜索按钮",
      "action_index": 2,
      "importance": 0.9,
      "parameters": {}
    }
  ],
  "target": "百度",
  "business_scenario": "数据查询 - 在搜索引擎中查找信息",
  "expected_results": [
    "获取搜索结果列表"
  ],
  "suggested_parameters": [],
  "confidence": 0.95,
  "reasoning": "根据用户反馈，添加了'打开浏览器'步骤"
}"""
    mock_llm_client.call_llm.return_value = refined_response

    # 执行优化
    refined_intent = await analyzer.refine_intent(
        original_intent=original_intent,
        user_feedback="还需要添加打开浏览器的步骤",
    )

    # 验证优化结果（返回了3个操作，替换了原来的操作）
    assert len(refined_intent.core_operations) == 3
    assert refined_intent.core_operations[0].operation == "打开浏览器"
    assert refined_intent.core_operations[0].action_index == -1
    assert "根据用户反馈" in refined_intent.reasoning


@pytest.mark.asyncio
async def test_create_intent_from_recording(
    mock_llm_client, sample_recording_session, sample_intent_analysis_response
):
    """测试从录制会话创建意图对象"""
    # 设置模拟响应
    mock_llm_client.call_llm.return_value = sample_intent_analysis_response

    # 创建分析器
    analyzer = IntentAnalyzer(mock_llm_client)

    # 创建意图
    intent = await analyzer.create_intent_from_recording(sample_recording_session)

    # 验证意图对象
    assert intent.recording_id == "test-recording-001"
    assert intent.status == "pending_confirmation"
    assert intent.analysis_result.target == "百度"
    assert len(intent.confirmation_turns) == 0
    assert intent.created_at > 0
    assert intent.updated_at > 0


@pytest.mark.asyncio
async def test_add_confirmation_turn(
    mock_llm_client, sample_recording_session, sample_intent_analysis_response
):
    """测试添加确认对话轮次"""
    # 设置模拟响应
    mock_llm_client.call_llm.return_value = sample_intent_analysis_response

    # 创建分析器和意图
    analyzer = IntentAnalyzer(mock_llm_client)
    intent = await analyzer.create_intent_from_recording(sample_recording_session)

    # 添加对话轮次
    turn = await analyzer.add_confirmation_turn(
        intent=intent,
        user_feedback="还需要记住密码",
        assistant_response="好的，已添加记住密码功能",
        updated_intent=intent.analysis_result,  # 简化，使用同一个结果
    )

    # 验证对话轮次
    assert turn.intent_id == intent.intent_id
    assert turn.user_feedback == "还需要记住密码"
    assert turn.assistant_response == "好的，已添加记住密码功能"
    assert turn.timestamp > 0

    # 验证意图已更新
    assert len(intent.confirmation_turns) == 1
    assert intent.updated_at == turn.timestamp


def test_validate_intent_valid(mock_llm_client):
    """测试验证有效的意图"""
    # 创建分析器
    analyzer = IntentAnalyzer(mock_llm_client)

    # 创建有效的意图
    intent = Intent(
        intent_id="test-intent-001",
        recording_id="test-recording-001",
        analysis_result=IntentAnalysisResult(
            core_operations=[
                CoreOperation(
                    operation="打开网站", action_index=0, importance=0.8
                ),
                CoreOperation(
                    operation="输入关键词", action_index=1, importance=1.0
                ),
            ],
            target="百度",
            business_scenario="数据查询 - 搜索",
            expected_results=["获取搜索结果"],
            suggested_parameters=[
                SuggestedParameter(
                    name="keyword",
                    type=ParameterType.TEXT,
                    description="搜索关键词",
                )
            ],
            confidence=0.9,
            reasoning="分析清晰",
        ),
        status="pending_confirmation",
    )

    # 验证
    result = analyzer.validate_intent(intent)

    assert result["is_valid"] is True
    assert len(result["issues"]) == 0
    assert result["confidence"] == 0.9
    assert result["operation_count"] == 2


def test_validate_intent_invalid_low_confidence(mock_llm_client):
    """测试验证低置信度的意图"""
    # 创建分析器
    analyzer = IntentAnalyzer(mock_llm_client)

    # 创建低置信度意图
    intent = Intent(
        intent_id="test-intent-002",
        recording_id="test-recording-002",
        analysis_result=IntentAnalysisResult(
            core_operations=[
                CoreOperation(
                    operation="打开网站", action_index=0, importance=0.8
                ),
            ],
            target="百度",
            business_scenario="数据查询 - 搜索",
            expected_results=[],
            suggested_parameters=[],
            confidence=0.5,  # 低置信度
            reasoning="分析不清晰",
        ),
        status="pending_confirmation",
    )

    # 验证
    result = analyzer.validate_intent(intent)

    assert result["is_valid"] is False
    assert len(result["issues"]) > 0
    assert any("置信度较低" in issue for issue in result["issues"])
    assert any("建议与用户确认" in s for s in result["suggestions"])


def test_validate_intent_invalid_no_operations(mock_llm_client):
    """测试验证无核心操作的意图"""
    # 创建分析器
    analyzer = IntentAnalyzer(mock_llm_client)

    # 创建无核心操作的意图
    intent = Intent(
        intent_id="test-intent-003",
        recording_id="test-recording-003",
        analysis_result=IntentAnalysisResult(
            core_operations=[],  # 无核心操作
            target="",
            business_scenario="",
            expected_results=[],
            suggested_parameters=[],
            confidence=0.0,
            reasoning="无数据",
        ),
        status="pending_confirmation",
    )

    # 验证
    result = analyzer.validate_intent(intent)

    assert result["is_valid"] is False
    assert len(result["issues"]) >= 3  # 操作、目标、场景都有问题
    assert result["operation_count"] == 0


def test_format_recording_data():
    """测试格式化录制数据"""
    from src.business.ai.prompts.intent_analysis_prompt import format_recording_data

    session = {
        "recording_id": "test-001",
        "recording_mode": "browser",
        "start_time": 100.0,
        "end_time": 200.0,
        "actions": [
            {
                "action_type": "click",
                "recording_mode": "browser",
                "url": "https://example.com",
                "timestamp": 110.0,
            },
            {
                "action_type": "keyboard_input",
                "recording_mode": "browser",
                "url": "https://example.com",
                "parameters": {"value": "test"},
                "timestamp": 120.0,
            },
        ],
    }

    formatted = format_recording_data(session)

    assert formatted["recording_id"] == "test-001"
    assert formatted["recording_mode"] == "browser"
    assert formatted["duration"] == 100.0
    assert "操作1: click" in formatted["actions_summary"]
    assert "操作2: input" in formatted["actions_summary"]
    # actions_details 是一个字符串，不是列表
    assert "### 操作1" in formatted["actions_details"]
    assert "### 操作2" in formatted["actions_details"]


def test_format_conversation_history():
    """测试格式化对话历史"""
    from src.business.ai.prompts.intent_analysis_prompt import format_conversation_history

    history = [
        {"role": "user", "content": "还需要添加记住密码"},
        {"role": "assistant", "content": "好的，已添加"},
    ]

    formatted = format_conversation_history(history)

    assert "第1轮对话" in formatted
    assert "用户: 还需要添加记住密码" in formatted
    assert "助手: 好的，已添加" in formatted


def test_format_conversation_history_empty():
    """测试格式化空对话历史"""
    from src.business.ai.prompts.intent_analysis_prompt import format_conversation_history

    formatted = format_conversation_history([])

    assert formatted == "（无对话历史）"

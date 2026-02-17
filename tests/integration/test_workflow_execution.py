"""
工作流执行集成测试

这些测试需要真实的浏览器环境，因此运行较慢。
使用 pytest.mark.asyncio 标记异步测试。
"""

import pytest
from src.data.models import Tool
from src.execution.executor import WorkflowExecutor

# 跳过所有工作流执行测试，因为执行引擎尚未完成
pytestmark = pytest.mark.skip(reason="执行引擎尚未完成，需要 Playwright 浏览器支持")

# 注意：这些测试需要安装并运行 Playwright
# 运行前需要执行: uv run playwright install chromium


@pytest.mark.asyncio
async def test_simple_navigation():
    """测试简单的导航操作"""
    # 创建一个简单的导航工具
    tool = Tool(
        tool_name="测试导航",
        description="导航到百度首页",
        parameters=[],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate_to_baidu",
                "action_type": "navigate",
                "description": "导航到百度首页",
                "parameters": {"url": "https://www.baidu.com"},
            }
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(tool, parameters={})

    # 验证结果
    assert context.status.value == "success"
    assert len(context.step_results) == 1
    assert "navigate_to_baidu" in context.step_results
    assert context.step_results["navigate_to_baidu"].success


@pytest.mark.asyncio
async def test_navigate_and_fill():
    """测试导航和输入操作"""
    tool = Tool(
        tool_name="百度搜索",
        description="在百度搜索关键词",
        parameters=[{"name": "keyword", "type": "string", "description": "搜索关键词"}],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate_to_baidu",
                "action_type": "navigate",
                "description": "导航到百度首页",
                "parameters": {"url": "https://www.baidu.com"},
            },
            {
                "step_number": 2,
                "step_name": "fill_search_box",
                "action_type": "fill",
                "description": "在搜索框中输入关键词",
                "parameters": {"value": "{{keyword}}"},
                "locator_info": {"type": "css_selector", "value": "#kw"},
            },
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(tool, parameters={"keyword": "Python"})

    # 验证结果
    assert context.status.value == "success"
    assert len(context.step_results) == 2
    assert context.step_results["navigate_to_baidu"].success
    assert context.step_results["fill_search_box"].success


@pytest.mark.asyncio
async def test_navigate_fill_and_click():
    """测试导航、输入和点击操作"""
    tool = Tool(
        tool_name="百度搜索并提交",
        description="在百度搜索并点击搜索按钮",
        parameters=[{"name": "keyword", "type": "string", "description": "搜索关键词"}],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate_to_baidu",
                "action_type": "navigate",
                "description": "导航到百度首页",
                "parameters": {"url": "https://www.baidu.com"},
            },
            {
                "step_number": 2,
                "step_name": "fill_search_box",
                "action_type": "fill",
                "description": "在搜索框中输入关键词",
                "parameters": {"value": "{{keyword}}"},
                "locator_info": {"type": "css_selector", "value": "#kw"},
            },
            {
                "step_number": 3,
                "step_name": "click_search_button",
                "action_type": "click",
                "description": "点击搜索按钮",
                "locator_info": {"type": "css_selector", "value": "#su"},
            },
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(tool, parameters={"keyword": "Playwright"})

    # 验证结果
    assert context.status.value == "success"
    assert len(context.step_results) == 3
    assert all(r.success for r in context.step_results.values())


@pytest.mark.asyncio
async def test_parameter_resolution():
    """测试参数解析功能"""
    tool = Tool(
        tool_name="参数解析测试",
        description="测试参数解析",
        parameters=[
            {"name": "search_term", "type": "string"},
            {"name": "target_url", "type": "string"},
        ],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate",
                "action_type": "navigate",
                "parameters": {"url": "{{target_url}}"},
            },
            {
                "step_number": 2,
                "step_name": "fill",
                "action_type": "fill",
                "parameters": {"value": "{{search_term}}"},
                "locator_info": {"type": "css_selector", "value": "#kw"},
            },
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(
        tool, parameters={"search_term": "测试搜索", "target_url": "https://www.baidu.com"}
    )

    assert context.status.value == "success"
    assert context.step_results["navigate"].result["url"] == "https://www.baidu.com"
    assert context.step_results["fill"].result["value"] == "测试搜索"


@pytest.mark.asyncio
async def test_wait_and_scroll():
    """测试等待和滚动操作"""
    tool = Tool(
        tool_name="等待和滚动测试",
        description="测试等待和滚动",
        parameters=[],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate",
                "action_type": "navigate",
                "parameters": {"url": "https://www.baidu.com"},
            },
            {
                "step_number": 2,
                "step_name": "wait",
                "action_type": "wait",
                "parameters": {"duration": 1000},  # 1秒
            },
            {
                "step_number": 3,
                "step_name": "scroll_down",
                "action_type": "scroll",
                "parameters": {"direction": "down", "pixels": 500},
            },
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(tool, parameters={})

    assert context.status.value == "success"
    assert context.step_results["wait"].result["duration"] == 1000
    assert context.step_results["scroll_down"].result["scrolled"]


@pytest.mark.asyncio
async def test_error_handling_continue():
    """测试错误处理（继续执行）"""
    tool = Tool(
        tool_name="错误处理测试",
        description="测试错误处理",
        parameters=[],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate",
                "action_type": "navigate",
                "parameters": {"url": "https://www.baidu.com"},
            },
            {
                "step_number": 2,
                "step_name": "fail_step",
                "action_type": "click",
                "description": "这步会失败（元素不存在）",
                "locator_info": {"type": "css_selector", "value": "#non-existent-element"},
                "error_handling": {"on_failure": "continue"},
            },
            {
                "step_number": 3,
                "step_name": "wait",
                "action_type": "wait",
                "parameters": {"duration": 500},
            },
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(tool, parameters={})

    # 第2步失败但第3步应该继续执行
    assert context.step_results["navigate"].success
    assert not context.step_results["fail_step"].success
    assert context.step_results["wait"].success
    assert len(context.step_results) == 3


@pytest.mark.asyncio
async def test_error_handling_abort():
    """测试错误处理（中止执行）"""
    tool = Tool(
        tool_name="错误中止测试",
        description="测试错误中止",
        parameters=[],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate",
                "action_type": "navigate",
                "parameters": {"url": "https://www.baidu.com"},
            },
            {
                "step_number": 2,
                "step_name": "fail_step",
                "action_type": "click",
                "description": "这步会失败并中止",
                "locator_info": {"type": "css_selector", "value": "#non-existent-element"},
                "error_handling": {"on_failure": "abort"},  # 默认值
            },
            {
                "step_number": 3,
                "step_name": "wait",
                "action_type": "wait",
                "parameters": {"duration": 500},
            },
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(tool, parameters={})

    # 第2步失败后，第3步不应该执行
    assert context.step_results["navigate"].success
    assert not context.step_results["fail_step"].success
    assert context.status.value == "failed"
    assert len(context.step_results) == 2  # 第3步未执行


@pytest.mark.asyncio
async def test_extract_data():
    """测试数据提取"""
    tool = Tool(
        tool_name="数据提取测试",
        description="测试从页面提取数据",
        parameters=[],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate",
                "action_type": "navigate",
                "parameters": {"url": "https://www.baidu.com"},
            },
            {
                "step_number": 2,
                "step_name": "extract_title",
                "action_type": "extract",
                "parameters": {"extract_type": "title"},
            },
            {
                "step_number": 3,
                "step_name": "extract_url",
                "action_type": "extract",
                "parameters": {"extract_type": "url"},
            },
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(tool, parameters={})

    assert context.status.value == "success"
    assert context.step_results["extract_title"].success
    assert context.step_results["extract_url"].success
    assert context.step_results["extract_title"].result["extract_type"] == "title"
    assert context.step_results["extract_url"].result["extract_type"] == "url"
    assert "baidu" in context.step_results["extract_url"].result["value"].lower()


@pytest.mark.asyncio
async def test_execution_context_properties():
    """测试执行上下文属性"""
    tool = Tool(
        tool_name="上下文测试",
        description="测试执行上下文",
        parameters=[],
        steps=[
            {
                "step_number": 1,
                "step_name": "step1",
                "action_type": "navigate",
                "parameters": {"url": "https://www.baidu.com"},
            },
            {
                "step_number": 2,
                "step_name": "step2",
                "action_type": "wait",
                "parameters": {"duration": 500},
            },
            {
                "step_number": 3,
                "step_name": "step3",
                "action_type": "wait",
                "parameters": {"duration": 500},
            },
        ],
    )

    executor = WorkflowExecutor()
    context = await executor.execute(tool, parameters={})

    # 验证上下文属性
    assert context.execution_id is not None
    assert context.tool_id == tool.tool_id
    assert context.status.value == "success"
    assert context.total_steps == 3
    assert context.current_step == 3
    assert abs(context.progress - 1.0) < 0.01
    assert context.duration is not None
    assert context.started_at is not None
    assert context.finished_at is not None


# 同步版本测试
def test_execute_sync():
    """测试同步执行接口"""
    tool = Tool(
        tool_name="同步测试",
        description="测试同步执行",
        parameters=[],
        steps=[
            {
                "step_number": 1,
                "step_name": "navigate",
                "action_type": "navigate",
                "parameters": {"url": "https://www.baidu.com"},
            }
        ],
    )

    executor = WorkflowExecutor()
    context = executor.execute_sync(tool, parameters={})

    assert context.status.value == "success"
    assert len(context.step_results) == 1

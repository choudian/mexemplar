"""
数据库模块单元测试
"""

import pytest
import tempfile
import os
from pathlib import Path

from src.data.database import DatabaseManager, init_database
from src.data.models import Tool, TaskExecution, Conversation
from src.data.repositories import ToolRepository, TaskExecutionRepository, ConversationRepository


@pytest.fixture
def temp_db():
    """创建临时数据库"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    db_manager = DatabaseManager(db_path)
    db_manager.initialize()

    yield db_manager

    # 清理
    db_manager.close()
    if os.path.exists(db_path):
        os.remove(db_path)


def test_database_initialization(temp_db):
    """测试数据库初始化"""
    conn = temp_db.connect()
    cursor = conn.cursor()

    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]

    assert "tools" in tables
    assert "task_executions" in tables
    assert "conversations" in tables
    assert "schema_version" in tables


def test_tool_repository(temp_db):
    """测试工具仓库"""
    repo = ToolRepository(temp_db)

    # 创建工具
    tool = Tool(
        tool_name="测试工具",
        description="这是一个测试工具",
        parameters=[{"name": "keyword", "type": "string"}],
        steps=[{"action": "click", "target": "button"}],
    )

    created_tool = repo.create(tool)
    assert created_tool.tool_id == tool.tool_id

    # 获取工具
    retrieved_tool = repo.get_by_id(tool.tool_id)
    assert retrieved_tool is not None
    assert retrieved_tool.tool_name == "测试工具"

    # 更新工具
    retrieved_tool.tool_name = "更新的工具名"
    updated_tool = repo.update(retrieved_tool)
    assert updated_tool.tool_name == "更新的工具名"

    # 删除工具
    deleted = repo.delete(tool.tool_id)
    assert deleted is True

    # 验证已删除
    retrieved_tool = repo.get_by_id(tool.tool_id)
    assert retrieved_tool is None


def test_task_execution_repository(temp_db):
    """测试任务执行仓库"""
    # 先创建一个工具
    tool_repo = ToolRepository(temp_db)
    tool = Tool(tool_name="测试工具", parameters=[], steps=[])
    tool_repo.create(tool)

    # 创建执行记录
    execution_repo = TaskExecutionRepository(temp_db)
    execution = TaskExecution(
        tool_id=tool.tool_id,
        status="success",
        parameters={"keyword": "test"},
        result={"price": "$100"},
    )

    created_execution = execution_repo.create(execution)
    assert created_execution.execution_id == execution.execution_id

    # 获取执行记录
    retrieved_execution = execution_repo.get_by_id(execution.execution_id)
    assert retrieved_execution is not None
    assert retrieved_execution.status == "success"


def test_conversation_repository(temp_db):
    """测试对话仓库"""
    repo = ConversationRepository(temp_db)

    conversation = Conversation(
        user_message="帮我查价格",
        assistant_response="好的，正在查询",
        parameters_extracted={"keyword": "键盘"},
    )

    created_conv = repo.create(conversation)
    assert created_conv.conversation_id == conversation.conversation_id

    # 获取对话记录
    retrieved_conv = repo.get_by_id(conversation.conversation_id)
    assert retrieved_conv is not None
    assert retrieved_conv.user_message == "帮我查价格"

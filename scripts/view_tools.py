#!/usr/bin/env python
"""
查看已保存的工具

显示数据库中所有工具，或显示特定工具的详细信息
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.repositories import ToolRepository
from src.data.database import DatabaseManager
from src.utils.logger import setup_logger


def list_tools():
    """列出所有工具"""
    repo = ToolRepository()
    tools = repo.get_all()

    if not tools:
        print("\n数据库中还没有工具")
        return

    print("\n" + "=" * 80)
    print(f"数据库中共有 {len(tools)} 个工具")
    print("=" * 80)

    for idx, tool in enumerate(tools, 1):
        print(f"\n{idx}. {tool.tool_name}")
        print(f"   描述: {tool.description}")
        print(f"   参数: {len(tool.parameters)} 个")
        print(f"   步骤: {len(tool.steps)} 个")
        print(f"   创建时间: {tool.created_at}")


def view_tool_detail(tool_id: str):
    """查看工具详情"""
    repo = ToolRepository()
    tool = repo.get_by_id(tool_id)

    if not tool:
        print(f"\n未找到工具: {tool_id}")
        return

    print("\n" + "=" * 80)
    print(f"工具: {tool.tool_name}")
    print("=" * 80)

    print(f"\nID: {tool_id}")
    print(f"描述: {tool.description}")
    print(f"创建时间: {tool.created_at}")
    print(f"更新时间: {tool.updated_at}")

    print(f"\n参数定义 ({len(tool.parameters)} 个):")
    if tool.parameters:
        for param in tool.parameters:
            print(f"\n  - {param.get('display_name', param.get('name'))}")
            print(f"    类型: {param.get('type')}")
            print(f"    必填: {param.get('required')}")
            if param.get("description"):
                print(f"    说明: {param.get('description')}")
            if param.get("default_value"):
                print(f"    默认值: {param.get('default_value')}")
    else:
        print("  (无参数)")

    print(f"\n执行步骤 ({len(tool.steps)} 个):")
    for step in tool.steps:
        print(f"\n  步骤 {step.get('step_number')}: {step.get('step_name')}")
        print(f"    类型: {step.get('action_type')}")
        if step.get("description"):
            print(f"    描述: {step.get('description')}")

        if step.get("parameters"):
            print(f"    参数:")
            for key, value in step["parameters"].items():
                if isinstance(value, str) and len(value) > 50:
                    value = value[:50] + "..."
                print(f"      {key}: {value}")

        if step.get("locator_info"):
            locator = step["locator_info"]
            locator_value = locator.get("value", "")
            if len(locator_value) > 50:
                locator_value = locator_value[:50] + "..."
            print(f"    定位: {locator.get('type')} = {locator_value}")

        if step.get("error_handling"):
            error_handling = step["error_handling"]
            print(f"    错误处理: 重试 {error_handling.get('retry_times')} 次")

    if tool.steps and tool.steps[-1].get("expected_output"):
        output = tool.steps[-1]["expected_output"]
        print(f"\n期望输出:")
        print(f"  类型: {output.get('type')}")
        print(f"  说明: {output.get('description')}")

    print("\n" + "=" * 80)


def main():
    """主函数"""
    logger = setup_logger()

    # 初始化数据库
    db_manager = DatabaseManager()
    db_manager.initialize()

    if len(sys.argv) < 2:
        # 没有参数，列出所有工具
        list_tools()
    else:
        # 有参数，查看特定工具详情
        tool_id = sys.argv[1]
        view_tool_detail(tool_id)


if __name__ == "__main__":
    main()

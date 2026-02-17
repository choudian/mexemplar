"""
集成测试运行脚本

提供便捷的测试运行命令
"""

import subprocess
import sys
import argparse
from pathlib import Path


def run_command(cmd: list, description: str):
    """运行命令并显示输出"""
    print(f"\n{'='*60}")
    print(f"运行: {description}")
    print(f"命令: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        print(f"\n❌ {description} 失败 (退出码: {result.returncode})")
        return False

    print(f"\n✅ {description} 成功")
    return True


def main():
    parser = argparse.ArgumentParser(description="Intent 确认集成测试运行器")
    parser.add_argument(
        "--scenario",
        type=str,
        choices=["1", "2", "3", "all"],
        default="all",
        help="选择测试场景 (1: 简单确认, 2: 多轮对话, 3: 取消确认, all: 所有场景)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="显示详细输出"
    )
    parser.add_argument(
        "--coverage", "-c", action="store_true", help="生成测试覆盖率报告"
    )
    parser.add_argument(
        "--parallel", "-p", action="store_true", help="并行运行测试"
    )

    args = parser.parse_args()

    # 基础命令
    base_cmd = ["uv", "run", "pytest", "tests/integration/"]

    # 添加选项
    if args.verbose:
        base_cmd.append("-v")

    if args.parallel:
        base_cmd.extend(["-n", "auto"])

    if args.coverage:
        base_cmd.extend([
            "--cov=src/business/intent",
            "--cov=src/communication",
            "--cov-report=html",
            "--cov-report=term"
        ])

    # 根据场景选择测试
    scenario_tests = {
        "1": "tests/integration/test_intent_confirmation_integration.py::TestScenario1_SimpleConfirmation",
        "2": "tests/integration/test_intent_confirmation_integration.py::TestScenario2_MultiTurnRefinement",
        "3": "tests/integration/test_intent_confirmation_integration.py::TestScenario3_Cancellation",
    }

    if args.scenario == "all":
        # 运行所有集成测试
        test_cmd = base_cmd
        description = "所有集成测试"
    else:
        # 运行特定场景
        test_cmd = base_cmd + [scenario_tests[args.scenario]]
        description = f"场景 {args.scenario} 测试"

    # 运行测试
    success = run_command(test_cmd, description)

    # 如果生成了覆盖率报告，显示位置
    if args.coverage and success:
        print(f"\n📊 覆盖率报告已生成: {Path.cwd() / 'htmlcov' / 'index.html'}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

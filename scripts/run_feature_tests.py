"""
功能测试运行脚本

运行所有核心功能的测试并生成报告
"""

import subprocess
import sys
from pathlib import Path


def run_test(test_path: str, description: str) -> dict:
    """运行测试并返回结果"""
    print(f"\n{'='*60}")
    print(f"🧪 测试: {description}")
    print(f"{'='*60}")

    result = subprocess.run(
        ["uv", "run", "pytest", test_path, "-v", "--tb=short"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    # 解析结果
    lines = result.stdout.split('\n')
    summary = {}
    for line in lines:
        if 'passed' in line and 'failed' in line:
            parts = line.split()
            for i, part in enumerate(parts):
                if part.isdigit() and parts[i+1] == 'passed':
                    summary['passed'] = int(part)
                elif part.isdigit() and parts[i+1] == 'failed':
                    summary['failed'] = int(part)

    return {
        'description': description,
        'success': result.returncode == 0,
        'summary': summary,
        'output': result.stdout,
    }


def main():
    """主函数"""
    import sys
    import io

    # 设置标准输出编码为 UTF-8
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    print("\n" + "="*60)
    print("Exemplar Core Feature Tests")
    print("="*60)

    # 定义测试套件
    test_suites = [
        ("tests/test_tool_execution.py", "工具执行功能（任务 #14）"),
        ("tests/unit/communication/", "WebSocket 通信（任务 #11）"),
        ("tests/unit/business/", "业务逻辑模块"),
        ("tests/unit/execution/", "执行引擎"),
    ]

    results = []

    # 运行所有测试
    for test_path, description in test_suites:
        try:
            result = run_test(test_path, description)
            results.append(result)
        except Exception as e:
            print(f"❌ 测试运行失败: {e}")
            results.append({
                'description': description,
                'success': False,
                'error': str(e),
            })

    # 打印总结
    print("\n" + "="*60)
    print("📊 测试结果总结")
    print("="*60)

    total_passed = 0
    total_failed = 0

    for result in results:
        status = "✅ 通过" if result['success'] else "❌ 失败"
        print(f"\n{status} - {result['description']}")

        if 'summary' in result:
            passed = result['summary'].get('passed', 0)
            failed = result['summary'].get('failed', 0)
            print(f"   通过: {passed}, 失败: {failed}")
            total_passed += passed
            total_failed += failed
        elif 'error' in result:
            print(f"   错误: {result['error']}")

    print("\n" + "="*60)
    print(f"总计: 通过 {total_passed} | 失败 {total_failed}")
    print("="*60)

    # 返回退出码
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

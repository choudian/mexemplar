#!/usr/bin/env python
"""
持久化用户数据示例

演示如何保留登录状态，避免每次录制都重新登录
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))

from src.recording.recorder import Recorder
from src.utils.config import RecordingConfig


def example_1_default_behavior():
    """
    示例 1: 默认行为（临时用户数据）

    每次录制都是全新的浏览器环境，需要重新登录
    """
    print("=" * 60)
    print("示例 1: 默认行为 - 临时用户数据")
    print("=" * 60)

    # 使用默认配置
    recorder = Recorder(recording_mode='browser')

    print("\n特点:")
    print("  - 每次录制都创建新的临时用户数据目录")
    print("  - 需要每次重新登录")
    print("  - 录制之间完全隔离")

    print("\n启动录制...")
    recorder.start_recording()
    input("请在浏览器中操作（首次需要登录），完成后按 Enter...")
    recorder.stop_recording()
    recorder.close()

    print("\n下次录制仍然需要重新登录 ❌")


def example_2_persistent_user_data():
    """
    示例 2: 启用持久化用户数据（推荐）

    保留登录状态，只需登录一次
    """
    print("\n" + "=" * 60)
    print("示例 2: 启用持久化用户数据")
    print("=" * 60)

    # 创建配置，启用持久化
    config = RecordingConfig(
        persistent_user_data=True  # 关键配置
    )

    recorder = Recorder(
        recording_mode='browser',
        config=config  # 传递配置
    )

    print("\n特点:")
    print("  - 使用固定的用户数据目录")
    print("  - 保留登录状态、cookies、localStorage")
    print("  - 只需登录一次，之后都可以复用 ✅")

    print("\n首次使用:")
    print("  1. 启动录制")
    print("  2. 登录您的网站")
    print("  3. 停止录制")
    print("  4. 之后所有录制都会保留登录状态！")

    print("\n启动录制...")
    recorder.start_recording()
    input("请在浏览器中操作（首次需要登录），完成后按 Enter...")
    recorder.stop_recording()
    recorder.close()

    print("\n下次录制无需重新登录 ✅")


def example_3_custom_user_data_dir():
    """
    示例 3: 自定义用户数据目录

    使用指定的目录存储用户数据
    """
    print("\n" + "=" * 60)
    print("示例 3: 自定义用户数据目录")
    print("=" * 60)

    # 创建配置，指定自定义路径
    config = RecordingConfig(
        persistent_user_data=True,
        user_data_dir=str(Path.home() / "exemplar_browser_profile")
    )

    recorder = Recorder(
        recording_mode='browser',
        config=config
    )

    print(f"\n使用自定义目录: {Path.home() / 'exemplar_browser_profile'}")

    print("\n优点:")
    print("  - 可以备份和恢复浏览器配置")
    print("  - 可以在多个项目间共享同一个配置")
    print("  - 便于管理（知道数据存在哪里）")

    print("\n启动录制...")
    recorder.start_recording()
    input("请在浏览器中操作，完成后按 Enter...")
    recorder.stop_recording()
    recorder.close()


def example_4_first_time_setup():
    """
    示例 4: 首次设置指南

    演示如何首次设置并登录
    """
    print("\n" + "=" * 60)
    print("示例 4: 首次设置指南")
    print("=" * 60)

    print("\n步骤 1: 启用持久化用户数据")
    print("```python")
    print("from src.utils.config import RecordingConfig")
    print("")
    print("config = RecordingConfig(")
    print("    persistent_user_data=True  # 启用持久化")
    print(")")
    print("```")

    print("\n步骤 2: 首次录制并登录")
    print("```python")
    print("from src.recording.recorder import Recorder")
    print("")
    print("recorder = Recorder(")
    print("    recording_mode='browser',")
    print("    config=config")
    print(")")
    print("")
    print("recorder.start_recording()")
    print("# 在浏览器中登录您的网站/应用")
    print("recorder.stop_recording()")
    print("```")

    print("\n步骤 3: 之后所有录制都会保留登录状态！")
    print("")
    print("✅ 登录一次，永久有效（除非 token 过期）")

    # 实际执行一次
    print("\n" + "-" * 60)
    print("现在执行首次设置...")
    print("-" * 60)

    config = RecordingConfig(persistent_user_data=True)
    recorder = Recorder(recording_mode='browser', config=config)

    recorder.start_recording()
    print("\n请在浏览器中登录您常用的网站（如 GitHub、Google 等）")
    input("登录完成后按 Enter...")
    recorder.stop_recording()
    recorder.close()

    print("\n✅ 设置完成！下次录制无需重新登录")


def main():
    """主函数"""
    print("=" * 60)
    print("持久化用户数据示例")
    print("=" * 60)
    print("\n解决痛点: 每次录制都要重新登录")
    print("解决方案: 启用持久化用户数据，保留登录状态")
    print("=" * 60)

    print("\n请选择示例:")
    print("  1. 默认行为（临时，每次重新登录）")
    print("  2. 启用持久化（推荐，只需登录一次）")
    print("  3. 自定义目录（高级用户）")
    print("  4. 首次设置指南")

    choice = input("\n请选择 (1-4): ").strip()

    if choice == '1':
        example_1_default_behavior()
    elif choice == '2':
        example_2_persistent_user_data()
    elif choice == '3':
        example_3_custom_user_data_dir()
    elif choice == '4':
        example_4_first_time_setup()
    else:
        print("无效选择，运行示例 2（推荐）")
        example_2_persistent_user_data()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户中断")
    except Exception as e:
        print(f"\n错误: {e}")
        import traceback
        traceback.print_exc()

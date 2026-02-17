#!/usr/bin/env python
"""
快速开始 - 事件驱动的自动工作流处理

这是最简单的入门示例，展示如何启用自动工作流处理
"""
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

from src.recording.recorder import Recorder
from src.business.ai.workflow_orchestrator import WorkflowOrchestrator


def main():
    print("="*60)
    print("事件驱动 - 快速开始")
    print("="*60)
    print()
    print("本示例展示如何实现自动工作流处理")
    print("当录制完成时，工作流会自动生成")
    print()

    # 步骤1: 创建录制器
    print("步骤1: 创建录制器")
    recorder = Recorder(recording_mode='desktop')
    print("✅ 录制器已创建")
    print()

    # 步骤2: 创建工作流编排器（关键：启用 auto_process）
    print("步骤2: 创建工作流编排器")
    print("   提示: auto_process=True 是启用自动处理的关键")
    orchestrator = WorkflowOrchestrator(
        auto_process=True,    # 关键配置：自动监听并处理
        enable_vision=False,  # 关闭视觉分析（加快速度）
        auto_save=False       # 不保存到数据库（演示用）
    )
    print("✅ 工作流编排器已创建并开始监听")
    print()

    # 步骤3: 开始录制
    print("步骤3: 开始录制")
    recording_id = recorder.start_recording()
    print(f"✅ 录制已开始 (ID: {recording_id})")
    print()
    print("提示: 现在可以执行一些操作（点击、输入等）")
    print("      等待5秒模拟操作...")
    print()

    import time
    time.sleep(5)

    # 步骤4: 停止录制（自动触发工作流处理！）
    print("步骤4: 停止录制")
    print("   注意: 停止录制后会自动触发工作流处理")
    print()
    session = recorder.stop_recording()
    print(f"✅ 录制已停止")
    print(f"   会话ID: {session.recording_id}")
    print(f"   操作数: {len(session.actions)}")
    print()
    print("="*60)
    print("关键点:")
    print("="*60)
    print("1. WorkflowOrchestrator(auto_process=True) 启用自动处理")
    print("2. stop_recording() 后自动触发工作流生成")
    print("3. 无需手动调用 orchestrator.process_recording()")
    print("4. Recorder 和 Orchestrator 完全解耦")
    print("="*60)
    print()

    # 清理资源
    print("清理资源...")
    recorder.close()
    orchestrator.close()
    print("✅ 清理完成")
    print()
    print("完成！查看上方日志了解工作流处理过程。")


if __name__ == '__main__':
    main()

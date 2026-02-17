#!/usr/bin/env python
"""
Exemplar 命令行工具

提供录制、数据压缩、分析功能的完整流程
"""
import sys
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# 添加项目根目录和 src 目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'src'))  # 添加 src 目录以便相对导入工作

from src.recording.recorder import Recorder, Action, RecordingSession
from src.recording.browser_recorder import BrowserRecorder
from src.recording.data_collector import DataCollector
from src.business.ai.data_preprocessor import DataPreprocessor, CompressionLevel
from src.utils.logger import setup_logger


class ExemplarCLI:
    """Exemplar 命令行工具"""

    def __init__(self):
        """初始化CLI"""
        self.logger = setup_logger()
        self.current_session: Optional[RecordingSession] = None
        self.recorder: Optional[Recorder] = None
        self.storage_path = project_root / 'data' / 'recordings'
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def show_main_menu(self):
        """显示主菜单"""
        print("\n" + "=" * 60)
        print("Exemplar - 智能办公助理")
        print("=" * 60)
        print("\n请选择操作:")
        print("  1. 浏览器录制")
        print("  2. 桌面录制")
        print("  3. 查看最近的录制数据")
        print("  4. 测试数据压缩功能")
        print("  0. 退出")
        print("-" * 60)

    def choose_recording_mode(self):
        """选择录制模式"""
        print("\n" + "=" * 60)
        print("选择录制模式")
        print("=" * 60)
        print("\n录制模式说明:")
        print("  1. 浏览器录制 - 录制浏览器中的操作（推荐）")
        print("     - 捕获点击、输入、滚动等操作")
        print("     - 自动获取 DOM 元素信息")
        print("     - 记录网络请求")
        print("     - 需要安装 Chrome 扩展")
        print()
        print("  2. 桌面录制 - 录制桌面应用程序操作")
        print("     - 捕获鼠标、键盘事件")
        print("     - 自动截屏")
        print("     - 记录窗口信息")
        print("     - 适用于任何桌面应用")
        print("-" * 60)

        while True:
            choice = input("\n请选择录制模式 (1/2/0返回): ").strip()
            if choice == '1':
                return 'browser'
            elif choice == '2':
                return 'desktop'
            elif choice == '0':
                return None
            else:
                print("[错误] 无效选择，请重新输入")

    def browser_recording_workflow(self):
        """浏览器录制流程"""
        print("\n" + "=" * 60)
        print("浏览器录制")
        print("=" * 60)

        # 询问起始URL
        print("\n请输入要访问的网址（留空使用默认搜索引擎）")
        start_url = input("URL: ").strip()
        if not start_url:
            start_url = 'https://www.baidu.com'

        print(f"\n将要打开: {start_url}")
        print("提示：浏览器将自动打开并开始录制")

        # 创建浏览器录制器
        try:
            recorder = BrowserRecorder(
                config=None,
                storage_path=self.storage_path
            )
        except Exception as e:
            print(f"[错误] 初始化浏览器录制器失败: {e}")
            return False

        # 启动录制
        print("\n[启动] 正在启动浏览器...")
        try:
            success = recorder.start_recording(start_url=start_url)
            if not success:
                print("[失败] 浏览器启动失败")
                return False
            print("[成功] 浏览器已启动，开始录制")
        except Exception as e:
            print(f"[错误] 启动录制失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        # 录制提示
        print("\n" + "=" * 60)
        print("录制中...")
        print("=" * 60)
        print("\n请在浏览器中执行你的操作：")
        print("  - 点击按钮、链接")
        print("  - 输入文本")
        print("  - 滚动页面")
        print("  - 导航到其他页面")
        print("\n完成操作后，返回此窗口按 Enter 键停止录制")
        print("-" * 60)

        # 等待用户按Enter停止
        try:
            input("\n按 Enter 键停止录制...")
        except (EOFError, KeyboardInterrupt):
            print("\n检测到中断信号")

        # 停止录制
        print("\n[停止] 正在停止录制...")
        recording_id = None
        try:
            # 获取 recording_id（BrowserRecorder 会保存为 exemplar_recording_{id}.json）
            if hasattr(recorder, '_recording_id'):
                recording_id = recorder._recording_id
            recorder.stop_recording()
            print("[成功] 录制已停止")
        except Exception as e:
            print(f"[警告] 停止录制时出错: {e}")

        # 读取保存的录制数据
        # 尝试多个可能的文件位置
        recording_file = None

        if recording_id:
            # 尝试标准路径
            possible_paths = [
                self.storage_path / f"exemplar_recording_{recording_id}.json",
                self.storage_path / f"{recording_id}.json",
            ]
            for path in possible_paths:
                if path.exists():
                    recording_file = path
                    break

        # 如果还没找到，搜索所有可能的 JSON 文件
        if not recording_file:
            print("\n[信息] 搜索录制数据文件...")
            # 搜索所有可能的 JSON 文件
            all_json_files = []
            # 搜索当前目录
            all_json_files.extend(self.storage_path.glob("*.json"))
            # 搜索 data 目录下所有 JSON 文件
            data_root = self.storage_path.parent
            all_json_files.extend(data_root.rglob("*.json"))

            # 过滤出可能的录制文件（排除 playwright 缓存等）
            candidate_files = [
                f for f in all_json_files
                if 'exemplar_recording' in f.name.lower() or
                   'recording' in f.name.lower() or
                   'playwright' not in str(f)  # 排除 playwright 缓存
            ]

            if candidate_files:
                # 按修改时间排序，获取最新的
                candidate_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                recording_file = candidate_files[0]
                print(f"[信息] 找到录制文件: {recording_file}")

        if not recording_file or not recording_file.exists():
            print(f"\n[错误] 未找到录制数据文件")
            print(f"[提示] recording_id = {recording_id}")
            print(f"[提示] 搜索路径: {self.storage_path}")
            # 列出 storage_path 中的所有文件
            if self.storage_path.exists():
                files = list(self.storage_path.glob("*"))
                if files:
                    print(f"[提示] storage_path 中的文件:")
                    for f in files[:10]:
                        print(f"  - {f.name}")
            return False

        # 检查文件是否存在
        if not recording_file.exists():
            print(f"\n[错误] 录制文件不存在: {recording_file}")
            return False

        # 加载录制数据
        try:
            with open(recording_file, 'r', encoding='utf-8') as f:
                recording_data = json.load(f)
            session = RecordingSession.from_dict(recording_data)
        except Exception as e:
            print(f"\n[错误] 加载录制文件失败: {e}")
            return False

        if not session.actions:
            print("\n[警告] 未录制到任何操作")
            return False

        print(f"\n[统计] 录制统计:")
        print(f"  录制ID: {session.recording_id}")
        print(f"  操作数量: {len(session.actions)}")
        if session.start_time and session.end_time:
            print(f"  录制时长: {session.end_time - session.start_time:.1f} 秒")
        print(f"  数据文件: {recording_file}")

        # 询问是否查看压缩后的数据
        print("\n是否查看压缩后的数据？(y/n)")
        choice = input("选择: ").strip().lower()
        if choice == 'y':
            self.show_compressed_data(session)

        return True

    def desktop_recording_workflow(self):
        """桌面录制流程"""
        print("\n" + "=" * 60)
        print("桌面录制")
        print("=" * 60)

        print("\n提示：")
        print("  - 将录制整个桌面的操作")
        print("  - 请确保你要操作的应用程序已打开")
        print("  - 鼠标移动和键盘输入都会被记录")
        print("  - 会自动截屏")

        input("\n准备好后按 Enter 键开始录制...")

        # 创建桌面录制器
        try:
            recorder = Recorder(
                storage_path=self.storage_path,
                recording_mode='desktop'
            )
        except Exception as e:
            print(f"[错误] 初始化桌面录制器失败: {e}")
            return False

        # 启动录制
        print("\n[启动] 正在启动桌面录制...")
        try:
            recorder.start_recording()
            print("[成功] 开始录制（后台运行）")
        except Exception as e:
            print(f"[错误] 启动录制失败: {e}")
            import traceback
            traceback.print_exc()
            return False

        # 录制提示
        print("\n" + "=" * 60)
        print("录制中...")
        print("=" * 60)
        print("\n请在桌面应用程序中执行你的操作：")
        print("  - 打开应用程序")
        print("  - 点击按钮、菜单")
        print("  - 输入文本")
        print("  - 切换窗口")
        print("\n完成操作后，返回此窗口按 Enter 键停止录制")
        print("-" * 60)

        # 等待用户按Enter停止
        try:
            input("\n按 Enter 键停止录制...")
        except (EOFError, KeyboardInterrupt):
            print("\n检测到中断信号")

        # 停止录制
        print("\n[停止] 正在停止录制...")
        try:
            session = recorder.stop_recording()
            print("[成功] 录制已停止")
        except Exception as e:
            print(f"[警告] 停止录制时出错: {e}")
            return False

        if not session or not session.actions:
            print("\n[警告] 未录制到任何操作")
            return False

        print(f"\n[统计] 录制统计:")
        print(f"  录制ID: {session.recording_id}")
        print(f"  操作数量: {len(session.actions)}")
        print(f"  录制时长: {session.end_time - session.start_time:.1f} 秒")

        # 保存录制数据
        recording_file = self.storage_path / f"{session.recording_id}.json"
        with open(recording_file, 'w', encoding='utf-8') as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
        print(f"  数据已保存: {recording_file}")

        # 询问是否查看压缩后的数据
        print("\n是否查看压缩后的数据？(y/n)")
        choice = input("选择: ").strip().lower()
        if choice == 'y':
            self.show_compressed_data(session)

        return True

    def show_compressed_data(self, session: RecordingSession):
        """显示压缩后的数据"""
        print("\n" + "=" * 60)
        print("数据压缩分析")
        print("=" * 60)

        # 选择压缩级别
        print("\n请选择压缩级别:")
        print("  1. NONE (无压缩) - 保留所有原始数据")
        print("  2. CONSERVATIVE (保守) - 压缩率 60-70%")
        print("  3. MODERATE (适中) - 压缩率 70-80% [推荐]")
        print("  4. AGGRESSIVE (激进) - 压缩率 80-90%")
        print("  5. 对比所有级别")

        while True:
            choice = input("\n请选择 (1-5): ").strip()
            if choice == '1':
                self._show_compression_result(session, CompressionLevel.NONE)
                break
            elif choice == '2':
                self._show_compression_result(session, CompressionLevel.CONSERVATIVE)
                break
            elif choice == '3':
                self._show_compression_result(session, CompressionLevel.MODERATE)
                break
            elif choice == '4':
                self._show_compression_result(session, CompressionLevel.AGGRESSIVE)
                break
            elif choice == '5':
                self._show_all_compression_levels(session)
                break
            else:
                print("[错误] 无效选择，请重新输入")

    def _show_compression_result(self, session: RecordingSession, level: CompressionLevel):
        """显示单个压缩级别的结果"""
        preprocessor = DataPreprocessor()
        result = preprocessor.preprocess(session.actions, compression_level=level)

        # 显示压缩统计
        print("\n" + "-" * 60)
        stats = result.metadata.get('compression_stats', {})
        if stats:
            print(f"压缩级别: {stats.get('compression_level', 'N/A')}")
            print(f"原始操作数: {stats.get('original_count', 'N/A')}")
            print(f"压缩后操作数: {stats.get('compressed_count', 'N/A')}")
            print(f"操作压缩率: {stats.get('compression_ratio', 'N/A')}")
            print(f"原始截图数: {stats.get('screenshots_original', 'N/A')}")
            print(f"优化后截图数: {stats.get('screenshots_optimized', 'N/A')}")
            print(f"关键操作数: {len(result.key_actions)}")
        else:
            print("压缩级别: NONE (无压缩)")
            print(f"操作数: {len(result.actions)}")
            print(f"截图数: {len(result.screenshots)}")

        # 显示操作类型统计
        print("\n操作类型分布:")
        action_types = {}
        for paction in result.actions:
            action = paction.original_action
            action_type = action.action_type
            action_types[action_type] = action_types.get(action_type, 0) + 1

        for action_type, count in sorted(action_types.items(), key=lambda x: -x[1]):
            print(f"  - {action_type}: {count} 次")

        # 显示前10个操作
        print("\n前10个操作:")
        for idx, paction in enumerate(result.actions[:10], 1):
            action = paction.original_action
            marker = "[关键]" if paction.is_key_action else "[系统]"
            desc = f"{marker} {idx}. {action.action_type}"

            if action.url:
                desc += f" | URL: {action.url[:50]}"

            if action.parameters.get('value'):
                value = str(action.parameters['value'])
                if len(value) > 20:
                    value = value[:20] + "..."
                desc += f" | 值: {value}"

            if action.dom_element:
                elem = action.dom_element
                if elem.get('tag_name'):
                    desc += f" | <{elem['tag_name']}>"
                if elem.get('id'):
                    desc += f" #{elem['id']}"

            print(desc)

        if len(result.actions) > 10:
            print(f"  ... 还有 {len(result.actions) - 10} 个操作")

        # 询问是否保存压缩后的数据
        print("\n是否保存压缩后的数据？(y/n)")
        choice = input("选择: ").strip().lower()
        if choice == 'y':
            filename = f"compressed_{level.name}_{session.recording_id}.json"
            filepath = self.storage_path / filename

            # 保存压缩后的数据
            compressed_data = {
                'recording_id': session.recording_id,
                'compression_level': level.name,
                'original_count': len(session.actions),
                'compressed_count': len(result.actions),
                'actions': [paction.original_action.to_dict() for paction in result.actions],
                'key_actions': [ka.original_action.to_dict() for ka in result.key_actions],
                'screenshots': list(result.screenshots),
                'metadata': result.metadata
            }

            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(compressed_data, f, ensure_ascii=False, indent=2)
            print(f"[成功] 数据已保存: {filepath}")

    def _show_all_compression_levels(self, session: RecordingSession):
        """对比所有压缩级别"""
        preprocessor = DataPreprocessor()
        levels = [
            (CompressionLevel.NONE, "NONE (无压缩)"),
            (CompressionLevel.CONSERVATIVE, "CONSERVATIVE (保守)"),
            (CompressionLevel.MODERATE, "MODERATE (适中)"),
            (CompressionLevel.AGGRESSIVE, "AGGRESSIVE (激进)"),
        ]

        print("\n" + "-" * 60)
        print("所有压缩级别对比:")
        print("-" * 60)
        print(f"{'级别':<20} {'原始操作':<10} {'压缩后':<10} {'压缩率':<10} {'截图数':<10}")
        print("-" * 60)

        results = {}
        for level, level_name in levels:
            result = preprocessor.preprocess(session.actions, compression_level=level)
            results[level] = result

            stats = result.metadata.get('compression_stats', {})
            if stats:
                original = stats.get('original_count', len(session.actions))
                compressed = stats.get('compressed_count', len(result.actions))
                ratio = stats.get('compression_ratio', '0%')
                screenshots = stats.get('screenshots_optimized', len(result.screenshots))
            else:
                original = len(session.actions)
                compressed = len(result.actions)
                ratio = "0%"
                screenshots = len(result.screenshots)

            print(f"{level_name:<20} {original:<10} {compressed:<10} {ratio:<10} {screenshots:<10}")

        # 询问是否查看详细信息
        print("\n是否查看某个级别的详细信息？(1-4, 0返回)")
        choice = input("选择: ").strip()
        if choice in ['1', '2', '3', '4']:
            level = levels[int(choice) - 1][0]
            self._show_compression_result(session, level)

    def view_recent_recording(self):
        """查看最近的录制数据"""
        print("\n" + "=" * 60)
        print("查看最近的录制数据")
        print("=" * 60)

        # 查找最近的录制文件
        json_files = list(self.storage_path.glob("*.json"))
        if not json_files:
            print("\n[错误] 未找到录制数据")
            print("   请先进行录制操作")
            return

        # 按修改时间排序
        json_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        # 显示最近的5个文件
        print("\n最近的录制文件:")
        for idx, filepath in enumerate(json_files[:5], 1):
            # 读取基本信息
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                recording_id = data.get('recording_id', filepath.stem)
                action_count = len(data.get('actions', []))
                mtime = datetime.fromtimestamp(filepath.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                print(f"  {idx}. {filepath.name}")
                print(f"     录制ID: {recording_id}")
                print(f"     操作数: {action_count}")
                print(f"     保存时间: {mtime}")
            except Exception as e:
                print(f"  {idx}. {filepath.name} (读取失败: {e})")

        # 选择要查看的文件
        print("\n请选择要查看的文件 (1-5, 0返回)")
        choice = input("选择: ").strip()
        if choice == '0' or not choice.isdigit():
            return

        idx = int(choice) - 1
        if idx < 0 or idx >= len(json_files):
            print("[错误] 无效选择")
            return

        filepath = json_files[idx]

        # 加载并显示录制数据
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            session = RecordingSession.from_dict(data)
            self.show_compressed_data(session)

        except Exception as e:
            print(f"[错误] 加载文件失败: {e}")
            import traceback
            traceback.print_exc()

    def test_compression(self):
        """测试数据压缩功能"""
        print("\n" + "=" * 60)
        print("测试数据压缩功能")
        print("=" * 60)
        print("\n将运行测试脚本，展示各级别的压缩效果")

        input("\n按 Enter 键开始测试...")

        # 运行测试脚本
        import subprocess
        test_script = project_root / 'scripts' / 'dev' / 'test_data_compression.py'
        result = subprocess.run(
            [sys.executable, str(test_script)],
            cwd=str(project_root)
        )

        if result.returncode == 0:
            print("\n[成功] 测试完成")
        else:
            print("\n[失败] 测试失败")

    def run(self):
        """运行CLI主循环"""
        while True:
            self.show_main_menu()

            try:
                choice = input("\n请选择操作 (0-4): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n\n再见！")
                break

            if choice == '0':
                print("\n再见！")
                break
            elif choice == '1':
                mode = self.choose_recording_mode()
                if mode == 'browser':
                    self.browser_recording_workflow()
            elif choice == '2':
                mode = self.choose_recording_mode()
                if mode == 'desktop':
                    self.desktop_recording_workflow()
            elif choice == '3':
                self.view_recent_recording()
            elif choice == '4':
                self.test_compression()
            else:
                print("\n[错误] 无效选择，请重新输入")

            # 询问是否继续
            print("\n" + "-" * 60)
            try:
                continue_choice = input("是否继续？(y/n): ").strip().lower()
                if continue_choice != 'y':
                    print("\n再见！")
                    break
            except (EOFError, KeyboardInterrupt):
                print("\n\n再见！")
                break


def main():
    """主函数"""
    cli = ExemplarCLI()
    cli.run()


if __name__ == '__main__':
    main()

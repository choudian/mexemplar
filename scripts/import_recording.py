#!/usr/bin/env python
"""
导入浏览器插件录制的JSON文件

用法:
    python scripts/import_recording.py <json_file_path>
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import logging
from recording.recorder_import import (
    import_recording_from_json, 
    save_imported_recording,
    validate_imported_recording
)
from recording.recorder import Recorder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/import_recording.py <json_file_path>")
        print("\n示例:")
        print("  python scripts/import_recording.py exemplar_recording_abc123.json")
        sys.exit(1)
    
    json_file = Path(sys.argv[1])
    if not json_file.exists():
        print(f"错误: 文件不存在: {json_file}")
        sys.exit(1)
    
    try:
        # 导入录制数据
        print(f"正在导入录制数据: {json_file}")
        print("-" * 60)
        
        session = import_recording_from_json(json_file)
        
        # 验证数据
        is_valid, error_msg = validate_imported_recording(session)
        if not is_valid:
            print(f"\n[警告] 数据验证失败: {error_msg}")
            print("继续导入...")
        
        # 保存到标准位置
        recorder = Recorder()
        saved_path = save_imported_recording(session, recorder.storage_path)
        
        print("\n" + "=" * 60)
        print("[成功] 录制数据已导入并保存")
        print("=" * 60)
        print(f"Session ID: {session.recording_id}")
        print(f"录制模式: {session.recording_mode}")
        print(f"操作数量: {len(session.actions)}")
        if session.start_time and session.end_time:
            duration = session.end_time - session.start_time
            print(f"录制时长: {duration:.2f} 秒")
        print(f"保存位置: {saved_path}")
        
        # 显示操作统计
        action_types = {}
        for action in session.actions:
            action_type = action.action_type
            action_types[action_type] = action_types.get(action_type, 0) + 1
        
        print("\n操作类型统计:")
        for action_type, count in sorted(action_types.items()):
            print(f"  {action_type}: {count}")
        
    except FileNotFoundError as e:
        print(f"\n[错误] {e}")
        sys.exit(1)
    except ValueError as e:
        print(f"\n[错误] JSON格式错误: {e}")
        sys.exit(1)
    except KeyError as e:
        print(f"\n[错误] JSON缺少必需的字段: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] 导入失败: {e}")
        logger.exception("导入失败")
        sys.exit(1)


if __name__ == '__main__':
    main()


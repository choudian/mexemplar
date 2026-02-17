#!/usr/bin/env python
"""
查看录制数据的脚本

用法:
    python scripts/view_recording.py <recording_file_path>
"""
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

def format_timestamp(timestamp: float, start_time: float) -> str:
    """格式化时间戳为相对时间"""
    elapsed = timestamp - start_time
    return f"{elapsed:.2f}s"

def format_key(key: str) -> str:
    """格式化按键名称"""
    # 移除 "Key." 前缀，处理特殊按键
    if key.startswith("Key."):
        key = key[4:]
    # 处理特殊按键的显示
    key_map = {
        "enter": "Enter",
        "space": "Space",
        "backspace": "Backspace",
        "delete": "Delete",
        "tab": "Tab",
        "shift": "Shift",
        "ctrl": "Ctrl",
        "alt": "Alt",
        "esc": "Esc",
    }
    return key_map.get(key.lower(), key.title())

def analyze_recording(file_path: Path):
    """分析录制文件并显示操作序列"""
    print("="*80)
    print(f"Analyzing Recording: {file_path.name}")
    print("="*80)
    
    # 读取JSON文件
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    recording_id = data.get('recording_id', 'unknown')
    start_time = data.get('start_time', 0)
    end_time = data.get('end_time', 0)
    duration = end_time - start_time if end_time else 0
    events = data.get('events', [])
    
    print(f"\nRecording ID: {recording_id}")
    print(f"Duration: {duration:.2f} seconds")
    print(f"Total Events: {len(events)}")
    print("\n" + "-"*80)
    
    # 统计事件类型
    event_type_counts = {}
    for event in events:
        event_type = event.get('event_type', 'unknown')
        event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
    
    print("\nEvent Statistics:")
    for event_type, count in sorted(event_type_counts.items()):
        print(f"  {event_type}: {count}")
    
    print("\n" + "="*80)
    print("Operation Sequence (Key Actions Only)")
    print("="*80)
    print("\n(Mouse movements are filtered out for clarity)\n")
    
    # 显示关键操作（过滤掉大量的鼠标移动事件）
    key_actions = []
    last_mouse_pos = None
    
    for i, event in enumerate(events):
        event_type = event.get('event_type', '')
        event_data = event.get('data', {})
        timestamp = event.get('timestamp', 0)
        
        if event_type == 'window_change':
            window_title = event_data.get('window_title', 'Unknown')
            window_class = event_data.get('window_class', 'Unknown')
            key_actions.append({
                'time': format_timestamp(timestamp, start_time),
                'type': 'window_change',
                'description': f"Window changed: {window_title}"
            })
        
        elif event_type == 'keyboard':
            key_event_type = event_data.get('event_type', '')
            key = event_data.get('key', '')
            
            if key_event_type == 'press':
                formatted_key = format_key(key)
                key_actions.append({
                    'time': format_timestamp(timestamp, start_time),
                    'type': 'keyboard',
                    'description': f"Key pressed: {formatted_key}"
                })
        
        elif event_type == 'mouse':
            mouse_event_type = event_data.get('event_type', '')
            x = event_data.get('x')
            y = event_data.get('y')
            button = event_data.get('button')
            pressed = event_data.get('pressed')
            
            if mouse_event_type == 'click':
                button_name = button if button else 'Unknown'
                action = 'pressed' if pressed else 'released'
                key_actions.append({
                    'time': format_timestamp(timestamp, start_time),
                    'type': 'mouse_click',
                    'description': f"Mouse {action} at ({x}, {y}) - Button: {button_name}"
                })
                last_mouse_pos = (x, y)
            
            elif mouse_event_type == 'scroll':
                scroll_dx = event_data.get('scroll_dx', 0)
                scroll_dy = event_data.get('scroll_dy', 0)
                key_actions.append({
                    'time': format_timestamp(timestamp, start_time),
                    'type': 'mouse_scroll',
                    'description': f"Mouse scrolled at ({x}, {y}) - dx: {scroll_dx}, dy: {scroll_dy}"
                })
                last_mouse_pos = (x, y)
        
        elif event_type == 'screenshot':
            key_actions.append({
                'time': format_timestamp(timestamp, start_time),
                'type': 'screenshot',
                'description': "Screenshot captured"
            })
    
    # 显示关键操作序列
    if key_actions:
        print(f"\nFound {len(key_actions)} key actions:\n")
        for i, action in enumerate(key_actions, 1):
            action_type = action['type'].upper().replace('_', ' ')
            print(f"[{action['time']}] {action_type:15s} - {action['description']}")
    else:
        print("\nNo key actions found (only mouse movements)")
    
    print("\n" + "="*80)
    print("Analysis Complete")
    print("="*80)

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("Usage: python scripts/view_recording.py <recording_file_path>")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    
    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    
    try:
        analyze_recording(file_path)
    except Exception as e:
        print(f"Error analyzing recording: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()


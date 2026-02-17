#!/usr/bin/env python3
"""
诊断脚本：检查录制完成后 network_requests 表的数据

使用方法：
1. 关闭 PyCharm 或其他占用数据库的程序
2. 运行: uv run python debug_network_requests.py
"""

import sys
from pathlib import Path

def check_network_requests():
    """检查 network_requests 表的数据"""
    try:
        from src.data.duckdb_manager import DuckDBManager
        from datetime import datetime

        print("=== 网络请求保存诊断 ===\n")

        # 初始化数据库
        db_manager = DuckDBManager()
        db_manager.initialize()
        conn = db_manager.connect()

        # 1. 检查表是否存在
        tables = conn.execute("SHOW TABLES").fetchall()
        table_names = [row[0] for row in tables]
        print(f"[1] 数据库表: {', '.join(table_names)}")

        if "network_requests" not in table_names:
            print("  ❌ network_requests 表不存在！")
            return

        # 2. 检查表结构
        columns = conn.execute("DESCRIBE network_requests").fetchall()
        col_names = [col[0] for col in columns]
        has_rec_id = "recording_id" in col_names
        print(f"\n[2] network_requests 表有 recording_id: {has_rec_id}")

        # 3. 检查数据量
        total = conn.execute("SELECT COUNT(*) FROM network_requests").fetchone()[0]
        with_rec = conn.execute("SELECT COUNT(*) FROM network_requests WHERE recording_id IS NOT NULL").fetchone()[0]
        with_null_rec = conn.execute("SELECT COUNT(*) FROM network_requests WHERE recording_id IS NULL").fetchone()[0]

        print(f"\n[3] 数据统计:")
        print(f"  总记录数: {total}")
        print(f"  有 recording_id: {with_rec}")
        print(f"  recording_id 为 NULL: {with_null_rec}")

        # 4. 按录制会话分组
        print(f"\n[4] 按录制会话分组:")
        result = conn.execute("""
            SELECT
                recording_id,
                COUNT(*) as count,
                MIN(timestamp) as first_time,
                MAX(timestamp) as last_time
            FROM network_requests
            GROUP BY recording_id
            ORDER BY first_time DESC
        """).fetchall()

        if not result:
            print("  ⚠️ 没有任何网络请求记录")
        else:
            for row in result:
                rec_id = row[0][:20] + "..." if row[0] and len(row[0]) > 20 else (row[0] if row[0] else "NULL")
                print(f"  {rec_id}: {row[1]} 条请求")
                print(f"    时间范围: {row[2]} -> {row[3]}")

        # 5. 最近的记录
        print(f"\n[5] 最近的 5 条记录:")
        result = conn.execute("""
            SELECT
                request_id, action_id, recording_id, url, method, timestamp
            FROM network_requests
            ORDER BY timestamp DESC
            LIMIT 5
        """).fetchall()

        if not result:
            print("  ⚠️ 没有找到任何记录")
        else:
            for row in result:
                rec_id = row[2][:15] + "..." if row[2] and len(row[2]) > 15 else (row[2] if row[2] else "NULL")
                url = row[3][:50] + "..." if row[3] and len(row[3]) > 50 else row[3]
                print(f"  ID={row[0]}, action_id={row[1]}, rec_id={rec_id}")
                print(f"    {row[4]} {url}")
                print(f"    时间: {row[5]}")

        # 6. 检查录制会话
        print(f"\n[6] 录制会话统计:")
        sessions = conn.execute("""
            SELECT
                recording_id,
                status,
                start_time,
                end_time
            FROM recording_sessions
            ORDER BY start_time DESC
        """).fetchall()

        if not sessions:
            print("  ⚠️ 没有任何录制会话")
        else:
            print(f"  共 {len(sessions)} 个录制会话")
            for session in sessions:
                rec_id = session[0][:20] + "..."
                print(f"  {rec_id}: {session[1]}, {session[2]} -> {session[3]}")

        conn.close()
        db_manager.close()

        print("\n=== 诊断完成 ===")

    except Exception as e:
        print(f"\n❌ 诊断失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True

if __name__ == "__main__":
    success = check_network_requests()
    sys.exit(0 if success else 1)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库迁移脚本

用法:
    python scripts/migrate_database.py
"""

import sys
import io
from pathlib import Path

# 修复 Windows 控制台编码问题
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.data.database import DatabaseManager
from src.data.migrations import run_migrations


def main():
    """主函数"""
    print("=" * 60)
    print("开始数据库迁移")
    print("=" * 60)

    try:
        # 初始化数据库管理器
        db_manager = DatabaseManager()
        db_manager.initialize()

        # 运行迁移
        run_migrations(db_manager)

        print("=" * 60)
        print("✅ 数据库迁移成功完成")
        print("=" * 60)

    except Exception as e:
        print("=" * 60)
        print(f"❌ 数据库迁移失败: {e}")
        print("=" * 60)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()


#!/usr/bin/env python3
"""
运行 Alembic 迁移的便捷脚本

用法:
    # 迁移 DuckDB 数据库
    python run_migration.py --db duckdb

    # 迁移 SQLite 数据库
    python run_migration.py --db sqlite

    # 查看当前状态
    python run_migration.py --status
"""

import os
import sys
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="运行 Alembic 数据库迁移")
    parser.add_argument(
        "--db",
        choices=["sqlite", "duckdb"],
        default="sqlite",
        help="数据库类型 (默认: sqlite)"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="查看当前迁移状态"
    )
    parser.add_argument(
        "--downgrade",
        action="store_true",
        help="回滚迁移"
    )

    args = parser.parse_args()

    # 设置环境变量
    os.environ["ALEMBIC_DB_TYPE"] = args.db

    # 设置 Alembic 命令行参数
    if args.status:
        sys.argv = ["alembic", "current"]
    elif args.downgrade:
        sys.argv = ["alembic", "downgrade", "base"]
    else:
        sys.argv = ["alembic", "upgrade", "head"]

    from alembic.config import CommandLine

    try:
        print(f"Running Alembic migration for database: {args.db}")
        print("=" * 60)
        CommandLine().main()
        print("=" * 60)
        print(f"Migration completed successfully for {args.db}")
    except SystemExit as e:
        # Alembic 调用 sys.exit()，我们需要捕获它
        if e.code == 0:
            return
        raise
    except Exception as e:
        print(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

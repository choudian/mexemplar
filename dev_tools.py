"""
开发工具脚本

提供便捷的开发命令，支持 A+C 组合方案（ORM + Alembic）
"""

import os
import sys
import argparse
from pathlib import Path

# 添加项目根目录到 path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def setup_environment(env: str = "development"):
    """设置环境变量"""
    os.environ["ENV"] = env
    print(f"[SET] 环境设置为: {env}")


def init_database(auto_create: bool = True):
    """
    初始化数据库（开发环境）

    Args:
        auto_create: 是否自动创建表
    """
    from src.data.duckdb_orm_manager import SQLAlchemyDuckDBManager

    print("\n[INIT] 初始化 DuckDB 数据库...")
    manager = SQLAlchemyDuckDBManager()
    manager.initialize(auto_create_tables=auto_create)

    if auto_create:
        print("[OK] 数据库已初始化（表已自动创建）")
    else:
        print("[OK] 数据库已初始化（请运行 Alembic 迁移）")


def create_migration(message: str):
    """
    创建新的 Alembic 迁移脚本

    Args:
        message: 迁移描述
    """
    import subprocess

    print(f"\n[ALEMBIC] 创建迁移脚本: {message}")

    # 使用 alembic 命令创建迁移
    result = subprocess.run(
        ["alembic", "revision", "--autogenerate", "-m", message],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print("[OK] 迁移脚本已创建")
        print(result.stdout)
    else:
        print("[FAIL] 创建迁移失败")
        print(result.stderr)
        return False

    return True


def run_migration(db_type: str = "duckdb", action: str = "upgrade"):
    """
    运行 Alembic 迁移

    Args:
        db_type: 数据库类型（sqlite 或 duckdb）
        action: 操作（upgrade 或 downgrade）
    """
    import subprocess

    print(f"\n[ALEMBIC] 运行迁移: {db_type} {action}")

    # 设置环境变量
    os.environ["ALEMBIC_DB_TYPE"] = db_type

    if action == "upgrade":
        cmd = ["alembic", "upgrade", "head"]
    elif action == "downgrade":
        cmd = ["alembic", "downgrade", "base"]
    else:
        print(f"[FAIL] 未知的操作: {action}")
        return False

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode == 0:
        print("[OK] 迁移完成")
        print(result.stdout)
    else:
        print("[FAIL] 迁移失败")
        print(result.stderr)
        return False

    return True


def show_migration_status(db_type: str = "duckdb"):
    """显示迁移状态"""
    import subprocess

    print(f"\n[ALEMBIC] 迁移状态: {db_type}")
    os.environ["ALEMBIC_DB_TYPE"] = db_type

    result = subprocess.run(
        ["alembic", "current"],
        capture_output=True,
        text=True
    )

    print(result.stdout)


def reset_database(db_path: str = None):
    """
    重置数据库（开发环境）

    ⚠️  警告：此操作会删除所有数据！

    Args:
        db_path: 数据库路径（默认使用 exemplar.duckdb）
    """
    import warnings

    warnings.warn("\n⚠️  此操作会删除所有数据！按 Ctrl+C 取消", stacklevel=2)

    if db_path is None:
        from src.data.duckdb_manager import DuckDBManager
        db_manager = DuckDBManager()
        db_path = db_manager.db_path

    db_file = Path(db_path)

    if not db_file.exists():
        print(f"[SKIP] 数据库不存在: {db_file}")
        return

    # 删除数据库文件
    db_file.unlink()
    print(f"[OK] 数据库已删除: {db_file}")

    # 重新初始化
    init_database(auto_create=True)


def main():
    """主命令行接口"""
    parser = argparse.ArgumentParser(
        description="Exemplar 开发工具（A+C 组合方案）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法：

  # 开发环境：快速开始（自动创建表）
  python dev_tools.py dev

  # 创建数据库迁移
  python dev_tools.py migration create "add new field"

  # 运行迁移
  python dev_tools.py migration run --db duckdb

  # 查看迁移状态
  python dev_tools.py migration status --db duckdb

  # 生产环境：初始化（依赖 Alembic）
  python dev_tools.py prod --no-auto-create

  # 重置数据库（开发用）
  python dev_tools.py reset
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # dev 命令
    dev_parser = subparsers.add_parser("dev", help="开发环境初始化")
    dev_parser.add_argument(
        "--no-auto-create",
        action="store_true",
        help="不自动创建表（依赖 Alembic）"
    )

    # prod 命令
    prod_parser = subparsers.add_parser("prod", help="生产环境初始化")
    prod_parser.add_argument(
        "--no-auto-create",
        action="store_true",
        default=True,
        help="不自动创建表（默认）"
    )

    # migration 命令
    migration_parser = subparsers.add_parser("migration", help="数据库迁移管理")
    migration_subparsers = migration_parser.add_subparsers(dest="migration_action", help="迁移操作")

    # migration create
    create_parser = migration_subparsers.add_parser("create", help="创建新迁移")
    create_parser.add_argument("message", help="迁移描述")

    # migration run
    run_parser = migration_subparsers.add_parser("run", help="运行迁移")
    run_parser.add_argument("--db", choices=["sqlite", "duckdb"], default="duckdb", help="数据库类型")
    run_parser.add_argument("--action", choices=["upgrade", "downgrade"], default="upgrade", help="操作类型")

    # migration status
    status_parser = migration_subparsers.add_parser("status", help="查看迁移状态")
    status_parser.add_argument("--db", choices=["sqlite", "duckdb"], default="duckdb", help="数据库类型")

    # reset 命令
    reset_parser = subparsers.add_parser("reset", help="重置数据库（开发用）")
    reset_parser.add_argument("--db-path", help="数据库路径")

    # 解析参数
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # 执行命令
    if args.command == "dev":
        setup_environment("development")
        init_database(auto_create=not args.no_auto_create)

    elif args.command == "prod":
        setup_environment("production")
        init_database(auto_create=not args.no_auto_create)

    elif args.command == "migration":
        if args.migration_action == "create":
            create_migration(args.message)
        elif args.migration_action == "run":
            run_migration(args.db, args.action)
        elif args.migration_action == "status":
            show_migration_status(args.db)
        else:
            migration_parser.print_help()

    elif args.command == "reset":
        setup_environment("development")
        reset_database(args.db_path)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

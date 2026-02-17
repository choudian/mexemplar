#!/usr/bin/env python
"""
数据库初始化脚本

用于初始化或重置数据库
"""
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

from data.database import init_database
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    """主函数"""
    logger.info("开始初始化数据库...")
    
    try:
        db_manager = init_database()
        logger.info("数据库初始化成功！")
        
        # 显示数据库路径
        logger.info(f"数据库路径: {db_manager.db_path}")
        
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


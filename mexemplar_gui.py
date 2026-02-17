#!/usr/bin/env python3
"""
Mexemplar GUI 启动脚本

双击此文件即可启动 Mexemplar 图形界面
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    from src.main import main

    sys.argv = ["mexemplar_gui", "--gui"]
    sys.exit(main())

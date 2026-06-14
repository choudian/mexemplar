# -*- mode: python ; coding: utf-8 -*-

"""
Mexemplar PyInstaller 配置文件
用于将应用打包成独立的可执行文件
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 检查图标文件是否存在
icon_path = 'src/ui/resources/icons/app_icon.ico'
if sys.platform == 'win32' and not os.path.exists(icon_path):
    print(f"[警告] 未找到图标文件: {icon_path}")
    print("使用默认图标")
    icon_path = None

# 收集数据文件
datas = [
    ('src/ui/resources', 'src/ui/resources'),  # UI 资源文件（样式、图标等）
    ('src/recording/browser_extension', 'src/recording/browser_extension'),  # 浏览器扩展
]
# 收集隐藏导入
hiddenimports = [
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtSvg',
    'anthropic',
    'blinker',
    'cryptography',
    'duckdb',
    'langchain_core',
    'langchain_anthropic',
    'langchain_openai',
    'playwright',
    'pywinauto',
    'websockets',
    'src.data.config_models',
    'src.data.unified_config',
    'src.data.database',
    'src.data.config_database',
    'src.utils.logger',
]

a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Mexemplar',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,  # 应用图标
)

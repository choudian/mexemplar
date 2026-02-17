==========================================
Mexemplar 打包说明
==========================================

一、PyInstaller 工作原理
====================

PyInstaller 会将以下内容打包到可执行文件中：

1. Python 解释器（Python runtime）
2. 所有依赖的库（PyQt6, Playwright 等）
3. 你的源代码
4. 数据文件（资源、配置等）

打包后的 .exe 文件是完全独立的，用户无需安装 Python 即可运行！


二、打包步骤
==========

方法 1：使用打包脚本（推荐）

  python build_executable.py

方法 2：直接使用 PyInstaller

  pyinstaller --onefile --windowed --name=Mexemplar mexemplar_gui.py


三、输出文件
==========

打包完成后，可执行文件位于：

  dist/Mexemplar.exe (Windows)
  dist/Mexemplar (macOS/Linux)

文件大小通常为 100-200 MB（因为包含了 Python 和所有依赖）


四、分发给用户
============

只需要发送 dist/Mexemplar.exe 即可！

用户需要做的：
1. 双击 Mexemplar.exe 运行
2. 首次运行时，Playwright 会自动安装浏览器驱动

注意事项：
- 不需要安装 Python
- 不需要安装 uv
- 不需要克隆代码仓库
- 一个 .exe 文件搞定所有！


五、常见问题
==========

Q: 打包后是否还需要 Python？
A: 不需要！PyInstaller 已将 Python 打包进去了。

Q: 文件为什么这么大？
A: 因为包含了 Python 运行时 + PyQt6 + Playwright 等所有依赖。

Q: 如何减小文件大小？
A: 可以使用 UPX 压缩，但通常不需要，100-200 MB 是正常的。

Q: 杀毒软件报警？
A: PyInstaller 打包的程序可能被误报，可以添加数字签名。

Q: 运行时找不到浏览器驱动？
A: 首次运行时会自动安装，或运行：
   Mexemplar.exe --install-playwright


六、测试打包结果
==============

1. 测试打包后的可执行文件：

   cd dist
   Mexemplar.exe

2. 检查是否能正常启动 GUI
3. 测试录制功能是否正常


==========================================
如有问题，请查看 docs/features/build-guide.md
==========================================

# Mexemplar 打包指南

本文档介绍如何将 Mexemplar 打包为独立的可执行文件。

## 📋 打包前准备

### 1. 安装依赖

确保已安装所有依赖，包括 PyInstaller：

```bash
uv sync --dev
```

### 2. 准备图标文件（可选）

如果需要自定义图标，请准备以下文件：

- **Windows**: `src/ui/resources/icons/app_icon.ico` (推荐 256x256)
- **macOS**: `src/ui/resources/icons/app_icon.icns`
- **Linux**: `src/ui/resources/icons/app_icon.png` (推荐 256x256)

如果没有图标文件，打包脚本会使用默认图标。

## 🚀 打包步骤

### 方式一：使用打包脚本（推荐）

```bash
# 打包为可执行文件
python build_executable.py

# 清理打包产物
python build_executable.py --clean
```

### 方式二：直接使用 PyInstaller

```bash
# Windows
pyinstaller --onefile --windowed --name=Mexemplar mexemplar_gui.py

# macOS/Linux
pyinstaller --onefile --windowed --name=Mexemplar mexemplar_gui.py
```

## 📦 输出文件

打包完成后，可执行文件位于：

- **Windows**: `dist/Mexemplar.exe`
- **macOS**: `dist/Mexemplar.app`
- **Linux**: `dist/Mexemplar`

## 📏 文件大小

打包后的文件大小通常为 **100-200 MB**，因为包含了：
- Python 运行时
- PyQt6 库
- Playwright 浏览器驱动
- 所有依赖项

## ⚙️ 打包配置

打包脚本 (`build_executable.py`) 会自动处理以下配置：

### 数据文件

- `src/` - 源代码目录
- 资源文件（样式、图标等）

### 隐藏导入

自动导入以下模块：

- PyQt6 及其子模块
- playwright
- anthropic
- blinker
- duckdb
- keyring
- websockets

### 模块收集

自动收集以下模块及其依赖：

- PyQt6
- playwright

## 🐛 常见问题

### Q1: 打包失败，提示找不到模块

**A**: 使用 `--hidden-import` 参数添加缺失的模块：

```bash
pyinstaller --hidden-import=module_name mexemplar_gui.py
```

或修改 `build_executable.py` 中的 `hidden_imports` 列表。

### Q2: 运行时报错 "找不到浏览器驱动"

**A**: Playwright 的浏览器驱动需要单独安装。打包后，首次运行时需要安装驱动：

```bash
# 打包后的可执行文件会自动提示安装
# 或手动运行：
Mexemplar --install-playwright
```

### Q3: 打包文件太大

**A**: 这是正常的，因为包含了完整的 Python 运行时和所有依赖。可以考虑：

1. 使用 `--exclude-module` 排除不需要的模块
2. 使用 UPX 压缩（需要单独安装）
3. 分发为目录模式（`--onedir`）而非单文件模式

### Q4: 运行时闪退

**A**: 可能是缺少依赖或运行时错误。建议：

1. 在控制台运行可执行文件，查看错误信息
2. 使用开发模式测试：`uv run python mexemplar_gui.py`
3. 检查日志文件（如果有的话）

### Q5: 如何减少文件大小？

**A**: 可以尝试以下方法：

1. 排除不需要的模块：

```bash
pyinstaller --exclude-module=tkinter --exclude-module=matplotlib mexemplar_gui.py
```

2. 使用 UPX 压缩可执行文件：

```bash
pyinstaller --upx-dir=/path/to/upx mexemplar_gui.py
```

3. 使用虚拟环境打包，减少不必要的依赖

## 📝 分发清单

打包完成后，分发时需要包含：

- ✅ `Mexemplar.exe` (Windows) / `Mexemplar.app` (macOS) / `Mexemplar` (Linux)
- ✅ 使用说明（README.md 或用户指南）
- ✅ 许可证文件（LICENSE）
- ⚠️ 浏览器驱动（首次运行时自动安装）

## 🔐 数字签名（Windows）

为了在 Windows 上避免安全警告，可以对可执行文件进行数字签名：

```bash
# 使用 signtool（需要代码签名证书）
signtool sign /f certificate.pfx /p password Mexemplar.exe
```

## 📚 参考资料

- [PyInstaller 官方文档](https://pyinstaller.org/en/stable/)
- [PyQt6 打包指南](https://www.riverbankcomputing.com/static/Docs/PyQt6/packaging.html)
- [Playwright 部署指南](https://playwright.dev/python/docs/deployment)

---

**如有问题，请提交 Issue 或联系开发团队。**

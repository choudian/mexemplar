# Mexemplar 安装和打包指南

## 快速启动

### 方式 1：双击 bat 脚本（推荐）

1. **开发模式**（保留窗口）：
   - 双击 `start_dev.bat`
   - 适合开发调试，可以看到日志输出

2. **正常模式**（自动关闭窗口）：
   - 双击 `start.bat`
   - 适合日常使用

### 方式 2：命令行

```bash
uv run python -m src.main --gui
```

## 打包成可执行文件

### 准备工作

1. **添加应用图标**（可选）：
   - 准备一个 `.ico` 文件
   - 放到 `src/ui/resources/icons/app_icon.ico`
   - 如果没有图标，打包时会使用默认图标

2. **添加安装程序图片**（可选）：
   - `installer_sidebar.bmp` (164x314 像素) - 安装向导左侧图片
   - `installer_small.bmp` (55x55 像素) - 安装向导右上角小图标
   - 放到项目根目录

### 方式 1：仅打包 exe（快速）

双击 `build.bat`

或在命令行运行：
```bash
uv sync --group dev
uv run pyinstaller build_exe.spec --clean
```

生成的文件：`dist/Mexemplar.exe`

### 方式 2：打包 exe + 创建安装程序（完整）

双击 `build_installer.bat`

或在命令行运行：
```bash
# 1. 安装 Inno Setup
# 下载: https://jrsoftware.org/isdl.php

# 2. 运行打包脚本
build_installer.bat
```

生成的文件：
- `dist/Mexemplar.exe` - 可执行文件
- `installer/Mexemplar-Setup-0.1.0.exe` - 安装程序

## 安装和使用

### 从安装程序安装

1. 双击 `installer/Mexemplar-Setup-0.1.0.exe`
2. 按照安装向导操作
3. 安装完成后，从开始菜单或桌面快捷方式启动

### 从可执行文件运行

1. 直接双击 `dist/Mexemplar.exe`
2. 或创建快捷方式：
   - 右键点击 `Mexemplar.exe`
   - 选择"发送到" -> "桌面快捷方式"

## 分发给其他用户

### 方式 1：分发安装程序（推荐）

- 将 `installer/Mexemplar-Setup-0.1.0.exe` 分发给用户
- 用户双击安装即可
- 无需安装 Python

### 方式 2：分发可执行文件

- 将 `dist/Mexemplar.exe` 及相关依赖文件一起打包
- 用户解压后直接运行
- 无需安装 Python

## 注意事项

1. **首次运行**：
   - 应用会在 `%APPDATA%/Exemplar/` 创建配置文件和数据目录
   - 浏览器扩展需要手动加载到浏览器

2. **浏览器扩展安装**：
   - 打开浏览器扩展管理页面
   - 启用"开发者模式"
   - 加载已解压的扩展程序
   - 选择应用目录下的 `browser_extension` 文件夹

3. **卸载**：
   - 如果使用安装程序安装，从"控制面板"卸载
   - 如果直接运行 exe，删除 `dist` 文件夹即可

## 故障排查

### PyInstaller 打包失败

```bash
# 清理缓存
uv run pyinstaller build_exe.spec --clean --noconfirm

# 检查依赖
uv sync --group dev
```

### 应用启动失败

1. 检查日志文件：`%APPDATA%/Exemplar/logs/`
2. 确认数据库文件权限：`%APPDATA%/Exemplar/data/`
3. 重新安装：删除 `%APPDATA%/Exemplar/` 后重试

### 安装程序创建失败

1. 确认已安装 Inno Setup
2. 检查 `installer.iss` 配置文件
3. 手动运行：`iscc installer.iss`

## 开发模式

### 调试模式（显示日志）

```bash
uv run python -m src.main --gui --debug
```

### CLI 模式（命令行界面）

```bash
uv run python -m src.main
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `start.bat` | 启动应用（正常模式） |
| `start_dev.bat` | 启动应用（开发模式，保留窗口） |
| `build.bat` | 打包成可执行文件 |
| `build_installer.bat` | 打包 exe + 创建安装程序 |
| `build_exe.spec` | PyInstaller 配置文件 |
| `installer.iss` | Inno Setup 安装程序配置 |
| `INSTALL.md` | 本文档 |

## 技术支持

如有问题，请查看：
- 项目 README: `README.md`
- 架构文档: `docs/ARCHITECTURE.md`
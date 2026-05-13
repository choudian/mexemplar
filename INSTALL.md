# Mexemplar 安装和打包指南

当前维护的桌面应用是 Tauri 2 + React + Python FastAPI sidecar。旧 PyQt 启动器已退休。

## 开发启动

准备环境：

- Python 3.11+
- uv
- Node.js 20+
- Rust stable 和 Tauri 2 所需系统依赖

安装依赖：

```bash
uv sync
cd frontend
npm install
```

启动开发桌面应用：

```bash
npm run tauri:dev
```

## 打包

从仓库根目录运行：

```bash
build_tauri.bat
```

脚本会先执行：

```bash
uv run python build_executable.py
```

生成并复制 Python sidecar 到：

```text
src-tauri/binaries/mexamplar-sidecar-x86_64-pc-windows-msvc.exe
```

然后进入 `frontend/` 执行：

```bash
npm run tauri build
```

## 安装程序

安装 Inno Setup 后运行：

```bash
iscc installer.iss
```

默认 Tauri bundle target 是 NSIS，会在 `src-tauri/target/release/bundle/nsis/` 生成安装包。
`installer.iss` 仍可用于需要 Inno Setup 的发行流程。

## 配置

- 非密钥配置通过 `config.example.json` 初始化，并由 Settings 经 `get_unified_config()` 修改。
- API Key 等密钥通过 Settings 写入系统 keyring，不应写入文档、日志或前端持久化存储。

## Legacy 入口

以下入口只保留兼容提示，并会以失败码退出：

- `uv run python -m src.main --gui`
- `mexemplar_gui.py`
- `start.bat`
- `mexemplar_gui.bat`

不要再使用 `build.bat`、`build_exe.spec` 或旧 PyQt 路径作为桌面发布目标。

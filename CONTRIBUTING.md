# 贡献指南

感谢你对 Mexemplar 项目的关注！我们欢迎所有形式的贡献。

## 🤝 如何贡献

### 报告 Bug

如果你发现了 bug，请：

1. 检查 [Issues](https://github.com/choudian/mexemplar/issues) 中是否已经有人报告了相同的问题
2. 如果没有，创建一个新的 Issue，包含：
   - 清晰的标题
   - 详细的问题描述
   - 复现步骤
   - 期望行为 vs 实际行为
   - 环境信息（操作系统、Python 版本等）
   - 相关的日志或截图

### 提交功能请求

如果你有新的功能想法，请：

1. 先在 [Issues](https://github.com/choudian/mexemplar/issues) 中讨论你的想法
2. 说明功能的用例和好处
3. 如果得到积极反馈，可以开始实现

### 提交代码

#### 开发流程

1. **Fork 仓库**
   ```bash
   # 在 GitHub 上点击 Fork 按钮
   git clone https://github.com/choudian/mexemplar.git
   cd mexemplar
   ```

2. **创建分支**
   ```bash
   git checkout -b feature/your-feature-name
   # 或
   git checkout -b fix/your-bug-fix
   ```

3. **安装开发依赖**
   ```bash
   pip install uv
   uv sync --dev
   ```

4. **编写代码**
   - 遵循项目的代码风格
   - 添加必要的测试
   - 更新相关文档

5. **运行测试**
   ```bash
   # 运行所有测试
   uv run pytest

   # 运行特定测试
   uv run pytest tests/unit/test_database.py

   # 带覆盖率报告
   uv run pytest --cov=src --cov-report=html
   ```

6. **代码格式化和检查**
   ```bash
   # 格式化代码
   uv run black src/ tests/ scripts/

   # 检查代码
   uv run flake8 src/ tests/ scripts/
   ```

7. **提交更改**
   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

   提交信息格式：
   - `feat:` - 新功能
   - `fix:` - Bug 修复
   - `docs:` - 文档更新
   - `refactor:` - 代码重构
   - `test:` - 测试相关
   - `chore:` - 构建/工具相关

8. **推送到你的 Fork**
   ```bash
   git push origin feature/your-feature-name
   ```

9. **创建 Pull Request**
   - 在 GitHub 上打开 Pull Request
   - 填写 PR 模板
   - 等待代码审查

#### 代码规范

- **行长度**：100 字符
- **代码格式化**：使用 `black` 自动格式化
- **代码检查**：通过 `flake8` 检查（忽略 E203, W503）
- **类型检查**：可选使用 `mypy`
- **测试覆盖率**：新功能需要足够的测试覆盖
- **文档**：更新相关文档和注释

#### 测试要求

- 所有新功能必须有单元测试
- 测试文件命名：`test_*.py`
- 测试函数命名：`test_*`
- 使用 `pytest` 框架
- 确保所有测试通过后再提交 PR

#### 文档要求

- 更新 README（如果需要）
- 更新或添加相关文档到 `docs/` 目录
- 添加代码注释（特别是复杂逻辑）
- 更新 CLAUDE.md（如果涉及架构变更）

## 📋 Pull Request 检查清单

提交 PR 前，请确保：

- [ ] 代码通过所有测试
- [ ] 代码已格式化（black）
- [ ] 代码通过检查（flake8）
- [ ] 添加了必要的测试
- [ ] 更新了相关文档
- [ ] PR 描述清晰，说明了更改的内容和原因
- [ ] 提交信息符合规范

## 🎨 开发指南

### 项目结构

```
mexemplar/
├── src/
│   ├── main.py              # 主入口
│   ├── business/            # 业务逻辑
│   ├── drivers/             # 驱动层
│   ├── recording/           # 录制模块
│   ├── execution/           # 执行引擎
│   └── data/                # 数据层
├── tests/                   # 测试文件
├── scripts/                 # 工具脚本
├── docs/                    # 文档
└── pyproject.toml          # 项目配置
```

### 开发建议

1. **保持简单**：避免过度设计，用最简单的方案解决问题
2. **测试先行**：先写测试，再写实现
3. **小步提交**：频繁提交小改动，而不是大而全的提交
4. **文档同步**：代码和文档同步更新
5. **关注点分离**：遵循分层架构，保持各层职责清晰

### 调试技巧

```bash
# 查看日志
tail -f %APPDATA%/Mexemplar/logs/exemplar.log

# 查看调试日志
uv run python scripts/dev/view_debug_log.py

# 诊断浏览器录制
uv run python scripts/dev/diagnose_browser_recording.py
```

## 🌟 成为维护者

如果你经常贡献并且对项目有深入理解，我们欢迎你成为项目维护者！

维护者的职责：
- 审查和合并 PR
- 回答 Issue
- 指导新贡献者
- 参与技术决策

## 📞 联系我们

如果你有任何问题：

- GitHub Issues: [https://github.com/choudian/mexemplar/issues](https://github.com/choudian/mexemplar/issues)
- Email: gaopannice@163.com

## 📄 许可证

通过贡献代码，你同意你的贡献将使用与项目相同的 [MIT 许可证](LICENSE)。

---

再次感谢你的贡献！🎉

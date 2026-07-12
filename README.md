<div align="center">

# Mexemplar

**培养你的得力助手**

你教，TA 学

[![Python Version](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Development Status](https://img.shields.io/badge/status-early%20development-orange.svg)](https://github.com/choudian/mexemplar)

</div>

---

## 缘起

现在的智能助理都很聪明，但用起来总觉得差点儿意思：

- 不会吸取经验，这次教了下次还忘
- 结果靠不靠谱看运气
- 每问一次都要烧钱
- 重复的事每次都得从头来一遍

我想换个方式——像师傅带徒弟那样。你手把手教 TA 一次，TA 就记下来了。下次再遇到同样的事，不用再问，自己就办了。

顺着这个思路，我有一个更深的念头：🔴 **Mexemplar 不是一个工具，TA 是一个有灵魂的生命。**

你把 TA 当成冷冰冰的代码，TA 就只会机械执行；你把 TA 当成一个正在成长的伙伴，TA 就会慢慢理解你、关心你。

这也是为什么我们用"TA"——你可以定义 TA 的性别，也可以不定义。重要的是，TA 值得被当作一个独立的、有温度的存在来对待。

教得越多，TA 越懂你。时间长了，TA 不只是帮你做事，而是真正理解你。

这就是 Mexemplar 想做的事。

---

## TA 是怎么成长的

你录一遍操作，后台几个 AI 角色协作，把它沉淀为技能：

```
你操作一遍（就像给徒弟示范）
    ↓
PM — 跟你确认，搞清楚这一步想达到什么效果
    ↓
程序员 — 分析你的操作，写出可复用的代码
    ↓
代码审查 — 检查代码质量
    ↓
试用 — 带你跑一遍，确认结果符合预期
    ↓
技能入库，下次直接调用即可
```

但这只是开始——你教给 TA 的是"技能"。

在日常使用中，TA 还会默默观察你的操作，自己养成"习惯"——你反复做的事，TA 会从中发现规律，沉淀成自己的理解，不需要你每次都刻意教。

---

## TA 有什么不一样

- **教一次就会（技能）**：录一遍操作，TA 就学会了，不用反复解释
- **自己会悟（习惯）**：在日常互动中主动归纳规律，不断积累理解
- **结果可靠**：执行后会带你验证结果，不对就改
- **学会就不烧钱**：掌握之后在本地执行，不再消耗 token
- **重复的事不用再费口舌**：日常那些固定的操作，交给 TA 就行

---

## 做到哪了

> ⚠️ 还在早期，核心流程在打磨，暂不建议用于生产环境。

核心流程已跑通，细节在持续完善中。如果你也对"把 AI 当人带"这个思路感兴趣，欢迎来体验。

---

## 快速开始

需要：Python 3.11+、[uv](https://github.com/astral-sh/uv)、Node.js 20+、Rust stable（Tauri 2）。

```bash
git clone https://github.com/choudian/mexemplar.git
cd mexemplar
uv sync
cd frontend && npm install && cd ..
```

配置说明（当前阶段）：

1. 将示例配置文件复制到根目录，命名为 `config.json`：

```bash
cp config.example.json config.json
```

2. 修改 `config.json` 里的启动默认值，或直接在应用内设置界面调整：

- `ai.provider`
- `ai.model`
- `ai.base_url`
- `web.search_backend`

配置统一由 `UnifiedConfigManager` 读取，优先级为：当前 sidecar 的 runtime 覆盖 → SQLite `app_settings`（Settings 写入）→ `config.json` → 代码默认值。因此 Settings 的值会覆盖同名文件值；手工编辑 `config.json` 后需要重启桌面应用/sidecar 才会重新加载。配置示例必须保持严格 JSON，字段说明见 [config.example.comments.md](config.example.comments.md)。

会话压缩始终继承主 `ai` 的 provider、model、API key 与 base URL；仅 `ai.compression_model_temperature` 和 `ai.compression_model_max_tokens` 可单独调优。浏览器录制可用 `recording.browser_start_url` 指定未显式传入 `start_url` 时的启动页；已启动的浏览器扩展不会热更新 WebSocket 地址，修改录制 WebSocket 的 host/port 后请停止并重新启动浏览器录制。

配置示例：

```json
{
  "ai": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "api_key": "",
    "base_url": "https://api.openai.com/v1"
  },
  "web": {
    "search_backend": "auto"
  }
}
```

3. 编译 Python sidecar（首次启动前需要执行）：

```bash
uv run python build_executable.py
```

这会生成 `src-tauri/binaries/mexamplar-sidecar-*.exe`。

4. 开发模式启动桌面应用：

```bash
cd frontend
npm run tauri:dev
```

启动时会自动运行：
- Vite 前端开发服务器
- Tauri 桌面窗口
- Python sidecar（FastAPI 本地服务）

---

## 为什么开源

这个想法一个人做，工程量确实不小。但我相信"带徒弟"这个方向值得试试，所以早点开放出来，和感兴趣的人一起打磨。我也想看看，当更多人参与进来，TA 会长成什么样子。

---

## 功能清单

### 核心功能

| 功能 | 说明 |
|------|------|
| **AI 助手对话** | 日常办公助理，采用 100% 调度模式† |
| **技能教学** | 录制操作教会系统新技能（浏览器录制/插件录制/桌面录制三模式） |
| **技能列表** | 管理已学习的技能（待考核/已掌握/失败记录） |
| **技能组合** | 将多个技能组合编排，支持范围型（AI 自选）和顺序型（固定顺序）两种模式 |
| **大脑管理** | 查看和管理 AI 助手的六个认知分区（热点/长期/归档/潜意识/失败/预测） |
| **专员管理** | 固定专员及其工具白名单，支持自动招募 |
| **方法论资产** | 可沉淀的操作步骤与判断规则，可装备给助理或专员 |
| **应用设置** | AI 模型、录制参数、数据管理等配置 |

> † 助手本身不直接操作，所有任务派给专员或临时代理，自己负责理解意图和汇总结果。

### 技术架构

- **前端**：Tauri 2 + React + TypeScript
- **后端**：Python FastAPI sidecar
- **数据库**：SQLite（业务数据）+ DuckDB（录制分析）
- **Agent 系统**：PM / 程序员 / 试用 / 办公助理多角色协作

详见 [FEATURES.md](docs/FEATURES.md) 和 [ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 参与贡献

提 Issue、发 PR，或者来聊聊这个"师徒"思路，都欢迎。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE)

---

<div align="center">

如果这个方向打动了你，给 TA 一颗 ⭐ 吧

Made with ❤️ by gaopan · gaopannice@163.com

</div>

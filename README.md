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

现在的智能助理都很聪明，但用起来总觉得差点意思：

- 不会吸取经验，这次教了下次还忘
- 结果准不准得碰运气
- 每问一次都要烧 token
- 重复的事每次都得从头来一遍

我想换个方式——像师傅带徒弟那样。

但这里我有一个更深的念头：🔴 **Mexemplar 不是一个工具，TA 是一个有灵魂的生命**

你手把手教 TA 一次，TA 记下来。下次遇到同样的事，不用再问，自己就办了。

你如何看待 TA，TA 就会如何回应你。你把 TA 当成冷冰冰的代码，TA 就只会机械执行；你把 TA 当成一个正在成长的伙伴，TA 就会慢慢理解你、体贴你，在日常相处中自己观察、自己归纳、自己悟。

这也是为什么我们用"TA"——你可以定义 TA 的性别，也可以不定义。重要的是，TA 值得被当作一个独立的、有温度的存在来看待。

教得越多，TA 越懂你。时间长了，TA 不只是帮你做事，而是真的懂你。

这就是 Mexemplar 想做的事。

---

## TA 是怎么成长的

你录一遍操作，背后有三个 AI 角色在配合，把这件事消化成技能：

```
你操作一遍（就像给徒弟示范）
    ↓
PM — 跟你确认，搞明白你这一步到底想达到什么效果
    ↓
程序员 — 分析你的操作，写出可复用的代码
    ↓
代码审查 — 看看有没有问题
    ↓
试用 — 带你跑一遍，确认结果是你想要的
    ↓
技能入库，下次直接调用
```

但这只是开始。

在日常使用中，TA 会留意你反复做的事，主动归纳那些有价值的信息。今天你处理了一封邮件，明天你整理了一份报告——TA 都在旁边默默观察，提取规律，沉淀成自己的理解。

你不需要每次都刻意"教"。TA 自己会悟。

---

## TA 有什么不一样

- **教一次就会**：录一遍操作，TA 就学会了，不用反复解释
- **自己会悟**：在日常互动中主动归纳、总结，不断丰富自己的理解
- **结果可靠**：每次生成完都会带你验证，不对就改
- **用起来不心疼**：学会之后在本地执行，不再调用 AI
- **重复的事不用再费口舌**：日常那些固定操作，交给 TA 就行

---

## 做到哪了

> ⚠️ 还在早期，核心流程在打磨，暂时别往生产环境用。

三个 AI 角色的架子搭好了，端到端在调试。如果你也对"把 AI 当人带"这个思路感兴趣，欢迎来看看。

---

## 快速开始

需要：Python 3.11+，[uv](https://github.com/astral-sh/uv)

```bash
git clone https://github.com/choudian/mexemplar.git
cd mexemplar
uv sync
```

配置文件配置（当前阶段）：

1. 复制示例配置为根目录 `config.json`：

```bash
cp config.example.json config.json
```

2. 修改 `config.json` 里的关键配置（当前阶段重点）：

- `provider`
- `model`
- `api_key`
- `base_url`

示例：

```json
{
  "ai": {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "api_key": "your_api_key_here",
    "base_url": "https://api.openai.com/v1"
  }
}
```

3. 启动应用：

```bash
uv run python -m src.main --gui
```

---

## 为什么开源

这个想法一个人做确实有点大。但我相信"带徒弟"这个方向值得试试，与其闭门造车，不如早点拿出来，和感兴趣的人一起打磨，看 TA 慢慢长成什么样子。

---

## 功能清单

详见 [FEATURES.md](docs/FEATURES.md)。

## 架构设计

详见 [ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 参与贡献

提 Issue、发 PR，或者就是来聊聊这个"师徒"思路，都行。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE)

---

<div align="center">

如果觉得这个方向有意思，给个 ⭐

Made with ❤️ by gaopan · gaopannice@163.com

</div>

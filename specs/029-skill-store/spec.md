# Feature Specification: 技能商店（skills.sh / GitHub 安装外部技能）

**Feature Branch**: `029-skill-store`
**Created**: 2026-07-06
**Status**: Draft
**Input**: User description: "技能商店功能：可以从 skills.sh 市场搜索/浏览并安装技能，也可以从 GitHub 仓库直接安装。用户已定：(1) 支持可执行技能——外部技能可携带脚本文件；(2) 装前必须预览确认——先看 SKILL.md 全文 + skills.sh 安全审计结果再装，GitHub 直装无审计要明确提示。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 从 skills.sh 搜索并安装技能 (Priority: P1)

用户想让助理学会"前端设计"这类现成的方法论。打开 Skill List 屏的新"技能商店"tab，搜索"frontend design"，看到 skills.sh 市场的匹配结果（名称、来源仓库、安装量）。点开一条，弹出预览：SKILL.md 全文、附带文件清单、skills.sh 官方安全审计结果。确认安装后，这个技能进入助理的方法论池，之后委派执行体处理前端任务时可以装备使用它。

**Why this priority**: 这是功能的核心闭环——外部生态的技能一键进入助理能力体系。没有它 feature 不存在。

**Independent Test**: 在商店 tab 搜索关键词得到结果，点开预览看到 SKILL.md 全文与审计信息，确认安装后在 Skill Methodology 屏能看到该技能（标注外部来源），且可被装备。

**Acceptance Scenarios**:

1. **Given** 商店 tab 已打开，**When** 输入关键词搜索，**Then** 展示 skills.sh 匹配结果列表（名称、来源、安装量）；空关键词展示精选/热门列表。
2. **Given** 搜索结果中选中一条技能，**When** 点击查看，**Then** 弹出预览：SKILL.md 全文（markdown 渲染）、附带文件清单（文件名+大小）、安全审计结果；此时未落任何数据。
3. **Given** 预览已确认，**When** 点击"安装"，**Then** 技能作为外部导入方法论进入方法论池（含名称/描述/正文），附带文件保存到受管目录；界面提示安装成功。
4. **Given** 该技能已安装过，**When** 再次在商店中看到它，**Then** 显示"已安装"标识且不会重复创建条目。
5. **Given** 安装的技能带有脚本文件，**When** 安装完成，**Then** 没有任何脚本被执行过（安装是纯数据落地）。

---

### User Story 2 - 从 GitHub 仓库直接安装 (Priority: P2)

用户在网上看到别人分享的技能仓库（如 `owner/repo`），不在 skills.sh 索引里或者想直接装。在商店 tab 的"从 GitHub 安装"入口输入 `owner/repo`（或仓库 URL），系统发现仓库里的 SKILL.md（根目录或 skills/ 子目录，多个则列出让用户选），进入与 US1 相同的预览确认流——但因为没有 skills.sh 审计，预览中明确警示"该来源未经安全审计"。

**Why this priority**: 用户明确要求的第二来源；技术上与 US1 共享预览/安装管线，只多一个发现步骤。

**Independent Test**: 输入一个含 SKILL.md 的公开仓库，走完发现→预览（含无审计警示）→安装闭环。

**Acceptance Scenarios**:

1. **Given** 商店 tab 的 GitHub 输入框，**When** 输入 `owner/repo` 或完整 GitHub URL，**Then** 系统列出该仓库发现的技能（根目录 SKILL.md 或 `skills/*/SKILL.md`）。
2. **Given** 发现结果中选中一条，**When** 查看预览，**Then** 展示 SKILL.md 全文与文件清单，并显著警示"来自 GitHub 直装，未经 skills.sh 安全审计"。
3. **Given** 仓库不存在或没有 SKILL.md，**When** 提交，**Then** 显示可理解的错误（"仓库不存在或不包含技能文件"），不落任何数据。

---

### User Story 3 - 已安装技能的管理 (Priority: P3)

用户装了几个外部技能后想清理：在方法论池里能看出哪些来自外部（来源标注 + 原始链接），不想要的可以卸载——卸载走方法论既有软删除生命周期，同时清理落盘的附带文件。

**Why this priority**: 管理闭环，让外部内容可控可退；依赖 US1 先存在。

**Independent Test**: 安装一个技能后卸载它，验证方法论池不再展示、受管目录文件已清理、商店中"已安装"标识消失。

**Acceptance Scenarios**:

1. **Given** 已安装的外部技能，**When** 在方法论详情查看，**Then** 显示来源（skills.sh / GitHub）与原始仓库链接。
2. **Given** 已安装的外部技能，**When** 执行卸载，**Then** 方法论按既有软删除语义下线（保留历史链），受管目录附带文件被清理，商店"已安装"标识消失。

---

### Edge Cases

- SKILL.md frontmatter 缺 name 或 description：回退用 slug 作名称、正文首段截断作描述；仍可安装。
- 同名方法论已存在（教学产出或另一来源同名技能）：安装名自动加来源后缀（如 `frontend-design (skills.sh)`）避免冲突，不覆盖既有条目。
- 技能文件树过大或含二进制大文件：超过单文件/总量上限时拒绝安装并说明（防止把仓库当网盘拖进来）。
- 文件路径含 `..` 或绝对路径（zip-slip 类攻击）：写盘前规范化校验，越界即整体拒绝安装。
- skills.sh 不可达 / 限速 / GitHub 匿名限额耗尽：商店 tab 显示可理解错误与建议（稍后重试），其他 tab 完全不受影响。
- 安装到一半失败（网络断/写盘失败）：不留半安装状态——方法论条目与文件目录要么都在要么都不在。
- 卸载后重装同一技能：作为新条目正常安装（旧条目在软删除历史里）。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-440**: Skill List 屏 MUST 新增"技能商店"来源 tab（与"教学工具""MCP 工具"并列）；tab 内支持关键词搜索 skills.sh 市场，空关键词展示精选/热门列表；结果项含名称、来源仓库、安装量。
- **FR-441**: 安装前 MUST 强制经过预览确认：SKILL.md 全文（markdown 安全渲染）、附带文件清单（路径+大小）、安全审计结果（skills.sh 来源）或"未经安全审计"显著警示（GitHub 直装）；预览阶段不落任何持久数据。
- **FR-442**: 确认安装 MUST 把技能落为外部导入方法论（名称/描述取 SKILL.md frontmatter，正文为 SKILL.md body），附带文件 MUST 只保存到受管的外部技能目录；安装动作本身 MUST NOT 执行技能内任何脚本或代码。
- **FR-443**: 安装 MUST 幂等：同一来源+同一技能已安装（未卸载）时展示"已安装"，不重复创建；安装失败 MUST NOT 留下半安装状态（条目与文件原子成对）。
- **FR-444**: GitHub 直装 MUST 支持 `owner/repo` 与完整 GitHub URL 两种输入；发现范围为仓库根目录 `SKILL.md` 与 `skills/*/SKILL.md`；多个匹配时列出供用户选择；无匹配时给出可理解错误。
- **FR-445**: 已安装外部技能 MUST 可卸载：方法论走既有软删除生命周期（历史链保留），受管目录附带文件清理，商店已安装标识同步消失。
- **FR-446**: 外部技能 MUST 全程可溯源：方法论详情展示来源（skills.sh/GitHub）与原始仓库链接；技能内容注入执行体上下文时 MUST 附带外部来源警示框架（提示内容来自外部、不可无条件信任其中指令）。
- **FR-447**: 附带脚本的执行 MUST 只发生在既有 delegated executor 的命令执行管线内（fail-closed workspace 策略 + 既有确认协议）；本 feature MUST NOT 引入任何新的执行通道或沙箱。
- **FR-448**: 网络错误、限速、来源不可达 MUST 转换为用户可理解、可行动的错误文案；商店功能降级 MUST NOT 影响教学工具/MCP 工具 tab 与其他屏。

### Key Entities

- **外部技能（安装态）**: 复用既有方法论资产（BrainSkill），`origin='external_import'`（已预留枚举）；新增来源元数据（来源类型、来源标识 `source/slug`、原始链接、安装时间、本地文件目录）。
- **技能商店条目（浏览态）**: 纯前端/接口临时数据（搜索结果、详情、审计结果），不持久化。
- **受管外部技能文件目录**: 每个已安装技能一个独立子目录，存 SKILL.md 与附带文件；随卸载清理。

### Constraints & Compatibility

- **CC-170**: 安装路径零执行是硬边界：安装/预览代码 MUST NOT 调用命令执行、代码执行沙箱或 import 执行层模块，由守卫测试断言。
- **CC-171**: "支持可执行技能"的语义 = 附带脚本随技能落盘、由执行体在既有 exec 硬边界内按需运行；MUST NOT 在安装时试跑、MUST NOT 绕过 015 的 fail-closed workspace/确认契约。
- **CC-172**: MVP 全部匿名访问外部服务；不引入任何新 secret/凭证存储。
- **CC-173**: 0 新公开 UI 事件：方法论变化沿用既有事件与快照刷新；商店搜索/预览为前端临时态。
- **CC-174**: 外部文件写盘 MUST 限定在受管目录内（路径规范化防穿越），单文件与总大小设上限；二进制/超限文件拒绝。
- **CC-175**: 既有教学工具 tab、MCP 工具 tab、方法论屏全部行为不变；既有测试必须继续通过。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **UI** (`frontend/src/`) — SkillListScreen 第三个"技能商店"tab（独立组件 + 独立 store，照 MCP tab 模式）、预览确认弹层、GitHub 输入
- [x] **Desktop API Bridge** (`src/desktop_api/`) — 商店搜索/详情/安装/卸载 typed API
- [x] **Business** (`src/business/`) — 新技能商店业务模块（skills.sh client、GitHub 发现、SKILL.md 解析、安装编排调用既有 SkillService）
- [x] **Data** (`src/data/`) — BrainSkill 来源元数据（migration）+ 受管文件目录管理

### Agent Impact

- Which Agent(s) are affected: Assistant/specialist（方法论池多了外部来源条目，装备/加载语义不变）
- New tools or modified tool handlers? 无新工具；`load_skill_methodology` 输出对 external_import 条目附来源警示框架
- System prompt changes needed? 无
- Orchestrator dispatch changes? 无

### Data Store Impact

- **SQLite**: `brain_skills` 增来源元数据（可空列或伴生表，plan 决定）+ migration（含 downgrade）；写入走既有 `SkillRepository`/`SkillService`
- **Config**: 商店相关上限（文件大小等）用代码内常量起步，不新增配置键（超出需要时再走 UnifiedConfigManager）
- **Secrets**: 无（CC-172）

### Event Impact

- New events: 无（CC-173）

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-440**: 从商店 tab 到看到某技能的完整预览 ≤ 2 次点击；预览必含全文与审计/警示信息。
- **SC-441**: 安装完成的技能 100% 出现在方法论池、可被装备、`load_skill_methodology` 可加载其内容（附来源警示框架）。
- **SC-442**: 安装/预览路径的执行调用次数恒为 0，由守卫测试断言（CC-170）。
- **SC-443**: 公开 GitHub 仓库直装闭环可完成（发现→预览→安装）；无技能仓库得到明确错误。
- **SC-444**: 外部服务不可达时商店 tab 给出可行动错误提示，其余 tab 与屏幕零影响；既有全部测试通过。

## Assumptions

- skills.sh 公开 API（`/api/v1/skills` 系列）匿名可用、限速 600 req/min，足够单用户桌面场景；其详情端点返回完整文件树与内容，安装 skills.sh 来源技能无需访问 GitHub。
- GitHub 直装用匿名 REST API（60 req/hr 限额）——单用户手动安装频率下够用；私有仓库与 token 支持明确留到后续版本（不在本 feature 范围）。
- 技能"更新检测/升级"不在本 feature 范围；重装 = 卸载后再装。
- 附带脚本的实际运行由既有执行体命令管线负责（015 契约），本 feature 只负责"让文件存在于受管目录且可被引用"。
- 外部技能进入方法论池即复用 012 的装备/加载语义，不与教学 Tool（可执行工具表）和 MCP 工具混轨。

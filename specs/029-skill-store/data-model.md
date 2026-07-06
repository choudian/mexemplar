# Data Model: 技能商店

**Date**: 2026-07-06 | **Plan**: [plan.md](plan.md)

## ExternalSkillInstall（新表，v26）

表 `external_skill_installs`，与 `brain_skills` 一对一（来源元数据伴生表，D2）：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `install_id` | TEXT | PK，前缀 `esi_` | 安装记录 id，同时是受管目录名 |
| `skill_id` | TEXT | NOT NULL，UNIQUE | 对应 brain_skills.skill_id（不建 FK，与项目惯例一致） |
| `source_type` | TEXT | NOT NULL，CHECK IN ('skills_sh','github') | 来源类型 |
| `source_ref` | TEXT | NOT NULL | 来源标识：skills.sh 为 `{source}/{slug}`；GitHub 为 `{owner}/{repo}[/{subdir}]` |
| `source_url` | TEXT | NOT NULL | 原始页面/仓库链接（详情 UI 展示） |
| `local_dir` | TEXT | NOT NULL | 受管目录绝对路径（`<data>/external_skills/<install_id>`） |
| `installed_at` | TEXT | NOT NULL | ISO 时间 |
| `uninstalled_at` | TEXT | nullable | 卸载时间；NULL = 活跃安装 |

- 索引：`UNIQUE(skill_id)`；`ix_external_skill_installs_source ON (source_type, source_ref)`（幂等判定查询）。
- "活跃安装" = `uninstalled_at IS NULL`；卸载置时间戳（软记录，保留审计），文件目录物理清理。
- 幂等（FR-443）：同 (source_type, source_ref) 存在活跃安装 → 安装请求直接返回既有记录（advisory 级，单用户场景足够）。

### Migration v26

- upgrade：CREATE TABLE IF NOT EXISTS + 两个索引。
- downgrade：DROP TABLE（文件目录不在 downgrade 中删除——数据文件非 schema）。

## BrainSkill（不改 schema）

- 外部技能落为 `origin='external_import'` 的普通方法论行：name（frontmatter/slug + 冲突后缀）、description、trigger_conditions=[description]、required_tools=[]、body_markdown=SKILL.md 正文。
- 生命周期全部复用既有语义：卸载 = `SkillService` 软删除路径 + 伴生表 `uninstalled_at` + 目录清理。

## 受管文件目录

```text
<get_default_data_dir()>/external_skills/
└── esi_xxxxxxxxxxxx/
    ├── SKILL.md
    └── （附带文件，保持原相对路径）
```

- 写盘约束（CC-174，file_store.py 常量）：单文件 ≤ 512KB；单技能总量 ≤ 2MB；文件数 ≤ 40；相对路径规范化后不得逃出目标目录（拒绝 `..`/绝对路径/盘符）；仅按 UTF-8 文本写入，二进制（解码失败）文件拒绝。
- 原子性（D5）：临时目录写全 → rename；失败逆序清理。

## DTO

- `StoreSkillSummary`：id/name/source/installs/sourceUrl/installed(bool)
- `StoreSkillPreview`：summary + skillMd(全文) + files[{path,size}] + audit（skills.sh：结果或 "unavailable"；github：固定 "unaudited"）
- `InstallResponse`：installId/skillId/name
- `InstalledExternalSkill`：installId/skillId/name/sourceType/sourceRef/sourceUrl/installedAt

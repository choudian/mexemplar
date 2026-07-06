# API Contract: 技能商店

Prefix：`/api/skill-store`（runtime token auth 与全站一致）

## GET /api/skill-store/search?q=&limit=

- q 空 → skills.sh 精选/热门列表；非空 → search 端点。
- 200：`{ "items": [StoreSkillSummary], "sourceAvailable": true }`
- 外部不可达：200 + `{ "items": [], "sourceAvailable": false, "message": "技能市场暂时无法访问，请稍后重试" }`（降级不抛 5xx，商店 tab 展示提示）。
- 每个 item 的 `installed` 按 (source_type, source_ref) 活跃安装计算。

## POST /api/skill-store/discover-github

- Body：`{ "repo": "owner/repo 或 GitHub URL" }`
- 200：`{ "skills": [{ "sourceRef": "owner/repo[/subdir]", "name": "...", "path": "SKILL.md 相对路径" }] }`
- 无 SKILL.md / 仓库不存在：200 + `{ "skills": [], "message": "仓库不存在或不包含技能文件" }`
- 输入非法（解析不出 owner/repo）：422。

## POST /api/skill-store/preview

- Body：`{ "sourceType": "skills_sh"|"github", "sourceRef": "..." }`
- 200：`StoreSkillPreview`（skills.sh 附审计结果或 `audit:"unavailable"`；github 恒 `audit:"unaudited"`）
- 预览零持久化副作用；超限技能（文件数/大小）在此即返回 `{ "installable": false, "reason": "..." }`。

## POST /api/skill-store/install

- Body：同 preview。
- 200：`InstallResponse`；重复安装（活跃）→ 200 返回既有 install（幂等）。
- 名称冲突自动加来源后缀重试一次；仍冲突 → 409。
- 安装动作零执行（CC-170）；失败无半安装残留（FR-443）。

## GET /api/skill-store/installed

- 200：`{ "items": [InstalledExternalSkill] }`（仅活跃安装）。

## POST /api/skill-store/{install_id}/uninstall

- 200：`{ "removed": true }`；方法论软删除 + `uninstalled_at` + 目录清理。
- 不存在/已卸载：404。

## 行为约束（contract 测试断言）

1. search 外部失败 → `sourceAvailable:false` 且不影响其他路由。
2. preview 不产生任何 DB 行或文件。
3. install 后：brain_skills 有 origin=external_import 活跃行、external_skill_installs 有活跃行、受管目录存在且含 SKILL.md；三者原子成对。
4. 重复 install 同 sourceRef → 同 installId，全库行数不增。
5. uninstall 后：方法论软删、目录删除、`installed` 标识翻转。
6. 路径穿越样本（`../x`、绝对路径）→ install 拒绝且零残留。

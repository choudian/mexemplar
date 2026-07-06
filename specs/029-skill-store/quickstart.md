# Quickstart: 技能商店

## 用户视角走查

1. Skill List 屏 → "技能商店" tab。
2. 搜索 "frontend"（或直接浏览精选）→ 点一条 → 预览弹层：SKILL.md 全文 + 文件清单 + 审计结果。
3. 点"安装" → 提示成功；Skill Methodology 屏可见该技能（带来源徽章与链接）。
4. "从 GitHub 安装"输入 `owner/repo` → 选择发现的技能 → 预览（含"未经安全审计"警示）→ 安装。
5. 已安装项在商店里显示"已安装"；在方法论详情可卸载。

## 开发验证命令

```powershell
uv run pytest tests/business/skill_store tests/desktop_api/test_skill_store_endpoint.py tests/data/test_external_skill_install_migration.py tests/guardrails/test_skill_store_guardrails.py -q
cd frontend; npx vitest run tests/unit/skill-store.test.tsx; npm run lint
```

## 关键锚点

- 业务模块：`src/business/skill_store/`（client / discovery / parser / install_service / file_store）
- 安装编排：`install_service.install()` —— 临时目录写全 → rename → SkillService.create → 伴生表
- 零执行守卫：`tests/guardrails/test_skill_store_guardrails.py`
- 警示框架：`skill_methodology_tools.py` 对 external_import 渲染注入来源警示头

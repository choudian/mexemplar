"""Data-owned defaults for the built-in skill methodology bootstrap row."""

BOOTSTRAP_HOW_TO_SKILL_ID = "bootstrap.how_to_create_skill_methodology"
DEFAULT_SEED_FILE_PATH = "src/business/brain/seed/how_to_create_skill_methodology.md"
BOOTSTRAP_NAME = "如何创建方法论"
BOOTSTRAP_DESCRIPTION = "调用 create_skill_methodology 工具时的参数填写指引与判重义务"
BOOTSTRAP_TRIGGERS = [
    "assistant 准备调用 create_skill_methodology 工具产出新方法论时",
    "受授权 specialist 准备调用 create_skill_methodology 工具时",
]
BOOTSTRAP_REQUIRED_TOOLS = ["create_skill_methodology"]
FALLBACK_BODY = """# 如何创建方法论（系统应急 fallback）

该方法论的 seed 文件未能正确加载，当前为系统应急 fallback 版本。
请联系开发者修复 seed 文件，或在 SkillScreen 上手动编辑此方法论以恢复完整指引。

最低限度的判重义务：调用 create_skill_methodology 之前，先扫描你 system prompt 里的方法论装备清单。
如果发现名称或触发场景与已有方法论高度重合，必须先在对话里与用户对齐要不要合并或择一，再决定是否产出新方法论。
"""

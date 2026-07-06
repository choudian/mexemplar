"""SKILL.md 极简解析（029 D4）。

Agent Skills 标准 frontmatter 只有 name/description 两个必填字段；这里做
零依赖的 `---` 包围 `key: value` 行解析，其余 frontmatter 键忽略。缺字段
按 spec 边缘用例回退：缺 name → slug，缺 description → 正文首个非空段截断。
"""

from __future__ import annotations

from dataclasses import dataclass

_DESCRIPTION_FALLBACK_LIMIT = 200


@dataclass(frozen=True)
class ParsedSkillMd:
    name: str
    description: str
    body: str


def parse_skill_md(content: str, *, fallback_slug: str) -> ParsedSkillMd:
    """解析 SKILL.md 内容为 (name, description, body)。

    Args:
        content: SKILL.md 原文。
        fallback_slug: frontmatter 缺 name 时的回退名称（通常是技能 slug）。
    """
    frontmatter, body = _split_frontmatter(content)
    name = (frontmatter.get("name") or "").strip() or fallback_slug
    description = (frontmatter.get("description") or "").strip()
    if not description:
        description = _first_paragraph(body)[:_DESCRIPTION_FALLBACK_LIMIT] or name
    return ParsedSkillMd(name=name, description=description, body=body.strip())


def _split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content
    fields: dict[str, str] = {}
    for index in range(1, len(lines)):
        stripped = lines[index].strip()
        if stripped == "---":
            body = "\n".join(lines[index + 1 :])
            return fields, body
        if ":" in stripped and not stripped.startswith("#"):
            key, _, value = stripped.partition(":")
            fields[key.strip().lower()] = value.strip()
    # 没有闭合分隔线：视为无 frontmatter
    return {}, content


def _first_paragraph(body: str) -> str:
    for block in body.split("\n\n"):
        cleaned = " ".join(line.strip() for line in block.splitlines() if line.strip()).strip()
        cleaned = cleaned.lstrip("#").strip()
        if cleaned:
            return cleaned
    return ""

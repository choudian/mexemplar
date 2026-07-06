"""skill_md_parser 行为测试（029 T006）。"""

from __future__ import annotations

from src.business.skill_store.skill_md_parser import parse_skill_md

_FULL = """---
name: frontend-design
description: Distinctive visual design guidance for new UI
---

# Frontend Design

Approach this as the design lead at a small studio.
"""

_NO_NAME = """---
description: Only description here
---

Body text.
"""

_NO_FRONTMATTER = """# My Skill

This skill teaches something useful for daily work.

More details below.
"""


def test_full_frontmatter():
    parsed = parse_skill_md(_FULL, fallback_slug="fallback")
    assert parsed.name == "frontend-design"
    assert parsed.description == "Distinctive visual design guidance for new UI"
    assert parsed.body.startswith("# Frontend Design")


def test_missing_name_falls_back_to_slug():
    parsed = parse_skill_md(_NO_NAME, fallback_slug="my-slug")
    assert parsed.name == "my-slug"
    assert parsed.description == "Only description here"


def test_no_frontmatter_falls_back_to_first_paragraph():
    parsed = parse_skill_md(_NO_FRONTMATTER, fallback_slug="raw-skill")
    assert parsed.name == "raw-skill"
    assert parsed.description.startswith("My Skill")
    assert parsed.body.startswith("# My Skill")


def test_unclosed_frontmatter_treated_as_body():
    content = "---\nname: broken\nno closing fence\n\nParagraph here."
    parsed = parse_skill_md(content, fallback_slug="broken-slug")
    assert parsed.name == "broken-slug"
    assert "Paragraph here" in parsed.body


def test_description_fallback_truncated_to_200():
    long_paragraph = "字" * 500
    parsed = parse_skill_md(f"body:\n\n{long_paragraph}", fallback_slug="s")
    assert len(parsed.description) <= 200

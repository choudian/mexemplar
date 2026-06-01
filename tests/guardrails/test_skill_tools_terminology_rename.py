from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_backend_public_events_use_tools_changed_and_skill_methodology_events():
    events_source = _read("src/utils/events.py")
    ui_events_source = _read("src/desktop_api/ui_events.py")

    assert "skills_changed" not in events_source
    assert "tools_changed" in events_source
    assert '"skills.changed"' not in ui_events_source
    assert '"tools.changed"' in ui_events_source
    assert '"skill.changed"' in ui_events_source
    assert '"skill.equipment.changed"' in ui_events_source


def test_source_emit_call_sites_do_not_publish_legacy_skills_changed():
    checked_roots = [ROOT / "src", ROOT / "frontend" / "src"]
    offenders: list[str] = []
    for base in checked_roots:
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in {".py", ".ts", ".tsx"}:
                text = path.read_text(encoding="utf-8")
                if "skills.changed" in text or "skills_changed" in text:
                    offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_legacy_skill_routes_redirect_to_tool_routes():
    routes_source = _read("frontend/src/app/routes.tsx")

    assert 'teaching: "/tools/teaching"' in routes_source
    assert 'skills: "/tools/list"' in routes_source
    assert 'compositions: "/tools/compositions"' in routes_source
    assert '"skill-methodology": "/skills/methodology"' in routes_source
    assert 'pathname === "/skills"' in routes_source
    assert '"/tools/list"' in routes_source
    assert 'pathname.startsWith("/skills/teaching")' in routes_source
    assert '"/tools/teaching"' in routes_source
    assert 'pathname.startsWith("/skills/compositions")' in routes_source
    assert '"/tools/compositions"' in routes_source
    # catch-all: any /skills/* not /skills/methodology must redirect to /tools/list
    assert 'startsWith("/skills/") && !pathname.startsWith("/skills/methodology")' in routes_source


def test_skill_methodology_navrail_label():
    routes_source = _read("frontend/src/app/routes.tsx")
    # plan.md §与现有屏幕的关系: label "方法论 / Skill", shortLabel "方法论"
    assert '"方法论 / Skill"' in routes_source
    assert '"方法论"' in routes_source


def test_methodology_screen_does_not_reuse_old_tool_screen_skill_terms():
    methodology_dir = ROOT / "frontend" / "src" / "screens" / "SkillMethodologyScreen"
    forbidden = ["Skill Teaching", "Skill List", "Skill Composition"]
    offenders: list[str] = []
    for path in methodology_dir.rglob("*"):
        if path.is_file() and path.suffix in {".ts", ".tsx"}:
            text = path.read_text(encoding="utf-8")
            for term in forbidden:
                if term in text:
                    offenders.append(f"{path.relative_to(ROOT)}:{term}")

    assert offenders == []

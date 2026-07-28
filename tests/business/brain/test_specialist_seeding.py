"""Built-in specialists ship with the install and stay current — unless edited.

Three rules, and the third is what makes the other two safe:
  1. missing → create
  2. untouched → upgrade to the latest definition
  3. edited by the user → never touched again

Without (2) a prompt fix only reaches people who reinstall. Without (3) every
restart would silently undo the user's own edits.
"""

from __future__ import annotations

import json

import pytest

from src.business.brain.specialist_presets import (
    CODING_EXECUTOR,
    compute_fingerprint,
    load_specialist_presets,
)
from src.business.brain.specialist_service import SpecialistService
from src.business.services.skill_composition.builtin_compositions import (
    EXTERNAL_CODING_COMPOSITION_ID,
)


class _Row:
    def __init__(self, **kwargs):
        self.specialist_id = kwargs.get("specialist_id", "spec_1")
        self.name = kwargs.get("name", CODING_EXECUTOR.name)
        self.description = kwargs.get("description", "")
        self.role_definition = kwargs.get("role_definition", "")
        self.composition_ids = kwargs.get("composition_ids", "[]")
        self.preset_key = kwargs.get("preset_key")
        self.preset_fingerprint = kwargs.get("preset_fingerprint")
        self.is_active = kwargs.get("is_active", True)


class _FakeRepo:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.updates: list[dict] = []
        self.marks: list[tuple] = []

    def get_specialist_by_preset_key(self, preset_key):
        return next((r for r in self.rows if r.preset_key == preset_key), None)

    def get_specialist_by_name(self, name):
        return next((r for r in self.rows if r.name == name and r.is_active), None)

    def update_specialist(self, specialist_id, **kwargs):
        self.updates.append({"specialist_id": specialist_id, **kwargs})
        row = next(r for r in self.rows if r.specialist_id == specialist_id)
        if kwargs.get("role_definition") is not None:
            row.role_definition = kwargs["role_definition"]
        if kwargs.get("description") is not None:
            row.description = kwargs["description"]
        return True

    def mark_as_preset(self, specialist_id, preset_key, fingerprint, commit=True):
        self.marks.append((specialist_id, preset_key, fingerprint))
        row = next((r for r in self.rows if r.specialist_id == specialist_id), None)
        if row is not None:
            row.preset_key = preset_key
            row.preset_fingerprint = fingerprint
        return True


class _Service(SpecialistService):
    def __init__(self, repo):
        self._repo = repo
        self.created: list[dict] = []

    def create_specialist(self, **kwargs):
        self.created.append(kwargs)
        row = _Row(
            specialist_id="spec_new",
            name=kwargs["name"],
            description=kwargs["description"],
            role_definition=kwargs["role_definition"],
            composition_ids=str(kwargs.get("composition_ids", [])).replace("'", '"'),
        )
        self._repo.rows.append(row)
        return {"specialist_id": "spec_new", "name": kwargs["name"]}


def _seeded_row(**overrides):
    """A row exactly as the seeder would have written it."""
    defaults = {
        "specialist_id": "spec_1",
        "name": CODING_EXECUTOR.name,
        "description": CODING_EXECUTOR.description,
        "role_definition": CODING_EXECUTOR.load_role_definition(),
        "composition_ids": f'["{EXTERNAL_CODING_COMPOSITION_ID}"]',
        "preset_key": CODING_EXECUTOR.key,
        "preset_fingerprint": CODING_EXECUTOR.fingerprint(),
    }
    defaults.update(overrides)
    return _Row(**defaults)


def _other_presets_already_seeded(subject_key):
    """其余内置专员都已按种子写入。

    单个 preset 的三条规则各自成立，但 seed_builtin_specialists 会遍历全部——
    不预置其余的，被测断言（"没有新建""没有更新"）会被别的 preset 的正常种子
    动作污染。
    """
    return [
        _Row(
            specialist_id=f"spec_{preset.key}",
            name=preset.name,
            description=preset.description,
            role_definition=preset.load_role_definition(),
            composition_ids=json.dumps(preset.composition_ids),
            preset_key=preset.key,
            preset_fingerprint=preset.fingerprint(),
        )
        for preset in load_specialist_presets()
        if preset.key != subject_key
    ]


def _repo_with(subject_row):
    """被测 preset 用给定行，其余 preset 保持已就绪。"""
    return _FakeRepo([subject_row] + _other_presets_already_seeded(CODING_EXECUTOR.key))


# --- 规则 1：缺了就建 ---------------------------------------------------------


def test_fresh_install_creates_every_preset():
    service = _Service(_FakeRepo())

    service.seed_builtin_specialists()

    assert {c["name"] for c in service.created} == {
        p.name for p in load_specialist_presets()
    }


def test_created_specialist_is_tagged_so_it_can_be_upgraded_later():
    repo = _FakeRepo()
    service = _Service(repo)

    service.seed_builtin_specialists()

    assert repo.marks
    _sid, key, fingerprint = repo.marks[0]
    assert key == CODING_EXECUTOR.key
    assert fingerprint == CODING_EXECUTOR.fingerprint()


def test_created_specialist_carries_composition_and_role():
    service = _Service(_FakeRepo())

    service.seed_builtin_specialists()

    call = service.created[0]
    assert call["composition_ids"] == [EXTERNAL_CODING_COMPOSITION_ID]
    assert call["role_kind"] == "executor"
    assert "两种已知的失败模式" in call["role_definition"]


# --- 规则 2：没改过就升级 -----------------------------------------------------


def test_untouched_specialist_is_upgraded_when_the_preset_changes():
    stale = _seeded_row(
        role_definition="旧版定义",
        preset_fingerprint=compute_fingerprint(
            role_definition="旧版定义",
            description=CODING_EXECUTOR.description,
            composition_ids=[EXTERNAL_CODING_COMPOSITION_ID],
        ),
    )
    repo = _repo_with(stale)
    service = _Service(repo)

    service.seed_builtin_specialists()

    assert len(repo.updates) == 1
    assert "两种已知的失败模式" in repo.updates[0]["role_definition"]
    assert service.created == []


def test_upgrade_refreshes_the_fingerprint_so_it_settles():
    stale = _seeded_row(
        role_definition="旧版定义",
        preset_fingerprint=compute_fingerprint(
            role_definition="旧版定义",
            description=CODING_EXECUTOR.description,
            composition_ids=[EXTERNAL_CODING_COMPOSITION_ID],
        ),
    )
    repo = _repo_with(stale)
    service = _Service(repo)

    service.seed_builtin_specialists()
    first = len(repo.updates)
    service.seed_builtin_specialists()

    # A second startup must be a no-op, not a repeated write.
    assert len(repo.updates) == first


def test_already_current_specialist_is_not_rewritten():
    repo = _repo_with(_seeded_row())
    service = _Service(repo)

    service.seed_builtin_specialists()

    assert repo.updates == []
    assert service.created == []


# --- 规则 3：改过就不动 -------------------------------------------------------


def test_user_edited_role_definition_is_never_overwritten():
    edited = _seeded_row(role_definition="我自己写的角色定义")
    repo = _repo_with(edited)
    service = _Service(repo)

    service.seed_builtin_specialists()

    assert repo.updates == []
    assert edited.role_definition == "我自己写的角色定义"


def test_user_edited_compositions_also_count_as_touched():
    # Fingerprinting only the role text would let a composition change be
    # silently reverted on the next upgrade.
    edited = _seeded_row(composition_ids='["comp_something_else"]')
    repo = _repo_with(edited)
    service = _Service(repo)

    service.seed_builtin_specialists()

    assert repo.updates == []


def test_deactivated_preset_is_not_recreated():
    repo = _repo_with(_seeded_row(is_active=False))
    service = _Service(repo)

    service.seed_builtin_specialists()

    assert service.created == []


# --- 认领既有同名专员 ---------------------------------------------------------


def test_untagged_specialist_matching_the_preset_is_adopted_and_kept_current():
    # Created by hand before tagging existed; its content matches the preset,
    # so it should be adopted and continue receiving upgrades.
    legacy = _Row(
        specialist_id="spec_legacy",
        name=CODING_EXECUTOR.name,
        description=CODING_EXECUTOR.description,
        role_definition=CODING_EXECUTOR.load_role_definition(),
        composition_ids=f'["{EXTERNAL_CODING_COMPOSITION_ID}"]',
    )
    repo = _repo_with(legacy)
    service = _Service(repo)

    service.seed_builtin_specialists()

    assert legacy.preset_key == CODING_EXECUTOR.key
    assert legacy.preset_fingerprint == CODING_EXECUTOR.fingerprint()
    assert service.created == []


def test_unrelated_specialist_with_the_same_name_is_left_to_the_user():
    mine = _Row(
        specialist_id="spec_mine",
        name=CODING_EXECUTOR.name,
        description="我自己建的",
        role_definition="完全不同的定义",
    )
    repo = _FakeRepo([mine])
    service = _Service(repo)

    service.seed_builtin_specialists()

    # Adopted for identity, but its fingerprint records *its* content, so it
    # reads as user-owned and is never overwritten.
    assert mine.preset_key == CODING_EXECUTOR.key
    assert mine.role_definition == "完全不同的定义"
    assert repo.updates == []


# --- 韧性 --------------------------------------------------------------------


def test_a_failing_preset_does_not_abort_startup():
    class _Boom(_FakeRepo):
        def get_specialist_by_preset_key(self, preset_key):
            raise RuntimeError("db down")

    service = _Service(_Boom())

    service.seed_builtin_specialists()  # must not raise


def test_preset_fingerprint_is_stable_across_calls():
    assert CODING_EXECUTOR.fingerprint() == CODING_EXECUTOR.fingerprint()


@pytest.mark.parametrize("preset", load_specialist_presets())
def test_every_preset_has_a_readable_seed_file(preset):
    assert preset.load_role_definition().strip()
    assert preset.key


# --- planner 纳入种子体系（024 DEC-B 修订 2026-07-27）-------------------------


def _planner_preset():
    return next(p for p in load_specialist_presets() if p.key == "planner")


def test_planner_is_a_preset_so_its_prompt_can_be_upgraded():
    """planner 必须在种子体系内。

    024 originally registered it through ensure_planner_specialist alone, which
    creates and never syncs -- so a prompt improvement reached only fresh
    installs, and every existing planner kept planning with the definition it
    was born with.
    """
    planner = _planner_preset()
    assert planner.role_kind == "planner"
    assert "第二步：探索现状" in planner.load_role_definition()


def test_legacy_untagged_planner_is_adopted_then_upgraded():
    """7/25 那个手工注册的 planner：先被认领，再在下一轮启动升级到当前定义。"""
    planner = _planner_preset()
    legacy = _Row(
        specialist_id="spec_planner_legacy",
        name=planner.name,
        description="复杂任务分解专员：将超阈值复杂任务分解为带依赖的 DAG 任务图，交由调度器按序执行。只规划不执行。",
        role_definition=(
            "你是规划专员。你的唯一职责是将复杂任务分解为一张带依赖关系的任务图（DAG）。"
            "你只输出任务图，不执行任何具体操作。"
        ),
        composition_ids="[]",
    )
    repo = _FakeRepo([legacy] + _other_presets_already_seeded(planner.key))
    service = _Service(repo)

    # 第一轮：认领，记下归属与当前内容指纹，本轮不改内容
    service.seed_builtin_specialists()
    assert legacy.preset_key == planner.key
    assert service.created == []
    assert repo.updates == []

    # 第二轮：内容仍等于认领时的指纹 → 判定未被用户改过 → 升级到四段式
    service.seed_builtin_specialists()
    assert len(repo.updates) == 1
    assert "第二步：探索现状" in repo.updates[0]["role_definition"]


def test_user_edited_planner_is_left_alone():
    """用户自己改过 planner 提示词的，升级不得覆盖。"""
    planner = _planner_preset()
    edited = _Row(
        specialist_id="spec_planner_mine",
        name=planner.name,
        description=planner.description,
        role_definition="我自己写的规划流程",
        composition_ids="[]",
        preset_key=planner.key,
        preset_fingerprint=compute_fingerprint(
            role_definition="别的内容",
            description=planner.description,
            composition_ids=[],
        ),
    )
    repo = _FakeRepo([edited] + _other_presets_already_seeded(planner.key))
    service = _Service(repo)

    service.seed_builtin_specialists()

    assert repo.updates == []
    assert edited.role_definition == "我自己写的规划流程"

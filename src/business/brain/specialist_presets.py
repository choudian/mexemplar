"""Built-in specialists seeded on startup.

A fresh install must arrive with the specialists needed to use the product's
built-in capability compositions — otherwise "外部 Coding" ships as eleven tools
nobody can reach, since only a fixed executor specialist configured with that
composition may activate them.

Seeding follows the same rule as the MCP presets (N19): upsert what is missing,
never overwrite what the user has since edited. Role definitions live in
``seed/*.md`` rather than inline strings so they can be reviewed as prose.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from src.business.services.skill_composition.builtin_compositions import (
    EXTERNAL_CODING_COMPOSITION_ID,
)

logger = logging.getLogger(__name__)

_SEED_DIR = Path(__file__).parent / "seed"


def compute_fingerprint(
    *, role_definition: str, description: str, composition_ids: list[str]
) -> str:
    """种子内容的摘要，用于判断用户此后有没有改过。

    覆盖种子会写入的每个字段：只比对角色定义的话，用户改了能力组合就会被
    当成"未改动"而在升级时被覆盖掉。
    """
    payload = json.dumps(
        {
            "role_definition": role_definition.strip(),
            "description": description.strip(),
            "composition_ids": sorted(composition_ids),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SpecialistPreset:
    """One built-in specialist.

    ``key`` is the stable identity: the user may rename the specialist and the
    seeder must still recognise it as the same one rather than creating a second.
    """

    key: str
    name: str
    description: str
    role_definition_file: str
    reason: str
    role_kind: str = "executor"
    composition_ids: list[str] = field(default_factory=list)
    tool_whitelist: list[str] = field(default_factory=list)

    def load_role_definition(self) -> str:
        path = _SEED_DIR / self.role_definition_file
        return path.read_text(encoding="utf-8").strip()

    def fingerprint(self) -> str:
        return compute_fingerprint(
            role_definition=self.load_role_definition(),
            description=self.description,
            composition_ids=list(self.composition_ids),
        )


CODING_EXECUTOR = SpecialistPreset(
    key="coding_executor",
    name="编码执行专员",
    description="把开发任务交给外部 coding CLI 执行，并对交付结果做独立核查——不轻信外部 agent 的自述",
    role_definition_file="coding_executor_specialist.md",
    reason="内置专员：外部 Coding 能力组合的唯一合法执行者",
    role_kind="executor",
    composition_ids=[EXTERNAL_CODING_COMPOSITION_ID],
)


def load_specialist_presets() -> list[SpecialistPreset]:
    return [CODING_EXECUTOR]

import pytest

from src.business.brain.models import Zone
from src.data.helpers import build_like_pattern
from src.data.repos.brain_repository import BrainRepository


def test_search_archive_entries_treats_like_wildcards_as_literals(in_memory_db):
    repo = BrainRepository()
    literal = repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="预算字段包含 %important 标记",
        origin="distillation",
        reason="literal percent",
    )
    repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="完全无关的历史条目",
        origin="distillation",
        reason="unrelated",
    )

    results = repo.search_archive_entries("%important")

    assert [entry.entry_id for entry in results] == [literal]


def test_search_entries_treats_underscore_as_literal(in_memory_db):
    repo = BrainRepository()
    literal = repo.create_entry(
        zone=Zone.PERSISTENT.value,
        content="用户偏好 a_b 命名格式",
        origin="distillation",
        reason="literal underscore",
    )
    repo.create_entry(
        zone=Zone.PERSISTENT.value,
        content="用户偏好 axb 命名格式",
        origin="distillation",
        reason="wildcard decoy",
    )

    results = repo.search_entries(Zone.PERSISTENT.value, "a_b")

    assert [entry.entry_id for entry in results] == [literal]


def test_build_like_pattern_rejects_empty_keyword():
    with pytest.raises(ValueError, match="term"):
        build_like_pattern("")

"""Archive layering service tests."""

from src.business.brain.archive_service import ArchiveService
from src.business.brain.models import Zone
from src.data.repos.brain_repository import BrainRepository


def test_archive_layering_job_does_not_duplicate_day_summaries(in_memory_db):
    repo = BrainRepository()
    repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="用户完成了季度预算复盘，并记录了多个部门的成本变化和后续跟进行动。",
        origin="distillation",
        reason="归档单元",
    )
    repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="用户确认下周继续追踪预算异常项，并要求后续输出保持简洁。",
        origin="distillation",
        reason="归档单元",
    )

    service = ArchiveService(brain_repo=repo)
    first = service.run_layering_job()
    second = service.run_layering_job()

    summaries = [
        entry
        for entry in repo.get_entries_by_zone(Zone.ARCHIVE.value, status="active", limit=1000)
        if entry.origin == "archive_layering" and entry.scope == "day"
    ]
    assert first["day_layers_created"] == 1
    assert second["day_layers_created"] == 0
    assert len(summaries) == 1


def test_archive_layering_creates_time_and_theme_rollups(in_memory_db):
    repo = BrainRepository()
    repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="预算主题第一段，包含足够长的内容用于归档聚合。",
        origin="distillation",
        reason="归档单元",
        scope="预算",
    )
    repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="预算主题第二段，继续记录预算审核过程和后续动作。",
        origin="distillation",
        reason="归档单元",
        scope="预算",
    )
    repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="用户完成了季度预算复盘，并记录了多个部门的成本变化和后续跟进行动。",
        origin="distillation",
        reason="归档单元",
    )
    repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="用户确认下周继续追踪预算异常项，并要求后续输出保持简洁。",
        origin="distillation",
        reason="归档单元",
    )

    stats = ArchiveService(brain_repo=repo).run_layering_job()
    entries = repo.get_entries_by_zone(Zone.ARCHIVE.value, status="active", limit=1000)
    scopes = {entry.scope for entry in entries if entry.origin == "archive_layering"}

    assert stats["day_layers_created"] == 1
    assert stats["week_layers_created"] == 1
    assert stats["month_layers_created"] == 1
    assert stats["year_layers_created"] == 1
    assert stats["theme_layers_created"] == 1
    assert {"day", "week", "month", "year", "theme"}.issubset(scopes)

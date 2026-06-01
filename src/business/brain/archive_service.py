"""
Archive Service - 归档区时间分层聚合

负责将 unit 级别的归档条目聚合为 day/week/month 级别的摘要。
"""

import logging
from collections import defaultdict
from datetime import date, datetime

from src.utils.events import emit

logger = logging.getLogger(__name__)


class ArchiveService:
    """归档区时间分层聚合服务"""

    def __init__(self, brain_repo=None, config=None):
        self._repo = brain_repo
        self._config = config

    def _get_repo(self):
        if self._repo is None:
            from src.data.repos.brain_repository import BrainRepository

            self._repo = BrainRepository()
        return self._repo

    def run_layering_job(self) -> dict:
        """执行一轮归档分层聚合。

        将归档区中未分层的 unit 条目按时间聚合为 day 层摘要。

        Returns:
            统计信息 dict
        """
        repo = self._get_repo()
        stats = {
            "unit_entries_scanned": 0,
            "day_layers_created": 0,
            "week_layers_created": 0,
            "month_layers_created": 0,
            "year_layers_created": 0,
            "theme_layers_created": 0,
        }

        entries = repo.get_entries_by_zone("archive", status="active", limit=1000)
        existing_day_layers = {
            self._layer_key(entry, "Day-layer aggregation for ")
            for entry in entries
            if getattr(entry, "origin", "") == "archive_layering"
            and getattr(entry, "scope", None) == "day"
        }
        existing_day_layers.discard(None)
        grouped: dict[str, list] = defaultdict(list)
        for entry in entries:
            if getattr(entry, "scope", None) is not None:
                continue
            created_at = getattr(entry, "created_at", None)
            entry_date = created_at.date().isoformat() if created_at else "unknown"
            grouped[entry_date].append(entry)

        for entry_date, day_entries in grouped.items():
            if entry_date in existing_day_layers:
                continue
            if len(day_entries) <= 1:
                continue
            combined_content = " || ".join(getattr(entry, "content", "") for entry in day_entries)
            if len(combined_content) <= 50:
                continue
            self._create_layer_summary(
                repo,
                layer_scope="day",
                key=entry_date,
                combined_content=combined_content,
                entry_count=len(day_entries),
            )
            stats["day_layers_created"] += 1
            stats["unit_entries_scanned"] += len(day_entries)

        entries = repo.get_entries_by_zone("archive", status="active", limit=1000)
        self._create_time_rollups(repo, entries, "week", stats)
        entries = repo.get_entries_by_zone("archive", status="active", limit=1000)
        self._create_time_rollups(repo, entries, "month", stats)
        entries = repo.get_entries_by_zone("archive", status="active", limit=1000)
        self._create_time_rollups(repo, entries, "year", stats)
        entries = repo.get_entries_by_zone("archive", status="active", limit=1000)
        self._create_theme_rollups(repo, entries, stats)

        logger.info(
            "Archive layering job completed: scanned=%d, day=%d, week=%d, month=%d, year=%d, theme=%d",
            stats["unit_entries_scanned"],
            stats["day_layers_created"],
            stats["week_layers_created"],
            stats["month_layers_created"],
            stats["year_layers_created"],
            stats["theme_layers_created"],
        )
        return stats

    def _create_time_rollups(self, repo, entries: list, layer_scope: str, stats: dict) -> None:
        source_scope = {
            "week": "day",
            "month": "week",
            "year": "month",
        }[layer_scope]
        existing = {
            self._layer_key(entry, f"{layer_scope.capitalize()}-layer aggregation for ")
            for entry in entries
            if getattr(entry, "origin", "") == "archive_layering"
            and getattr(entry, "scope", None) == layer_scope
        }
        existing.discard(None)
        grouped: dict[str, list] = defaultdict(list)
        for entry in entries:
            if getattr(entry, "origin", "") != "archive_layering":
                continue
            if getattr(entry, "scope", None) != source_scope:
                continue
            source_key = self._layer_key(
                entry,
                f"{source_scope.capitalize()}-layer aggregation for ",
            )
            rollup_key = self._rollup_key(source_key, layer_scope)
            if rollup_key:
                grouped[rollup_key].append(entry)

        stat_key = f"{layer_scope}_layers_created"
        for key, layer_entries in grouped.items():
            if key in existing:
                continue
            combined_content = " || ".join(getattr(entry, "content", "") for entry in layer_entries)
            if not combined_content.strip():
                continue
            self._create_layer_summary(
                repo,
                layer_scope=layer_scope,
                key=key,
                combined_content=combined_content,
                entry_count=len(layer_entries),
            )
            stats[stat_key] += 1

    def _create_theme_rollups(self, repo, entries: list, stats: dict) -> None:
        existing = {
            self._layer_key(entry, "Theme-layer aggregation for ")
            for entry in entries
            if getattr(entry, "origin", "") == "archive_layering"
            and getattr(entry, "scope", None) == "theme"
        }
        existing.discard(None)
        grouped: dict[str, list] = defaultdict(list)
        reserved_scopes = {"day", "week", "month", "year", "theme"}
        for entry in entries:
            scope = str(getattr(entry, "scope", "") or "").strip()
            if not scope or scope in reserved_scopes:
                continue
            if getattr(entry, "origin", "") == "archive_layering":
                continue
            grouped[scope].append(entry)

        for theme, theme_entries in grouped.items():
            if theme in existing or len(theme_entries) <= 1:
                continue
            combined_content = " || ".join(getattr(entry, "content", "") for entry in theme_entries)
            if not combined_content.strip():
                continue
            self._create_layer_summary(
                repo,
                layer_scope="theme",
                key=theme,
                combined_content=combined_content,
                entry_count=len(theme_entries),
            )
            stats["theme_layers_created"] += 1

    def _create_layer_summary(
        self,
        repo,
        layer_scope: str,
        key: str,
        combined_content: str,
        entry_count: int,
    ) -> None:
        """创建一个归档层级摘要。"""
        summary_text = combined_content[:500] if combined_content else ""
        label = layer_scope.capitalize()
        entry_id = repo.create_entry(
            zone="archive",
            content=summary_text,
            origin="archive_layering",
            reason=f"{label}-layer aggregation for {key} ({entry_count} entries)",
            scope=layer_scope,
        )
        emit("brain_zone_changed", zone="archive", entry_id=str(entry_id), operation="create")

    @staticmethod
    def _layer_key(entry, prefix: str) -> str | None:
        reason = str(getattr(entry, "reason", "") or "")
        if not reason.startswith(prefix):
            return None
        rest = reason[len(prefix) :]
        paren = rest.rfind(" (")
        return rest[:paren] if paren > 0 else rest

    @staticmethod
    def _rollup_key(source_key: str | None, target_scope: str) -> str | None:
        if not source_key:
            return None
        try:
            if target_scope == "week":
                day = date.fromisoformat(source_key)
                iso = day.isocalendar()
                return f"{iso.year}-W{iso.week:02d}"
            if target_scope == "month":
                if "-W" in source_key:
                    year, week = source_key.split("-W", 1)
                    monday = datetime.strptime(f"{year} {int(week)} 1", "%G %V %u").date()
                    return monday.strftime("%Y-%m")
                return source_key[:7]
            if target_scope == "year":
                return source_key[:4]
        except (TypeError, ValueError):
            return None
        return None

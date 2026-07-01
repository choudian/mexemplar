"""Narrow brain facades used by assistant built-in tools."""

from __future__ import annotations

from typing import Iterable

from src.business.brain.context_builder import BrainContextBuilder
from src.business.brain.retrieval_service import RetrievalService
from src.business.brain.skill_reference_counter import SkillReferenceCounterService
from src.business.brain.specialist_service import SpecialistService
from src.data.repos.brain_repository import BrainRepository
from src.data.repos.skill_repository import SkillRepository


class AssistantMemoryToolFacade:
    """Brain memory actions exposed to assistant tools."""

    def retrieve_archive(self, query: str) -> list[dict]:
        return RetrievalService().retrieve_archive(query)

    def retrieve_failure_zone(self, context: str) -> list[dict]:
        return RetrievalService().retrieve_failure_zone(context)

    def context_entry_ids_for_session(
        self,
        session_id: str | None,
        retrieved_entry_ids: Iterable[str] = (),
    ) -> list[str] | None:
        if not session_id:
            return None
        context = BrainContextBuilder().build_context(session_id, track_loaded=False)
        entry_ids = set(context.injected_entry_ids)
        entry_ids.update(
            str(entry_id).strip() for entry_id in retrieved_entry_ids if str(entry_id).strip()
        )
        return list(entry_ids)

    def invalidate_memory_entry(
        self,
        entry_id: str,
        reason: str,
        *,
        current_context_entry_ids: list[str] | None,
    ) -> dict:
        with BrainRepository() as repo:
            service = RetrievalService(brain_repo=repo)
            return service.invalidate_memory_entry(
                entry_id,
                reason,
                current_context_entry_ids=current_context_entry_ids,
            )

    def record_memory_references(self, entry_ids: list[str]) -> None:
        if not entry_ids:
            return
        with BrainRepository() as repo:
            repo.batch_update_referenced_counts(entry_ids)

    def record_skill_references(self, skill_ids: list[str]) -> None:
        if not skill_ids:
            return
        with SkillRepository() as skill_repo:
            SkillReferenceCounterService(repo=skill_repo).process_reply_metadata(skill_ids)


class AssistantSpecialistToolFacade:
    """Specialist management actions exposed to assistant tools."""

    def create_from_conversation(
        self,
        *,
        session_id: str,
        name: str,
        description: str,
        role_definition: str,
        tool_whitelist: list[str],
    ) -> dict:
        return SpecialistService().create_specialist(
            name=name,
            description=description,
            role_definition=role_definition,
            tool_whitelist=tool_whitelist,
            origin="user_conversation",
            reason=f"由用户在会话 {session_id[:8]}... 中创建",
        )

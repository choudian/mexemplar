"""Repository for persistent built-in tool output references."""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_

from src.business.agents.tools.builtin_permissions import workspace_hash
from src.data.models_sqlite import ToolOutputReference as ToolOutputReferenceModel
from src.data.repos.base_repository import BaseRepository
from src.utils.helpers import get_default_data_dir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedToolOutput:
    model: ToolOutputReferenceModel
    data: bytes


class ToolOutputRepository(BaseRepository):
    """SQLite metadata plus private filesystem blobs for raw tool output."""

    storage_root_kind = "app_data_tool_outputs"

    def __init__(self, session=None, storage_root: Path | None = None):
        super().__init__(session=session)
        self.storage_root = Path(storage_root or get_default_data_dir() / "tool_outputs")
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def create_reference(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_call_id: str | None,
        kind: str,
        data: str | bytes,
        workspace_root: str | Path | None,
        content_type: str = "text/plain",
        retention_days: int = 14,
        redaction_profile: str | None = None,
    ) -> ToolOutputReferenceModel:
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        reference_id = f"out_{uuid.uuid4().hex}"
        digest = hashlib.sha256(raw).hexdigest()
        storage_key = f"{reference_id[:8]}/{reference_id}.blob"
        temp_path = self.storage_root / f"{reference_id}.tmp"
        final_path = self.storage_root / storage_key
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            days=max(1, int(retention_days))
        )
        model = ToolOutputReferenceModel(
            reference_id=reference_id,
            kind=kind,
            tool_name=tool_name,
            session_id=session_id,
            tool_call_id=tool_call_id,
            storage_key=storage_key,
            storage_root_kind=self.storage_root_kind,
            size_bytes=len(raw),
            content_type=content_type,
            sha256=digest,
            redaction_profile=redaction_profile,
            status="active",
            owner_workspace_hash=workspace_hash(workspace_root),
            expires_at=expires_at,
        )
        try:
            temp_path.write_bytes(raw)
            if os.name != "nt":
                temp_path.chmod(0o600)
            if hashlib.sha256(temp_path.read_bytes()).hexdigest() != digest:
                raise RuntimeError("tool_output_digest_mismatch")
            final_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_path, final_path)
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
            return model
        except Exception:
            self.session.rollback()
            for path in (temp_path, final_path):
                try:
                    if path.exists():
                        path.unlink()
                except OSError:
                    pass
            raise

    def get_by_reference_id(self, reference_id: str) -> ToolOutputReferenceModel | None:
        return (
            self.session.query(ToolOutputReferenceModel)
            .filter(ToolOutputReferenceModel.reference_id == reference_id)
            .first()
        )

    def get_authorized(
        self,
        reference_id: str,
        *,
        session_id: str,
        workspace_root: str | Path | None,
    ) -> ToolOutputReferenceModel | None:
        model = self.get_by_reference_id(reference_id)
        if model is None:
            return None
        if self.is_expired(model):
            self.mark_expired(reference_id)
            return model
        if model.status != "active":
            return model
        if model.session_id != session_id:
            return None
        if model.owner_workspace_hash != workspace_hash(workspace_root):
            return None
        return model

    def is_expired(self, model: ToolOutputReferenceModel, *, now: datetime | None = None) -> bool:
        if model.expires_at is None:
            return False
        cutoff = now or datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = model.expires_at
        if expires_at.tzinfo is not None:
            expires_at = expires_at.astimezone(timezone.utc).replace(tzinfo=None)
        return expires_at <= cutoff

    def blob_path(self, model: ToolOutputReferenceModel) -> Path:
        return self.storage_root / model.storage_key

    def load_authorized_bytes(
        self,
        reference_id: str,
        *,
        session_id: str,
        workspace_root: str | Path | None,
    ) -> LoadedToolOutput | None:
        model = self.get_authorized(
            reference_id,
            session_id=session_id,
            workspace_root=workspace_root,
        )
        if model is None or model.status != "active":
            return None
        path = self.blob_path(model)
        if not path.exists():
            return None
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != model.sha256:
            return None
        return LoadedToolOutput(model=model, data=data)

    def mark_expired(self, reference_id: str) -> bool:
        model = self.get_by_reference_id(reference_id)
        if model is None:
            return False
        model.status = "expired"
        self.session.commit()
        self._delete_blob_best_effort(model)
        return True

    def mark_deleted(self, reference_id: str, *, delete_blob: bool = True) -> bool:
        model = self.get_by_reference_id(reference_id)
        if model is None:
            return False
        if delete_blob:
            self._delete_blob_best_effort(model)
        model.status = "deleted"
        self.session.commit()
        return True

    def cleanup_expired(self, *, now: datetime | None = None) -> dict[str, int]:
        cutoff = now or datetime.now(timezone.utc).replace(tzinfo=None)
        rows = (
            self.session.query(ToolOutputReferenceModel)
            .filter(
                or_(
                    (
                        (ToolOutputReferenceModel.status == "active")
                        & ToolOutputReferenceModel.expires_at.isnot(None)
                        & (ToolOutputReferenceModel.expires_at <= cutoff)
                    ),
                    ToolOutputReferenceModel.status == "expired",
                )
            )
            .all()
        )
        removed_blobs = 0
        missing_blobs = 0
        failed_blob_deletes = 0
        for row in rows:
            path = self.blob_path(row)
            if path.exists():
                try:
                    path.unlink()
                    removed_blobs += 1
                except OSError:
                    failed_blob_deletes += 1
                    logger.warning(
                        "[agent_tools] expired output blob delete failed: reference_id=%s",
                        row.reference_id,
                        exc_info=True,
                    )
            else:
                missing_blobs += 1
            row.status = "expired"
        self.session.commit()
        return {
            "expiredMetadata": len(rows),
            "removedBlobs": removed_blobs,
            "missingBlobs": missing_blobs,
            "failedBlobDeletes": failed_blob_deletes,
            "orphanedBlobs": self.cleanup_orphaned_blobs(),
        }

    def cleanup_orphaned_blobs(self) -> int:
        known = {
            row.storage_key
            for row in self.session.query(ToolOutputReferenceModel)
            .filter(ToolOutputReferenceModel.status == "active")
            .all()
        }
        removed = 0
        for path in self.storage_root.glob("**/*.blob"):
            rel = path.relative_to(self.storage_root).as_posix()
            if rel in known:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                logger.warning(
                    "[agent_tools] orphaned output blob delete failed: storage_key_hash=%s",
                    hashlib.sha256(rel.encode("utf-8", errors="replace")).hexdigest()[:16],
                    exc_info=True,
                )
        return removed

    def _delete_blob_best_effort(self, model: ToolOutputReferenceModel) -> bool:
        try:
            self.blob_path(model).unlink(missing_ok=True)
            return True
        except OSError:
            logger.warning(
                "[agent_tools] output blob delete failed: reference_id=%s",
                model.reference_id,
                exc_info=True,
            )
            return False

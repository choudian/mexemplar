"""Repository for Assistant task attempts and recovery leases."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.exc import IntegrityError

from src.data.models_sqlite import AssistantTaskAttempt
from src.utils.timezone import utc_now_naive

from .base_repository import BaseRepository, generate_id


class AssistantTaskAttemptRepository(BaseRepository):
    # I3：active = 真正占用执行者容量=1 槽的状态。paused 不在其中——暂停即释放执行者槽，
    # 让专员去接别的任务；续跑走 continue_graph → pending_dispatch → 新 start_attempt（attempt
    # 仓库没有 unpause，paused 从不就地复活）。若把 paused 算 active，旧 paused 会撞 per-task
    # partial unique index 把同一任务的续跑挡死。终态/暂停行都不占名额。
    ACTIVE_STATUSES = ("starting", "running")

    def start_attempt(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        lease_owner: str,
        lease_expires_at: datetime,
        attempt_id: str | None = None,
        checkpoint_ref: str | None = None,
    ) -> AssistantTaskAttempt | None:
        self.ensure_immediate_transaction()
        active = (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.task_id == task_id,
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .first()
        )
        if active is not None:
            self._abort_conflict()
            return None
        # FR-003 容量=1：单个执行者一次只执行一件任务。已持有 active attempt 的 executor
        # 不得在另一个任务上再起 attempt；需要更多并行只能由别的 executor 承接。
        executor_busy = (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.executor_type == executor_type,
                AssistantTaskAttempt.executor_id == executor_id,
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .first()
        )
        if executor_busy is not None:
            self._abort_conflict()
            return None
        now = utc_now_naive()
        row = AssistantTaskAttempt(
            attempt_id=attempt_id or generate_id("att"),
            task_id=task_id,
            executor_type=executor_type,
            executor_id=executor_id,
            status="running",
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            heartbeat_at=now,
            started_at=now,
            checkpoint_ref=checkpoint_ref,
        )
        try:
            return self._add_and_flush(row)
        except IntegrityError:
            # 并发下应用层 read 漏过时，DB partial unique index 拒绝第二个 active
            # attempt——视为容量冲突，与应用层守卫等价（return None），不把异常抛给
            # dispatcher。
            self._abort_conflict()
            return None

    def get_by_id(self, attempt_id: str) -> AssistantTaskAttempt | None:
        return self.session.get(AssistantTaskAttempt, attempt_id)

    def list_for_task(self, task_id: str) -> list[AssistantTaskAttempt]:
        return (
            self.session.query(AssistantTaskAttempt)
            .filter(AssistantTaskAttempt.task_id == task_id)
            .order_by(AssistantTaskAttempt.created_at)
            .all()
        )

    def scan_expired_active(self, now: datetime) -> list[AssistantTaskAttempt]:
        return (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
                AssistantTaskAttempt.lease_expires_at <= now,
            )
            .order_by(AssistantTaskAttempt.lease_expires_at)
            .all()
        )

    def latest_resume_ref_for_task(self, task_id: str) -> str | None:
        """Return the newest checkpoint/result reference that can guide a resumed attempt."""
        row = (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.task_id == task_id,
                AssistantTaskAttempt.status.in_(("paused", "fenced")),
            )
            .order_by(
                AssistantTaskAttempt.finished_at.desc().nullslast(),
                AssistantTaskAttempt.updated_at.desc(),
                AssistantTaskAttempt.created_at.desc(),
            )
            .first()
        )
        if row is None:
            return None
        return row.checkpoint_ref or row.result_ref

    def _refetch(self, attempt_id: str) -> AssistantTaskAttempt | None:
        """条件 UPDATE 后用 ``populate_existing`` 重取受影响行的权威态。

        ``synchronize_session=False`` 的 bulk UPDATE 不同步 identity map；只刷新本行，
        不像 ``expire_all`` 那样殃及共享 session 里已加载的 task/adjudication 对象。
        """
        return (
            self.session.query(AssistantTaskAttempt)
            .populate_existing()
            .filter(AssistantTaskAttempt.attempt_id == attempt_id)
            .one_or_none()
        )

    def renew_lease(self, attempt_id: str, *, lease_expires_at: datetime) -> bool:
        """续租一个仍在执行的 attempt，返回是否续上。

        租约原本只在创建时写死一个到期时间，此后无人续约，于是执行体只要跑得比
        租约长就会被恢复扫描判死并重新派发——而它其实还活着，重派只会又起一个。

        与 ``fence`` 同样用条件 UPDATE：续约跑在执行线程，围栏和终态跑在别的
        连接上，ORM 的 read-check-write 会盲写覆盖，把已终态的 attempt 复活。
        守卫进 SQL，匹配 0 行就说明这个 attempt 已经不归自己管了。
        """
        self.ensure_immediate_transaction()
        now = utc_now_naive()
        updated = (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.attempt_id == attempt_id,
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .update(
                {"lease_expires_at": lease_expires_at, "heartbeat_at": now},
                synchronize_session=False,
            )
        )
        self._commit()
        if updated == 0:
            return False
        # bulk UPDATE 不同步 identity map：同 session 的后续读会拿到旧的到期时间，
        # 看起来像"续约没生效"。与 fence 一致，只刷新本行。
        self._refetch(attempt_id)
        return True

    def fence(self, attempt_id: str) -> AssistantTaskAttempt | None:
        # 原子条件 UPDATE：守卫（仅 active 才围栏）进 SQL，不在 Python 读后判断。recovery 的
        # fence 与 worker 的 terminate 跑在独立连接、不共用 _write_lock；ORM read-check-write
        # 会发 WHERE pk=? 盲写，并发下两笔都落库（fence 被 late complete 覆盖、行被污染）。
        # 条件 UPDATE 让 SQLite 写串行把第二笔匹配 0 行，那侧拿 rowcount=0 -> None。
        self.ensure_immediate_transaction()
        updated = (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.attempt_id == attempt_id,
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .update(
                {
                    "status": "fenced",
                    "fence_token": AssistantTaskAttempt.fence_token + 1,
                    "finished_at": utc_now_naive(),
                },
                synchronize_session=False,
            )
        )
        self._commit()
        if updated == 0:
            # attempt 不存在、已围栏或已终态（多见于 worker 完成与恢复扫描的竞态）：
            # 未围栏，返回 None 让调用方跳过。
            return None
        return self._refetch(attempt_id)

    def _terminate_if_current(
        self,
        *,
        attempt_id: str,
        fence_token: int,
        status: str,
        result_ref: str | None,
        error_category: str | None = None,
    ) -> AssistantTaskAttempt | None:
        # 原子条件 UPDATE：fence_token + active 守卫进 SQL。迟到结果（attempt 已被 fence
        # 至更高 token 或已终态）在 SQL 层匹配 0 行 -> None，由调用方计 late_result_rejected。
        self.ensure_immediate_transaction()
        values: dict = {
            "status": status,
            "result_ref": result_ref,
            "finished_at": utc_now_naive(),
        }
        if error_category is not None:
            values["error_category"] = error_category
        updated = (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.attempt_id == attempt_id,
                AssistantTaskAttempt.fence_token == fence_token,
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .update(values, synchronize_session=False)
        )
        self._commit()
        if updated == 0:
            return None
        return self._refetch(attempt_id)

    def complete_if_current(
        self,
        *,
        attempt_id: str,
        fence_token: int,
        result_ref: str | None,
    ) -> AssistantTaskAttempt | None:
        return self._terminate_if_current(
            attempt_id=attempt_id,
            fence_token=fence_token,
            status="succeeded",
            result_ref=result_ref,
        )

    def fail_if_current(
        self,
        *,
        attempt_id: str,
        fence_token: int,
        error_category: str,
        result_ref: str | None = None,
    ) -> AssistantTaskAttempt | None:
        return self._terminate_if_current(
            attempt_id=attempt_id,
            fence_token=fence_token,
            status="failed",
            result_ref=result_ref,
            error_category=error_category,
        )

    def pause_if_current(
        self,
        *,
        attempt_id: str,
        fence_token: int,
        result_ref: str | None = None,
    ) -> AssistantTaskAttempt | None:
        return self._terminate_if_current(
            attempt_id=attempt_id,
            fence_token=fence_token,
            status="paused",
            result_ref=result_ref,
        )

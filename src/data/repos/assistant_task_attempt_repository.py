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
    #
    # ⚠️ 这里**刻意不含 paused**，不是漏网之鱼。排查"暂停后没人被通知"时，这一处曾被列为
    # 疑似缺陷之一——但它的语义是"占不占执行者槽"，跟"该不该通知"无关。paused 的活不需要
    # recovery 兜底，它需要的是通知，而通知由 task.waiting_on 负责（见 dispatcher
    # ._paused_reentry_payload）。改这里只会撞上面说的 unique index。
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

    def scan_all_active(self) -> list[AssistantTaskAttempt]:
        """重启扫描：所有 active attempt，不看 lease 过期。

        与 ``scan_expired_active`` 的区别：那个只扫 lease 过期的（运行期失联，由
        ``TaskCollaborationBackgroundWorker`` 周期调用）；这个扫**全部** active——sidecar
        重启后上一代进程的执行体线程物理全死，无论 lease 到没到期，状态都是假的。判据是
        进程级全局事实（重启 = 上一代全死），不需要逐 attempt 的 PID 校验，因为普通 attempt
        的执行体是进程内线程（``dispatcher.py`` 的 ThreadPoolExecutor），不起子进程。
        """
        return (
            self.session.query(AssistantTaskAttempt)
            .filter(AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES))
            .order_by(AssistantTaskAttempt.created_at)
            .all()
        )

    def latest_resume_ref_for_task(self, task_id: str) -> str | None:
        """Return the newest checkpoint/result reference that can guide a resumed attempt.

        ⚠️ 此方法已被 ``latest_resume_target_for_task`` 取代——后者返回结构化续跑目标，
        含三条硬规则校验（执行人匹配、capability_scope fail-closed、has_progress）。
        此方法保留仅供 fresh 派发路径（``start_pending_graph_tasks``）使用，
        fresh 派发不需要续跑校验，只需要"有没有旧会话可参考"的粗粒度信号。
        """
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

    def latest_resume_target_for_task(
        self,
        task_id: str,
        *,
        assignee_type: str,
        assignee_id: str,
    ) -> dict | None:
        """③ 第二阶段：选出可续跑的 attempt，返回结构化续跑目标。

        三条硬规则（详见 step-3-resume-plan §2.2）：
        1. paused 和 fenced 都续跑（fenced 带对账提示）
        2. 候选 executor_type/executor_id 必须匹配 assignee_type/assignee_id
        3. has_progress：会话里有任何 assistant 消息才算（含 content 空的）

        返回 ``{"session_id": str, "was_fenced": bool, "has_progress": bool}`` 或 None。
        capability_scope 的 fail-closed 校验由调用方做（数据层不持有 task.capability_scope）。
        """
        from src.data.models_sqlite import Message

        candidates = (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.task_id == task_id,
                AssistantTaskAttempt.status.in_(("paused", "fenced")),
                AssistantTaskAttempt.executor_type == assignee_type,
                AssistantTaskAttempt.executor_id == assignee_id,
                AssistantTaskAttempt.executor_session_id.is_not(None),
            )
            .order_by(
                AssistantTaskAttempt.finished_at.desc().nullslast(),
                AssistantTaskAttempt.updated_at.desc(),
                AssistantTaskAttempt.created_at.desc(),
            )
            .all()
        )
        for attempt in candidates:
            session_id = attempt.executor_session_id
            if not session_id:
                continue
            # has_progress：会话里有任何 assistant 消息就算（含 content 空的、只带 tool_calls 的）
            has_msg = (
                self.session.query(Message.message_id)
                .filter(
                    Message.session_id == session_id,
                    Message.role == "assistant",
                )
                .first()
            )
            if has_msg is None:
                continue  # 没进度，往前找下一个
            return {
                "session_id": session_id,
                "was_fenced": attempt.status == "fenced",
                "has_progress": True,
            }
        return None

    def latest_attempt_for_task(self, task_id: str) -> AssistantTaskAttempt | None:
        """返回某 task 最新一条 attempt（不限状态），按创建时间倒序。

        供同步委派终态映射用：拿到最新 attempt 后看 status 决定要不要写终态。
        """
        return (
            self.session.query(AssistantTaskAttempt)
            .filter(AssistantTaskAttempt.task_id == task_id)
            .order_by(AssistantTaskAttempt.created_at.desc())
            .first()
        )

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

    def _active_attempt_for_task(self, task_id: str) -> AssistantTaskAttempt | None:
        """返回该任务当前的 active attempt（partial unique index 保证至多一条）。

        ``populate_existing`` 强制落库读：绑定态可能被 recovery fence / 终态在别的连接
        上改写，归属判定和绑定刷新都必须拿权威值，不能信 identity map 里的旧态。
        """
        return (
            self.session.query(AssistantTaskAttempt)
            .populate_existing()
            .filter(
                AssistantTaskAttempt.task_id == task_id,
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .first()
        )

    def bind_session(self, *, task_id: str, executor_session_id: str) -> bool:
        """把执行体的会话 id 绑定到该任务当前 active attempt，返回是否绑上。

        派活先于执行体创建，所以 ``executor_id`` 对临时子代理只能填任务 id 顶替——
        "此刻谁在干这活"因此在库里不存在。执行体启动时回填本列补上这条事实，
        归属校验和任务下钻都以它为准。

        与 ``renew_lease`` 同样用条件 UPDATE：绑定跑在执行线程，围栏和终态跑在别的
        连接上，ORM 的 read-check-write 会盲写把已终态的 attempt 复活。守卫进 SQL，
        匹配 0 行说明这个任务已经没有 active attempt——绑定失败即返回 False，
        由调用方决定是继续还是放弃，不静默当成功。
        """
        self.ensure_immediate_transaction()
        updated = (
            self.session.query(AssistantTaskAttempt)
            .filter(
                AssistantTaskAttempt.task_id == task_id,
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .update({"executor_session_id": executor_session_id}, synchronize_session=False)
        )
        self._commit()
        if updated == 0:
            return False
        # bulk UPDATE 不同步 identity map：同 session 的后续读会拿到绑定前的 None，
        # 看起来像"绑定没生效"。partial unique index 保证每 task 至多一条 active，
        # 直接 populate_existing 刷新该行即可，不必先查 attempt_id 再按 PK refetch。
        self._active_attempt_for_task(task_id)
        return True

    def active_attempt_session(self, task_id: str) -> str | None:
        """返回该任务当前 active attempt 绑定的执行会话 id，未绑定或无 active attempt 时 None。

        每个任务同时至多一条 active attempt（partial unique index 焊死），所以
        "正在干这活的执行体"必然唯一，不需要调用方再做区分。
        """
        row = self._active_attempt_for_task(task_id)
        return row.executor_session_id if row is not None else None

    def latest_attempt_for_session(self, executor_session_id: str) -> AssistantTaskAttempt | None:
        """按执行会话 id 反查最新 attempt（不限状态）。

        供"判断执行体在不在跑"用：拿到 attempt 后看 status 是否在 ACTIVE_STATUSES。
        返回最新一条是因为一个 session 可能先后跑过多轮 attempt（暂停→续跑开新 attempt），
        只有最新那条反映当前真实状态。
        """
        return (
            self.session.query(AssistantTaskAttempt)
            .filter(AssistantTaskAttempt.executor_session_id == executor_session_id)
            .order_by(AssistantTaskAttempt.created_at.desc())
            .first()
        )

    def active_executor_sessions(self, executor_session_ids: list[str]) -> set[str]:
        """批量返回有 active attempt 的执行会话 id 集合。

        供 observability 等批量查询用：一次查 N 个子代理各自的 attempt，返回其中
        有 active（starting/running）attempt 的 session_id 子集。
        """
        if not executor_session_ids:
            return set()
        rows = (
            self.session.query(AssistantTaskAttempt.executor_session_id)
            .filter(
                AssistantTaskAttempt.executor_session_id.in_(executor_session_ids),
                AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
            )
            .all()
        )
        return {row[0] for row in rows if row[0]}

    def latest_statuses_for_sessions(
        self, executor_session_ids: list[str]
    ) -> dict[str, str]:
        """批量返回每个执行会话最新 attempt 的 status。

        供 observability 批量渲染子代理列表用：一次查 N 个 session 的最新 attempt status，
        返回 ``{session_id: attempt_status}``。无 attempt 的 session 不在结果中。
        """
        if not executor_session_ids:
            return {}
        # 每个 session 最新 attempt 的 status：用 ROW_NUMBER() 窗口函数保证确定性。
        # 比 IN(subquery)+ORDER BY 更可靠——后者不保证去重和外层顺序。
        from sqlalchemy import func, literal_column
        from sqlalchemy.orm import aliased

        # 子查询给每行按 session 分组、created_at 倒序编号
        ranked = (
            self.session.query(
                AssistantTaskAttempt.executor_session_id.label("sid"),
                AssistantTaskAttempt.status.label("st"),
                func.row_number()
                .over(
                    partition_by=AssistantTaskAttempt.executor_session_id,
                    order_by=AssistantTaskAttempt.created_at.desc(),
                )
                .label("rn"),
            )
            .filter(AssistantTaskAttempt.executor_session_id.in_(executor_session_ids))
            .subquery()
        )
        rows = (
            self.session.query(ranked.c.sid, ranked.c.st)
            .filter(ranked.c.rn == 1)
            .all()
        )
        result: dict[str, str] = {}
        for session_id, status in rows:
            if session_id:
                result[session_id] = status
        return result

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
        checkpoint_ref: str | None = None,
    ) -> AssistantTaskAttempt | None:
        """暂停 attempt。checkpoint_ref 存续跑信息 JSON（executor_session_id 等），
        供 ``latest_resume_target_for_task`` 解析续跑目标。
        """
        if checkpoint_ref is not None:
            # _terminate_if_current 不写 checkpoint_ref，单独先写
            self.ensure_immediate_transaction()
            updated = (
                self.session.query(AssistantTaskAttempt)
                .filter(
                    AssistantTaskAttempt.attempt_id == attempt_id,
                    AssistantTaskAttempt.fence_token == fence_token,
                    AssistantTaskAttempt.status.in_(self.ACTIVE_STATUSES),
                )
                .update({"checkpoint_ref": checkpoint_ref}, synchronize_session=False)
            )
            self._commit()
            if updated == 0:
                return None
        return self._terminate_if_current(
            attempt_id=attempt_id,
            fence_token=fence_token,
            status="paused",
            result_ref=result_ref,
        )

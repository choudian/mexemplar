"""v40：``assistant_tasks.status`` 的 ``failed`` 改名为 ``abandoned``。

不是加格子，是给同一个格子换一个说真话的名字。

能进这个格子的只有两条路，两条都是明确拍板：裁定选 abandoned，或主助理调
``abandon_request_graph`` 放弃整个请求。系统侧的失败根本不走这里——执行体崩了写
attempt 表并建待裁定，租约过期回 ``pending_dispatch`` 重派。

叫 ``failed`` 时，读到它的人（主助理、看板、日志）会以为"系统判它死了，也许该
重试"，而真相是有人已经决定放弃：语义和处置正好相反。

整表重建最怕两件事——**存量行没被转换**（迁移后立刻撞 CHECK）和**转换时丢了列**
（悄无声息地少一批数据）。下面每一条都在钉这两件事。
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.business.task_collaboration.models import TaskStatus
from src.data import migrations
from src.data.models_sqlite import AssistantTask, Base
from src.data.repos import AssistantTaskRepository

from tests.data.test_migrations_v38 import TASK_INDEXES
from tests.data.test_migrations_v39 import _engine_at_v38, _allowed_values, _indexes


#: 迁移前埋进去的各种状态。``failed`` 是唯一该被改写的，其余每一个都必须原样留下——
#: 一条 ``CASE WHEN`` 写错就会连累它们。
_SEEDED_STATUSES = ("pending_dispatch", "running", "completed", "failed", "cancelled")


def _engine_at_v39():
    """v39 状态的库，外加一批各种状态的任务行。

    走真实迁移链（v37→v38→v39）而不是手搭 schema：顺带证明这几步能连着跑。
    """
    engine = _engine_at_v38()
    migrations.migrate_to_v39(engine)
    with engine.begin() as conn:
        for status in _SEEDED_STATUSES:
            conn.execute(
                text(
                    """
                    INSERT INTO assistant_tasks (
                        task_id, graph_id, root_task_id, parent_task_id,
                        session_id, user_message_sequence, title, description,
                        status, suspend_reason, waiting_on, assignee_type, assignee_id,
                        owner_session_id, capability_scope, graph_version,
                        task_version, created_at, updated_at, completed_at,
                        failed_at, cancelled_at, requires_confirmation, workspace_root
                    ) VALUES (
                        :task_id, 'tg_v40', 'tsk_root_v40', 'tsk_parent_v40',
                        'ast_v40', 7, :title, 'v40 seed description',
                        :status, NULL, NULL, 'specialist', 'sp_v40',
                        'ast_owner_v40', '["read_file"]', 5,
                        9, '2026-07-30 10:00:00', '2026-07-30 10:05:00', NULL,
                        '2026-07-30 10:06:00', NULL, 1, 'E:/worktrees/v40'
                    )
                    """
                ),
                {"task_id": f"tsk_v40_{status}", "title": f"seeded {status}", "status": status},
            )
    return engine


def _status_by_task(engine, prefix: str = "tsk_v40_") -> dict[str, str]:
    with engine.connect() as conn:
        return {
            row[0]: row[1]
            for row in conn.execute(
                text("SELECT task_id, status FROM assistant_tasks WHERE task_id LIKE :p"),
                {"p": f"{prefix}%"},
            )
        }


def test_v40_rewrites_existing_failed_rows_and_leaves_the_rest_alone() -> None:
    """存量行的定义性验收。

    回填必须发生在 ``INSERT ... SELECT`` 里：新表的 CHECK 已经不认 ``failed``，
    先插再 UPDATE 会被当场拒绝，整个迁移失败。
    """
    engine = _engine_at_v39()

    migrations.migrate_to_v40(engine)

    statuses = _status_by_task(engine)
    assert statuses["tsk_v40_failed"] == "abandoned"
    # 其余每一个原样留下——CASE WHEN 写错最容易把它们一起改掉。
    assert statuses["tsk_v40_pending_dispatch"] == "pending_dispatch"
    assert statuses["tsk_v40_running"] == "running"
    assert statuses["tsk_v40_completed"] == "completed"
    assert statuses["tsk_v40_cancelled"] == "cancelled"
    # 迁移后库里不该再剩任何 failed。
    with engine.connect() as conn:
        remaining = conn.execute(
            text("SELECT COUNT(*) FROM assistant_tasks WHERE status = 'failed'")
        ).scalar_one()
    assert remaining == 0


def test_v40_carries_every_column_through_the_rebuild() -> None:
    """整表重建把每一列都搬过去了——只有 status 变，其余逐字段相同。

    重建时漏写一列不会报错，只会让那列变成 NULL：数据静静地少一批，而这是最难
    在事后发现的一类故障。所以这里逐列比对，不只抽查几个。
    """
    engine = _engine_at_v39()
    with engine.connect() as conn:
        before = dict(
            conn.execute(
                text("SELECT * FROM assistant_tasks WHERE task_id = 'tsk_v40_failed'")
            )
            .one()
            ._mapping
        )

    migrations.migrate_to_v40(engine)

    with engine.connect() as conn:
        after = dict(
            conn.execute(
                text("SELECT * FROM assistant_tasks WHERE task_id = 'tsk_v40_failed'")
            )
            .one()
            ._mapping
        )

    assert after["status"] == "abandoned"
    assert before["status"] == "failed"
    assert {k: v for k, v in after.items() if k != "status"} == {
        k: v for k, v in before.items() if k != "status"
    }


def test_v40_advances_version_rebuilds_indexes_and_is_idempotent() -> None:
    engine = _engine_at_v39()

    migrations.migrate_to_v40(engine)
    # 跑第二遍：这时库里已经没有 failed 了，CASE WHEN 什么都不做，但整表重建仍要能走完。
    migrations.migrate_to_v40(engine)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version FROM schema_version")).scalar_one()
    assert version == 40
    assert _indexes(engine, "assistant_tasks") == TASK_INDEXES
    assert _status_by_task(engine)["tsk_v40_failed"] == "abandoned"


def test_v40_check_accepts_abandoned_and_rejects_the_old_name() -> None:
    """放宽不等于放开：旧名字必须当场被拒，不能悄悄留一条后路。"""
    engine = _engine_at_v39()
    migrations.migrate_to_v40(engine)

    assert _allowed_values(engine, "assistant_tasks", "ck_assistant_tasks_status") == {
        status.value for status in TaskStatus
    }

    with pytest.raises(IntegrityError, match="ck_assistant_tasks_status"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE assistant_tasks SET status = 'failed' "
                    "WHERE task_id = 'tsk_v40_completed'"
                )
            )


def test_v40_skips_cleanly_when_the_table_is_absent() -> None:
    """全新安装尚未建表时也要能推进版本号，不能卡在这一步。"""
    engine = create_engine("sqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (39)"))

    migrations.migrate_to_v40(engine)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version FROM schema_version")).scalar_one() == 40


def test_orm_and_migration_agree_on_every_task_status() -> None:
    """ORM 建的表和迁移建的表必须认同一组状态。

    两条路径分别服务全新安装和存量升级；它们分岔时，症状是"我这儿好好的，你那儿
    一存就报错"，而两边的代码都看不出问题。
    """
    orm_constraint = next(
        c
        for c in AssistantTask.__table__.constraints
        if getattr(c, "name", None) == "ck_assistant_tasks_status"
    )
    orm_values = set(re.findall(r"'([a-z_]+)'", str(orm_constraint.sqltext)))

    engine = _engine_at_v39()
    migrations.migrate_to_v40(engine)
    migrated_values = _allowed_values(engine, "assistant_tasks", "ck_assistant_tasks_status")

    assert orm_values == migrated_values == {status.value for status in TaskStatus}


def test_repository_persists_every_task_status_on_a_fresh_orm_schema() -> None:
    """全新安装路径：每个状态真写一遍，不只读 DDL。

    ``suspended`` 另有 suspend_reason/waiting_on 的强制约束，不在这条的范围内。
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    terminal_and_active = [s for s in TaskStatus if s != TaskStatus.SUSPENDED]
    with Session.begin() as session:
        repo = AssistantTaskRepository(session)
        for status in terminal_and_active:
            task_id = f"tsk_orm_{status.value}"
            repo.create_task(
                task_id=task_id,
                graph_id="tg_orm_v40",
                session_id="ast_orm_v40",
                title=status.value,
                description="task status persistence contract",
            )
            assert repo.update_status(task_id, status=status.value) is not None

    with engine.connect() as conn:
        persisted = {
            row[0]
            for row in conn.execute(
                text("SELECT status FROM assistant_tasks WHERE graph_id = 'tg_orm_v40'")
            )
        }
    assert persisted == {status.value for status in terminal_and_active}


def test_abandoning_a_task_stamps_the_terminal_timestamp() -> None:
    """改名后时间戳仍要落下。

    列名还叫 ``failed_at``（没有任何读取方，改名要动 5 段迁移历史 DDL 换不来东西），
    但写它的分支是按 status 值匹配的——分支漏改的话不报错，只是从此再没有任何任务
    记下过终结时刻。
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    with Session.begin() as session:
        repo = AssistantTaskRepository(session)
        repo.create_task(
            task_id="tsk_stamp",
            graph_id="tg_stamp",
            session_id="ast_stamp",
            title="stamp",
            description="terminal timestamp contract",
        )
        assert repo.update_status("tsk_stamp", status=TaskStatus.ABANDONED.value) is not None

    with engine.connect() as conn:
        stamped = conn.execute(
            text("SELECT failed_at FROM assistant_tasks WHERE task_id = 'tsk_stamp'")
        ).scalar_one()
    assert stamped is not None

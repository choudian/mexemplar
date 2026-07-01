"""Shared-session unit of work for atomic multi-repository task writes.

办公助理任务协作里很多业务动作要"写 A 表再写 B 表"才算完成：认领 = 占位 + 写 claim，
恢复 = fence + 挂起 + 建裁定，派发 = 建 attempt + 翻任务态，裁定 = 决策 + 翻任务态 + 失败桥接。
默认情况下每个 Repository 各持一个 session、各自 commit，任一第二步失败都会留下半完成状态。

这里提供两件东西让上述动作变原子：

- :func:`new_task_session` —— 从统一 SQLAlchemy 管理器取一个新 session，供同一个 service 的
  各 Repository 共享。
- :class:`AtomicTaskService` —— service mixin，``_atomic`` 在操作边界对共享 session 统一
  commit / rollback。它按 session 重入（深度计数挂在 session 上），所以组合调用（一个 service
  方法里调用另一个共享同一 session 的 service 方法）只在最外层提交，不会把半截操作提前 commit。

共享 session 下，Repository 的 :meth:`~src.data.repos.base_repository.BaseRepository._commit`
只 flush；真正落库由 ``_atomic`` 出口完成。
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from src.data.sqlalchemy_manager import get_sqlalchemy_manager

if TYPE_CHECKING:
    from src.data.repos.base_repository import BaseRepository

_TXN_DEPTH_ATTR = "_task_txn_depth"


def new_task_session() -> Session:
    """返回一个新的共享 session（同一 service 的多个 Repository 复用它以保证原子）。"""
    manager = get_sqlalchemy_manager()
    manager.initialize()
    return manager.get_session()


@contextmanager
def task_session_scope() -> Iterator[Session]:
    """Context manager for a standalone task collaboration session.

    Provides the session lifecycle (commit on success, rollback on error, close always)
    used by background worker jobs and other standalone operations.
    """
    session = new_task_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class AtomicTaskService:
    """为任务协作 service 提供按 session 重入的事务边界。

    使用方需在 ``__init__`` 里把 ``self._session`` 指向各 Repository 共享的 session，
    并设置 ``self._owns_session`` 标记是否由本 service 创建 session。
    """

    _session: Session
    _owns_session: bool

    def _init_repos(self, **repos: "tuple[type[BaseRepository], BaseRepository | None]") -> None:
        """把本 service 用到的 Repository 接到共享 session 上。

        每个关键字把仓库属性名（存为 ``_<name>``）映射到 ``(RepoClass, 注入实例或 None)``。
        仅当所有注入实例都为 None 时本 service 才拥有 session——此时新建一个共享 session 供
        全部 Repository 复用，``_atomic`` 在出口统一提交；否则复用注入的 Repository（约定它们
        共享同一 session）。``self._session`` 取声明顺序里的第一个 Repository 的 session。
        """
        self._owns_session = all(injected is None for _, injected in repos.values())
        session = new_task_session() if self._owns_session else None
        first_repo: BaseRepository | None = None
        for attr, (repo_cls, injected) in repos.items():
            repo = repo_cls(session) if self._owns_session else (injected or repo_cls())
            setattr(self, f"_{attr}", repo)
            if first_repo is None:
                first_repo = repo
        self._session = first_repo.session

    def close(self) -> None:
        """Close the session if this service owns it."""
        if getattr(self, "_owns_session", False) and self._session:
            self._session.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        """按 session 重入的事务边界：仅最外层 commit/rollback，内层只 yield。

        business 层经此统一管理事务边界是 Unit-of-Work 模式的有意设计——SQL 仍由 Repository
        封装（共享 session 下 ``_commit`` 只 flush），这里只决定"一组 Repository 写入何时原子
        落库"，不拼 SQL，因此不违反 constitution II 的"业务数据经 Repository、不直接写 SQL"。
        """
        session = self._session
        depth = getattr(session, _TXN_DEPTH_ATTR, 0) + 1
        setattr(session, _TXN_DEPTH_ATTR, depth)
        try:
            yield
            if depth == 1:
                session.commit()
        except Exception:
            if depth == 1:
                session.rollback()
            raise
        finally:
            setattr(session, _TXN_DEPTH_ATTR, depth - 1)

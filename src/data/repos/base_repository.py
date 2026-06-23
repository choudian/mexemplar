"""
BaseRepository -- Repository 基类，提供统一的会话初始化
"""

import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session as SQLAlchemySession

from ..sqlalchemy_manager import get_sqlalchemy_manager

logger = logging.getLogger(__name__)


def generate_id(prefix: str) -> str:
    """Generate a prefixed unique ID for repository rows."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


class BaseRepository:
    """Repository 基类，提供统一的会话初始化"""

    def __init__(self, session: Optional[SQLAlchemySession] = None):
        if session is None:
            manager = get_sqlalchemy_manager()
            manager.initialize()
            self.session = manager.get_session()
            self._owns_session = True
        else:
            self.session = session
            self._owns_session = False

    def close(self):
        """关闭 session（仅关闭由 Repository 自己创建的 session）"""
        if self._owns_session and self.session:
            try:
                self.session.close()
            except Exception as e:
                logger.debug(f"Error closing session: {e}")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def ensure_immediate_transaction(self) -> None:
        """No-op：写串行由 SQLite 单写者 + busy_timeout 保证，不手动 BEGIN IMMEDIATE。

        手动 ``session.execute("BEGIN IMMEDIATE")`` 会与 SQLAlchemy/pysqlite 自动事务嵌套
        （"cannot start a transaction within a transaction"）。CAS 类操作（容量=1、认领、
        fence）的原子性由 ``assistant_task_attempts`` 上的 partial unique index
        （active-per-task / active-per-executor）兜底，不依赖 IMMEDIATE 锁或进程级写锁；
        多 worker 并发写由 SQLite 单写者 + busy_timeout 排队。
        """
        return None

    def _commit(self) -> None:
        """Persist pending writes.

        当 Repository 自己持有 session（独立使用）时直接 commit；当 session 是外部注入
        的共享 session（``_owns_session=False``，跨多个 Repository 的一个工作单元）时只
        flush，由工作单元出口统一 commit/rollback，从而让"写 A 表再写 B 表"保持原子。
        """
        if self._owns_session:
            self.session.commit()
        else:
            self.session.flush()

    def _add_and_flush(self, row) -> object:
        """Add a row, commit/flush, and refresh it in one step."""
        self.session.add(row)
        self._commit()
        self.session.refresh(row)
        return row

    def _update_and_flush(self, row) -> object:
        """Commit/flush pending mutations on a row and refresh it."""
        self._commit()
        self.session.refresh(row)
        return row

    def _abort_conflict(self) -> None:
        """Discard a no-op CAS conflict.

        乐观并发方法在版本不匹配/已被占用时未写入任何行，回滚 session 释放脏状态和
        IMMEDIATE 锁。共享 session（``_atomic`` 工作单元）下回滚整个工作单元——这是
        原子性的有意语义：工作单元内 CAS 冲突视为整单元失败（见
        ``test_claim_task_rolls_back_assign_when_claim_write_fails``）。当前所有 CAS 方法在工作
        单元中都是首操作或独立，不存在“在先写入被误回滚”的受影响路径；若未来出现“写 A
        再 CAS B”组合，应在调用层显式处理冲突，而非用 savepoint 削弱工作单元原子性。
        """
        if self.session.in_transaction():
            self.session.rollback()

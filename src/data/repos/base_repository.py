"""
BaseRepository -- Repository 基类，提供统一的会话初始化
"""

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session as SQLAlchemySession

from ..sqlalchemy_manager import get_sqlalchemy_manager

logger = logging.getLogger(__name__)


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
        """Start a SQLite IMMEDIATE transaction when the session has not begun one yet."""
        bind = self.session.get_bind()
        if getattr(getattr(bind, "dialect", None), "name", None) != "sqlite":
            return
        if self.session.in_transaction():
            return
        self.session.execute(text("BEGIN IMMEDIATE"))

"""
RawSQLRepository

基于原生 sqlite3 的 Repository 基类，封装连接管理和事务样板。
"""

import sqlite3
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


class RawSQLRepository:
    """基于原生 sqlite3 的 Repository 基类，封装连接管理和事务样板。"""

    def __init__(self, db_manager):
        self._db_manager = db_manager

    def _execute(self, sql: str, params: tuple = (), commit: bool = True) -> sqlite3.Cursor:
        """执行 SQL，处理连接获取和事务管理。"""
        conn = self._db_manager.connect()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            if commit:
                conn.commit()
            return cursor
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"SQL 执行失败: {e}")
            raise

    def _execute_insert(self, sql: str, params: tuple = ()) -> int:
        """执行 INSERT 并返回 lastrowid。"""
        cursor = self._execute(sql, params)
        return cursor.lastrowid

    def _fetch_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """执行 SELECT 并返回一行。"""
        cursor = self._execute(sql, params, commit=False)
        return cursor.fetchone()

    def _fetch_all(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        """执行 SELECT 并返回所有行。"""
        cursor = self._execute(sql, params, commit=False)
        return cursor.fetchall()

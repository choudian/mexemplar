"""
Intent Repository

提供意图数据的 CRUD 操作
"""

import sqlite3
import json
import logging
from typing import List, Optional
from datetime import datetime

from src.data.database import DatabaseManager
from .intent_models import Intent, IntentStatus

logger = logging.getLogger(__name__)


class IntentRepository:
    """意图仓库"""

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def create(self, intent: Intent) -> Intent:
        """创建意图"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO intents
                (intent_id, recording_id, core_operations, target, business_scenario,
                 expected_results, status, confirmed_operations, user_message,
                 analysis_confidence, llm_model_used, created_at, updated_at, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    intent.intent_id,
                    intent.recording_id,
                    json.dumps(intent.core_operations, ensure_ascii=False),
                    intent.target,
                    intent.business_scenario,
                    json.dumps(intent.expected_results, ensure_ascii=False),
                    (
                        intent.status.value
                        if isinstance(intent.status, IntentStatus)
                        else intent.status
                    ),
                    json.dumps(intent.confirmed_operations, ensure_ascii=False),
                    intent.user_message,
                    intent.analysis_confidence,
                    intent.llm_model_used,
                    intent.created_at or datetime.now(),
                    intent.updated_at or datetime.now(),
                    intent.confirmed_at,
                ),
            )
            conn.commit()
            logger.info(f"意图已创建: {intent.intent_id}")
            return intent
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"创建意图失败: {e}")
            raise

    def get_by_id(self, intent_id: str) -> Optional[Intent]:
        """根据ID获取意图"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM intents WHERE intent_id = ?", (intent_id,))
        row = cursor.fetchone()

        if row:
            return Intent.from_dict(dict(row))
        return None

    def update(self, intent: Intent) -> Intent:
        """更新意图"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                UPDATE intents
                SET core_operations = ?, target = ?, business_scenario = ?,
                    expected_results = ?, status = ?, confirmed_operations = ?,
                    user_message = ?, analysis_confidence = ?, llm_model_used = ?,
                    updated_at = ?, confirmed_at = ?
                WHERE intent_id = ?
            """,
                (
                    json.dumps(intent.core_operations, ensure_ascii=False),
                    intent.target,
                    intent.business_scenario,
                    json.dumps(intent.expected_results, ensure_ascii=False),
                    (
                        intent.status.value
                        if isinstance(intent.status, IntentStatus)
                        else intent.status
                    ),
                    json.dumps(intent.confirmed_operations, ensure_ascii=False),
                    intent.user_message,
                    intent.analysis_confidence,
                    intent.llm_model_used,
                    intent.updated_at or datetime.now(),
                    intent.confirmed_at,
                    intent.intent_id,
                ),
            )
            conn.commit()
            logger.info(f"意图已更新: {intent.intent_id}")
            return intent
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"更新意图失败: {e}")
            raise

    def delete(self, intent_id: str) -> bool:
        """删除意图"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM intents WHERE intent_id = ?", (intent_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"意图已删除: {intent_id}")
            return deleted
        except sqlite3.Error as e:
            conn.rollback()
            logger.error(f"删除意图失败: {e}")
            raise

    def get_all(self, limit: int = 100) -> List[Intent]:
        """获取所有意图"""
        conn = self.db_manager.connect()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM intents
            ORDER BY created_at DESC
            LIMIT ?
        """,
            (limit,),
        )
        rows = cursor.fetchall()

        return [Intent.from_dict(dict(row)) for row in rows]

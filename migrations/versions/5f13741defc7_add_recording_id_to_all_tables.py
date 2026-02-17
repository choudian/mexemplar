"""add_recording_id_to_all_tables

为所有表添加 recording_id 字段，并添加其他辅助字段

Revision ID: 5f13741defc7
Revises:
Create Date: 2026-02-09 10:48:43.800750

"""
import os
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite, postgresql

# revision identifiers, used by Alembic.
revision: str = '5f13741defc7'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def get_db_type():
    """从环境变量获取数据库类型"""
    return os.environ.get("ALEMBIC_DB_TYPE", "sqlite")


def upgrade() -> None:
    """升级数据库结构"""
    db_type = get_db_type()

    if db_type == "duckdb":
        # ========== DuckDB 迁移 ==========

        # 1. network_requests 表
        op.execute("""
            -- 添加 recording_id
            ALTER TABLE network_requests ADD COLUMN IF NOT EXISTS recording_id VARCHAR;

            -- 添加过滤相关字段
            ALTER TABLE network_requests ADD COLUMN IF NOT EXISTS filtered BOOLEAN DEFAULT FALSE;
            ALTER TABLE network_requests ADD COLUMN IF NOT EXISTS filter_reason JSON;
            ALTER TABLE network_requests ADD COLUMN IF NOT EXISTS filtered_at TIMESTAMP;

            -- 添加重要性字段
            ALTER TABLE network_requests ADD COLUMN IF NOT EXISTS is_recommendation BOOLEAN DEFAULT FALSE;
            ALTER TABLE network_requests ADD COLUMN IF NOT EXISTS importance_level VARCHAR;
        """)

        # 回填 recording_id
        op.execute("""
            UPDATE network_requests nr
            SET recording_id = a.recording_id
            FROM actions a
            WHERE nr.action_id = a.action_id
            AND nr.recording_id IS NULL;
        """)

        # 2. sibling_snapshots 表
        op.execute("""
            ALTER TABLE sibling_snapshots ADD COLUMN IF NOT EXISTS recording_id VARCHAR;
        """)

        # 3. list_contexts 表
        op.execute("""
            ALTER TABLE list_contexts ADD COLUMN IF NOT EXISTS recording_id VARCHAR;
        """)

        # 4. filter_decisions 表
        op.execute("""
            ALTER TABLE filter_decisions ADD COLUMN IF NOT EXISTS recording_id VARCHAR;
            ALTER TABLE filter_decisions ADD COLUMN IF NOT EXISTS action_id INTEGER;
            ALTER TABLE filter_decisions ADD COLUMN IF NOT EXISTS request_timestamp TIMESTAMP;
            ALTER TABLE filter_decisions ADD COLUMN IF NOT EXISTS action_timestamp TIMESTAMP;
        """)

        # 回填 filter_decisions
        op.execute("""
            UPDATE filter_decisions fd
            SET action_id = nr.action_id,
                recording_id = a.recording_id,
                request_timestamp = nr.timestamp,
                action_timestamp = a.timestamp
            FROM network_requests nr
            LEFT JOIN actions a ON nr.action_id = a.action_id
            WHERE fd.request_id = CAST(nr.request_id AS VARCHAR)
            AND fd.action_id IS NULL;
        """)

    elif db_type == "sqlite":
        # ========== SQLite 迁移 ==========
        # SQLite 使用 batch_alter_table 模式

        with op.batch_alter_table("tools", schema=None) as batch_op:
            batch_op.add_column(sa.Column("recording_id", sa.String(), nullable=True))

        with op.batch_alter_table("task_executions", schema=None) as batch_op:
            batch_op.add_column(sa.Column("recording_id", sa.String(), nullable=True))

        with op.batch_alter_table("conversations", schema=None) as batch_op:
            batch_op.add_column(sa.Column("recording_id", sa.String(), nullable=True))


def downgrade() -> None:
    """回滚数据库结构"""
    db_type = get_db_type()

    if db_type == "duckdb":
        # ========== DuckDB 回滚 ==========

        op.execute("""
            -- network_requests 表
            ALTER TABLE network_requests DROP COLUMN IF EXISTS recording_id;
            ALTER TABLE network_requests DROP COLUMN IF EXISTS filtered;
            ALTER TABLE network_requests DROP COLUMN IF EXISTS filter_reason;
            ALTER TABLE network_requests DROP COLUMN IF EXISTS filtered_at;
            ALTER TABLE network_requests DROP COLUMN IF EXISTS is_recommendation;
            ALTER TABLE network_requests DROP COLUMN IF EXISTS importance_level;

            -- sibling_snapshots 表
            ALTER TABLE sibling_snapshots DROP COLUMN IF EXISTS recording_id;

            -- list_contexts 表
            ALTER TABLE list_contexts DROP COLUMN IF EXISTS recording_id;

            -- filter_decisions 表
            ALTER TABLE filter_decisions DROP COLUMN IF EXISTS recording_id;
            ALTER TABLE filter_decisions DROP COLUMN IF EXISTS action_id;
            ALTER TABLE filter_decisions DROP COLUMN IF EXISTS request_timestamp;
            ALTER TABLE filter_decisions DROP COLUMN IF EXISTS action_timestamp;
        """)

    elif db_type == "sqlite":
        # ========== SQLite 回滚 ==========

        with op.batch_alter_table("tools", schema=None) as batch_op:
            batch_op.drop_column("recording_id")

        with op.batch_alter_table("task_executions", schema=None) as batch_op:
            batch_op.drop_column("recording_id")

        with op.batch_alter_table("conversations", schema=None) as batch_op:
            batch_op.drop_column("recording_id")

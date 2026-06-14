"""
GrandTourFixtureService -- Real Grand Tour E2E 夹具技能注入。

仅在 ``MEXEMPLAR_REAL_GRAND_TOUR=1`` 的真实大巡演 sidecar 启动时幂等注入一个
固定的 fixture published skill，作为技能组合"至少 2 个成员"契约的第二成员占位。
生产环境（不设该 env）短路返回，零影响。

模式参考 ``src/business/brain/skill_bootstrap_service.py`` 的启动期幂等注入。
"""

import logging
from typing import Any

from src.data.grand_tour_fixture_seed import (
    FIXTURE_CODE_LANGUAGE,
    FIXTURE_CODE_VERSION,
    FIXTURE_DESCRIPTION,
    FIXTURE_EXECUTION_CODE,
    FIXTURE_EXECUTION_STRATEGY,
    FIXTURE_SOURCE,
    FIXTURE_TOOL_ID,
    FIXTURE_TOOL_NAME,
    FIXTURE_TRIAL_SUCCESS_COUNT,
)
from src.data.real_tour_audit import is_real_tour_runtime

logger = logging.getLogger(__name__)


def ensure_fixture_skill() -> dict[str, Any]:
    """幂等注入 Real Grand Tour 夹具技能；非 grand-tour 环境直接短路。

    返回 dict 标注本次行为：``skipped``（非 grand-tour）/ ``created``（首次注入）/
    ``repaired``（已存在但字段漂移被修正）。
    """
    if not is_real_tour_runtime():
        return {
            "fixture_tool_id": FIXTURE_TOOL_ID,
            "created": False,
            "skipped": True,
        }

    from src.data.models_sqlite import Tool as ToolOrm
    from src.data.repositories import ToolRepository
    from src.data.sqlalchemy_manager import get_sqlalchemy_manager

    manager = get_sqlalchemy_manager()
    manager.initialize()
    active_session = manager.get_session()
    owns_session = True

    try:
        repo = ToolRepository(active_session)
        existing = repo.get_by_id(FIXTURE_TOOL_ID)

        if existing is None:
            repo.create(
                ToolOrm(
                    tool_id=FIXTURE_TOOL_ID,
                    tool_name=FIXTURE_TOOL_NAME,
                    description=FIXTURE_DESCRIPTION,
                    execution_code=FIXTURE_EXECUTION_CODE,
                    code_language=FIXTURE_CODE_LANGUAGE,
                    code_version=FIXTURE_CODE_VERSION,
                    execution_strategy=FIXTURE_EXECUTION_STRATEGY,
                    source=FIXTURE_SOURCE,
                    trial_success_count=FIXTURE_TRIAL_SUCCESS_COUNT,
                    status="published",
                )
            )
            logger.info("Grand tour fixture skill created: %s", FIXTURE_TOOL_ID)
            return {
                "fixture_tool_id": FIXTURE_TOOL_ID,
                "created": True,
                "skipped": False,
                "repaired": False,
            }

        # 防御性字段修正：正常路径不会漂移，但 sidecar 跨版本重启时容错。
        drifted = False
        if existing.status != "published":
            existing.status = "published"
            drifted = True
        if existing.source != FIXTURE_SOURCE:
            existing.source = FIXTURE_SOURCE
            drifted = True
        if existing.execution_strategy != FIXTURE_EXECUTION_STRATEGY:
            existing.execution_strategy = FIXTURE_EXECUTION_STRATEGY
            drifted = True
        if existing.execution_code != FIXTURE_EXECUTION_CODE:
            existing.execution_code = FIXTURE_EXECUTION_CODE
            drifted = True
        if drifted:
            repo.update(existing)
            logger.info("Grand tour fixture skill repaired: %s", FIXTURE_TOOL_ID)

        return {
            "fixture_tool_id": FIXTURE_TOOL_ID,
            "created": False,
            "skipped": False,
            "repaired": drifted,
        }
    except Exception:
        active_session.rollback()
        logger.error("Grand tour fixture skill injection failed", exc_info=True)
        raise
    finally:
        if owns_session:
            active_session.close()

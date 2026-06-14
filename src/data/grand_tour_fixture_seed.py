"""Data-owned defaults for the Real Grand Tour fixture skill.

仅在 grand-tour 真实 E2E 环境（MEXEMPLAR_REAL_GRAND_TOUR=1）下由
``grand_tour_fixture_service.ensure_fixture_skill()`` 幂等注入到 ToolRepository，
作为技能组合"至少 2 个成员"契约的第二成员占位。生产环境绝不注入。

前端测试常量 ``frontend/tests/e2e/helpers/grand-tour-fixture-constants.ts``
的 ``GRAND_TOUR_FIXTURE_SKILL_NAME`` 必须与本文件 ``FIXTURE_TOOL_NAME`` 保持一致。
"""

FIXTURE_TOOL_ID = "fixture.grand_tour.echo"
FIXTURE_TOOL_NAME = "Grand Tour Fixture Echo"
FIXTURE_DESCRIPTION = (
    "Safe local no-op fixture skill for the Real Grand Tour E2E composition "
    "validation. Returns a fixed success message without side effects."
)
FIXTURE_SOURCE = "test_fixture"
FIXTURE_EXECUTION_STRATEGY = "api"
FIXTURE_CODE_LANGUAGE = "python"
FIXTURE_CODE_VERSION = "1.0"
FIXTURE_TRIAL_SUCCESS_COUNT = 3

# 符合 src/execution/tool_executor.py run_tool_code 契约：
# venv 子进程跑 ``asyncio.run(mod.execute(**params))``；无 import → 不触发 pip install，零副作用。
FIXTURE_EXECUTION_CODE = '''async def execute(**kwargs):
    return {
        "success": True,
        "message": "Fixture skill executed successfully. This is a safe no-op validation stub.",
        "data": {"fixture": True, "received_params": dict(kwargs)},
    }
'''

"""Real Grand Tour fixture skill 注入行为契约测试。

验证 ensure_fixture_skill() 的 env gate、幂等、漂移修正、组合集成与执行码契约。
in_memory_db (tests/conftest.py autouse) 提供每个用例独立的 in-memory DB。
"""

import ast

from src.business.services.grand_tour_fixture_service import ensure_fixture_skill
from src.data.grand_tour_fixture_seed import (
    FIXTURE_EXECUTION_CODE,
    FIXTURE_EXECUTION_STRATEGY,
    FIXTURE_SOURCE,
    FIXTURE_TOOL_ID,
    FIXTURE_TOOL_NAME,
)
from src.data.models_sqlite import Tool as ToolOrm
from src.data.repositories import ToolRepository


def _get_fixture() -> ToolOrm | None:
    with ToolRepository() as repo:
        return repo.get_by_id(FIXTURE_TOOL_ID)


def test_skips_when_env_not_set(monkeypatch):
    monkeypatch.delenv("MEXEMPLAR_REAL_GRAND_TOUR", raising=False)

    result = ensure_fixture_skill()

    assert result["skipped"] is True
    assert result["created"] is False
    assert _get_fixture() is None


def test_creates_when_env_set_and_missing(monkeypatch):
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")

    result = ensure_fixture_skill()

    assert result["created"] is True
    fixture = _get_fixture()
    assert fixture is not None
    assert fixture.tool_id == FIXTURE_TOOL_ID
    assert fixture.tool_name == FIXTURE_TOOL_NAME
    assert fixture.status == "published"
    assert fixture.source == FIXTURE_SOURCE
    assert fixture.execution_strategy == FIXTURE_EXECUTION_STRATEGY
    assert fixture.execution_code == FIXTURE_EXECUTION_CODE
    assert fixture.trial_success_count == 3


def test_idempotent_on_repeat(monkeypatch):
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")

    first = ensure_fixture_skill()
    second = ensure_fixture_skill()

    assert first["created"] is True
    assert second["created"] is False
    assert second["repaired"] is False
    with ToolRepository() as repo:
        count = repo.session.query(ToolOrm).filter(ToolOrm.tool_id == FIXTURE_TOOL_ID).count()
    assert count == 1


def test_repairs_drifted_fields(monkeypatch):
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    # 预先注入一个字段漂移的 fixture（模拟跨版本重启残留）
    with ToolRepository() as repo:
        repo.create(
            ToolOrm(
                tool_id=FIXTURE_TOOL_ID,
                tool_name=FIXTURE_TOOL_NAME,
                status="pending",
                source="manual",
                execution_strategy="browser",
            )
        )

    result = ensure_fixture_skill()

    assert result["created"] is False
    assert result["repaired"] is True
    fixture = _get_fixture()
    assert fixture is not None
    assert fixture.status == "published"
    assert fixture.source == FIXTURE_SOURCE
    assert fixture.execution_strategy == FIXTURE_EXECUTION_STRATEGY
    assert fixture.execution_code == FIXTURE_EXECUTION_CODE


def test_fixture_passes_composition_normalizer(monkeypatch):
    """fixture + 一个普通 published tool 必须能过组合创建校验（根因回归保护）。"""
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    ensure_fixture_skill()
    with ToolRepository() as repo:
        repo.create(
            ToolOrm(
                tool_id="tool_normal_member",
                tool_name="普通成员技能",
                status="published",
            )
        )

    from src.business.services import SkillCompositionService

    composition = SkillCompositionService().create_composition(
        composition_name="fixture-integration",
        description="集成测试组合",
        applicability="验证 fixture 能进组合",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": FIXTURE_TOOL_ID, "selected_order": 1, "execution_order": None},
            {"tool_id": "tool_normal_member", "selected_order": 2, "execution_order": None},
        ],
    )

    assert composition.status == "draft"
    member_ids = {member.tool_id for member in composition.members}
    assert FIXTURE_TOOL_ID in member_ids


def test_fixture_execution_code_satisfies_run_tool_code_contract():
    """FIXTURE_EXECUTION_CODE 语法正确且提供 run_tool_code 要求的 async execute。

    真实子进程执行由 grand-tour E2E 覆盖；单测层只校验契约结构，避免 venv 依赖。
    """
    tree = ast.parse(FIXTURE_EXECUTION_CODE)
    func_defs = [
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    execute_defs = [node for node in func_defs if node.name == "execute"]
    assert execute_defs, "execution_code 必须定义 execute 函数"
    assert any(
        isinstance(node, ast.AsyncFunctionDef) for node in execute_defs
    ), "execute 必须是 async def（run_tool_code 跑 asyncio.run(mod.execute))"
    # 参数契约：**kwargs 收任意入参，组合 dispatch 不会因参数不匹配报错
    execute_node = execute_defs[0]
    assert execute_node.args.kwarg is not None, "execute 必须声明 **kwargs"

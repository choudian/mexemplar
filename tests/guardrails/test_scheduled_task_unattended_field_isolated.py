"""T025: guard — ``unattended_auto_approve`` 三重不暴露（CC-005 / FR-025，比 031 更严）。

三层静态断言（``inspect.getsource``）：

1. **5 个工具 schema 的 ``properties``** 不含 ``unattended_auto_approve`` 键；
2. **5 个 handler 源码** 不含 ``unattended_auto_approve`` 字符串；
3. **router create/update 源码** 不含 ``unattended_auto_approve`` 字符串（snake_case）。

该字段唯一写入路径 = 创建确认卡勾选（POST confirmations/{id}/decision）+ 详情页 PATCH 开关。
前者经 router decision endpoint 按位置传入 manager（router 源码只见 camelCase ``unattendedAutoApprove``）；
后者经 PATCH endpoint 调 ``service.set_unattended``（方法名不含字段名）。
"""

from __future__ import annotations

import inspect

from src.business.agents.tools import assistant_tools
from src.desktop_api.routers import scheduled_tasks as scheduled_tasks_router

GUARDED_FIELD = "unattended_auto_approve"

SCHEDULED_TOOL_SCHEMAS = [
    "CREATE_SCHEDULED_TASK_SCHEMA",
    "LIST_SCHEDULED_TASKS_SCHEMA",
    "UPDATE_SCHEDULED_TASK_SCHEMA",
    "PAUSE_SCHEDULED_TASK_SCHEMA",
    "DELETE_SCHEDULED_TASK_SCHEMA",
]

SCHEDULED_TOOL_HANDLER_FACTORIES = [
    "create_create_scheduled_task_handler",
    "create_list_scheduled_tasks_handler",
    "create_update_scheduled_task_handler",
    "create_pause_scheduled_task_handler",
    "create_delete_scheduled_task_handler",
]


# ---------------------------------------------------------------------------
# 层 1：工具 schema properties 不含该字段
# ---------------------------------------------------------------------------


def test_tool_schema_properties_exclude_field():
    for schema_name in SCHEDULED_TOOL_SCHEMAS:
        schema = getattr(assistant_tools, schema_name)
        props = schema["function"]["parameters"]["properties"]
        assert GUARDED_FIELD not in props, (
            f"{schema_name}.properties 含 {GUARDED_FIELD}（CC-005 违规）"
        )


# ---------------------------------------------------------------------------
# 层 2：5 个 handler 源码不含该字段字符串
# ---------------------------------------------------------------------------


def test_handler_source_excludes_field():
    for factory_name in SCHEDULED_TOOL_HANDLER_FACTORIES:
        factory = getattr(assistant_tools, factory_name)
        source = inspect.getsource(factory)
        assert GUARDED_FIELD not in source, (
            f"{factory_name} 源码含 {GUARDED_FIELD}（CC-005 违规：handler 签名或实现不得引用该字段）"
        )


# ---------------------------------------------------------------------------
# 层 3：router create/update 源码不含 snake_case 字段字符串
# ---------------------------------------------------------------------------


def test_router_source_excludes_field():
    """router 整个模块源码不得出现 ``unattended_auto_approve``（snake_case）。

    router 允许出现 camelCase ``unattendedAutoApprove``（DTO 字段访问）；
    但 snake_case Python 参数名出现在 router 源码 = 违反三重不暴露（manager 调用
    必须按位置传，不能在 router 里写 ``unattended_auto_approve=...``）。
    """
    source = inspect.getsource(scheduled_tasks_router)
    assert GUARDED_FIELD not in source, (
        f"router 源码含 {GUARDED_FIELD}（CC-005 违规：该字段只能经 manager 按位置传入或 service.set_unattended）"
    )


# ---------------------------------------------------------------------------
# 补强：确认 PATCH endpoint 能写入该字段（唯一合法路径之一）
# ---------------------------------------------------------------------------


def test_patch_endpoint_writes_field_via_service_set_unattended():
    """PATCH endpoint 经 ``service.set_unattended`` 写入（方法名不含字段名，源码静态断言已守）。

    这里只确认 service facade 有该方法（动态可用性），不真正调 DB。
    """
    from src.business.scheduling.scheduler_service import SchedulerService

    assert hasattr(SchedulerService, "set_unattended"), "SchedulerService.set_unattended missing"

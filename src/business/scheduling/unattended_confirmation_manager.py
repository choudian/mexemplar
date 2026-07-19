"""``UnattendedConfirmationManager`` —— per-task 无人值守免确认授权集（033 US5）。

**完全独立**于进程级 ``_auto_approve_enabled``（``builtin_general_tools.py`` 的进程级单一
布尔）。本管理器维护受锁保护的 authorized task-id ``set[str]``，从 SQLite
``scheduled_tasks.unattended_auto_approve=1`` 全量加载，任务开关变更时增量刷新。

四重限定（FR-024 / CC-005，硬保证）：

1. **仅 ``source='scheduled'`` 会话生效**（用户会话走原流程，``_confirm_or_reject`` 注入点
   按 session.source 判定，非 scheduled 直接 return None）；
2. **仅该 ``scheduled_task_id``**（授权集按 task id 精确匹配，不波及其他 scheduled 任务）；
3. **默认关闭**（migration v30 ``unattended_auto_approve`` 列 ``DEFAULT 0``）；
4. **只能由用户显式 UI 操作开启**（创建确认卡勾选 / 详情页 PATCH；**无工具入口**——T025
   三重不暴露门卫守住）。

爆炸半径焊死在「仅该 scheduled 会话的高危动作」；进程级 ``_auto_approve_enabled`` 的值 /
签名 / 语义完全不被本模块读写。
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class UnattendedConfirmationManager:
    """per-task 免确认授权集（内存态，启动时从 SQLite 全量加载）。

    线程安全：授权 task-id set 的公开读写均经 ``_lock`` 串行化。
    """

    def __init__(
        self,
        *,
        loader: Callable[[], list[str]] | None = None,
    ) -> None:
        """``loader``：返回授权任务 id 列表的 callback（默认走 ScheduledTaskRepository）。

        注入 callback 避免 business 直接 import data 层具体 Repository（便于测试）；
        实际默认实现在 ``_default_loader`` 内部延迟构造 Repository。
        """
        self._loader = loader or _default_loader
        self._lock = threading.Lock()
        self._authorized: set[str] = set()

    # -- 全量加载 / 重载 -------------------------------------------------------

    def load_all(self) -> None:
        """sidecar lifespan 启动 / 重载时全量加载授权集。

        失败不抛，但必须 fail-closed 清空旧授权集；保留旧值会让已撤销授权在数据库
        暂时不可读时继续放行。返回值不区分空 / 非空——空集 = 没有任何 task 开启
        免确认（安全默认）。
        """
        try:
            ids = list(self._loader() or [])
        except Exception:
            with self._lock:
                self._authorized = set()
            logger.error(
                "UnattendedConfirmationManager.load_all: loader failed; "
                "cleared authorized set fail-closed",
                exc_info=True,
            )
            return
        normalized = {str(tid) for tid in ids if tid}
        with self._lock:
            self._authorized = normalized
        logger.info(
            "UnattendedConfirmationManager.load_all: %d task(s) authorized",
            len(normalized),
        )

    def reload(self) -> None:
        """``load_all`` 的语义别名（任务开关变更时调）。"""
        self.load_all()

    # -- 查询 ------------------------------------------------------------------

    def is_authorized(self, scheduled_task_id: str | None) -> bool:
        """该 task 是否在授权集（不在 / None / 空字符串 → False）。"""
        if not scheduled_task_id:
            return False
        tid = str(scheduled_task_id)
        # 查询与 load/set 共用同一锁，避免观察到授权集替换或增量更新的中间状态。
        with self._lock:
            return tid in self._authorized

    # -- 增量刷新 --------------------------------------------------------------

    def set(self, scheduled_task_id: str, enabled: bool) -> None:
        """任务开关变更时增量刷新（详情页 PATCH / 确认卡勾选落库后调）。

        优于 ``reload()`` 全量读：避免每次开关都走一次全表扫描；操作幂等。
        """
        tid = str(scheduled_task_id or "").strip()
        if not tid:
            return
        with self._lock:
            if enabled:
                self._authorized.add(tid)
            else:
                self._authorized.discard(tid)
        logger.info(
            "UnattendedConfirmationManager.set: task=%s enabled=%s",
            tid,
            bool(enabled),
        )

    # -- 测试辅助 --------------------------------------------------------------

    def snapshot(self) -> frozenset[str]:
        """返回当前授权集快照（测试断言用）。"""
        with self._lock:
            return frozenset(self._authorized)


# =============================================================================
# 默认 loader：走 ScheduledTaskRepository.list_unattended_auto_approve_task_ids
# =============================================================================


def _default_loader() -> list[str]:
    """默认授权集加载器：从 SQLite ``scheduled_tasks`` 全量读取。

    延迟 import 避免业务模块在 data 层尚未装配时炸；loader 调用失败由 ``load_all``
    的 try/except 兜底并清空旧授权集（fail-closed）。
    """
    from src.data.repos.scheduled_task_repository import ScheduledTaskRepository

    with ScheduledTaskRepository() as repo:
        return list(repo.list_unattended_auto_approve_task_ids())


# =============================================================================
# 模块级单例
# =============================================================================

_manager: UnattendedConfirmationManager | None = None
_singleton_lock = threading.Lock()


def get_unattended_confirmation_manager() -> UnattendedConfirmationManager:
    """模块级单例（sidecar lifespan 启动时调 ``load_all``）。"""
    global _manager
    if _manager is None:
        with _singleton_lock:
            if _manager is None:
                _manager = UnattendedConfirmationManager()
    return _manager


def reset_state_for_tests(
    *,
    loader: Callable[[], list[str]] | None = None,
    authorized: Any | None = None,
) -> UnattendedConfirmationManager:
    """测试用：重置单例 + 可选注入 loader / 初始授权集。

    Args:
        loader: 可选自定义 loader（默认 None → 保留默认 ``_default_loader``）。
        authorized: 可选 ``set[str]`` / ``list[str]``，直接覆盖授权集（跳过 loader）。
            传空集合 = 没有任何 task 授权。
    """
    global _manager
    with _singleton_lock:
        _manager = UnattendedConfirmationManager(loader=loader)
        if authorized is not None:
            normalized = {str(tid) for tid in (authorized or []) if tid}
            # 直接走 private 字段赋值，跳过 loader（测试场景受控）
            _manager._authorized = normalized  # type: ignore[private-attribute]
    return _manager

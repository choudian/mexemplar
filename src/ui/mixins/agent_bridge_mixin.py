"""
AgentBridgeMixin — AgentUIBridge 初始化与生命周期管理

包含 MainWindow 中与 AgentUIBridge 创建、预热、确保就绪相关的全部方法。
OrchestratorInitStatus 枚举也定义在此处。
"""

import threading
from enum import Enum

from src.ui.page_ids import INTENT_CONFIRMATION


class OrchestratorInitStatus(Enum):
    """AgentUIBridge 初始化状态枚举"""

    NOT_STARTED = "not_started"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"


class AgentBridgeMixin:
    """AgentUIBridge 初始化管理 Mixin，由 MainWindow 混入使用"""

    _BRIDGE_INIT_ERROR_TEMPLATE = (
        "Agent 编排器初始化失败：\n{}\n\n录制功能仍可使用，但不会自动启动 Agent。"
    )

    def _mark_bridge_ready(self, bridge) -> None:
        with self._orchestrator_init_condition:
            self.agent_ui_bridge = bridge
            self._pending_bridge = None
            self._orchestrator_init_status = OrchestratorInitStatus.READY
            self._orchestrator_init_condition.notify_all()

    def _mark_bridge_failed(self, error: str) -> None:
        with self._orchestrator_init_condition:
            self._orchestrator_init_status = OrchestratorInitStatus.FAILED
            self._orchestrator_init_error = str(error)
            self.agent_ui_bridge = None
            self._orchestrator_init_condition.notify_all()

    def _warmup_orchestrator_async(self) -> None:
        """异步预热 AgentUIBridge（后台线程），应用启动时自动调用"""

        def warmup():
            try:
                with self._orchestrator_init_condition:
                    if self._orchestrator_init_status == OrchestratorInitStatus.READY:
                        self.logger.info("AgentUIBridge already ready, skipping warmup")
                        return
                    self._orchestrator_init_status = OrchestratorInitStatus.INITIALIZING
                    self.logger.info("Warming up AgentUIBridge in background...")

                bridge = self._create_agent_ui_bridge()
                self._mark_bridge_ready(bridge)
                self.logger.info("AgentUIBridge warmup completed")

            except Exception as e:
                self._mark_bridge_failed(str(e))
                self.logger.error(f"AgentUIBridge warmup failed: {e}", exc_info=True)

        self._orchestrator_warmup_thread = threading.Thread(
            target=warmup, daemon=False, name="OrchestratorWarmup"
        )
        self._orchestrator_warmup_thread.start()
        self.logger.info("AgentUIBridge warmup thread started")

    def _create_agent_ui_bridge(self):
        """创建 AgentUIBridge 实例（内部方法）"""
        from src.business.agents.tools.builtin_general_tools import register_confirm_mechanism
        from src.business.ai.llm_client import LangChainLLMClient
        from src.business.orchestration.agent_orchestrator import AgentOrchestrator
        from src.data.unified_config import get_unified_config
        from src.ui.agent_ui_bridge import AgentUIBridge
        from src.utils.events import connect, event_value

        config = get_unified_config()
        llm_client = LangChainLLMClient(
            provider=config.get_ai_provider(),
            model=config.get_ai_model(),
            api_key=config.get_ai_api_key(),
            base_url=config.get_ai_base_url(),
            temperature=0.7,
        )

        orchestrator = AgentOrchestrator(llm_client=llm_client, config=config)
        bridge = AgentUIBridge(orchestrator)

        # 注册高危工具跨线程确认机制
        try:
            self._confirm_action_signal.disconnect(self._on_confirm_action_requested)
        except TypeError:
            pass
        self._confirm_action_signal.connect(self._on_confirm_action_requested)
        register_confirm_mechanism(self._confirm_action_signal)

        orchestrator.task_worker.start()

        bridge.question_received.connect(self._on_agent_question)
        bridge.error_occurred.connect(self._on_agent_error)
        bridge.progress_updated.connect(self._on_agent_progress)
        bridge.tool_saved_signal.connect(self._on_tool_saved)
        bridge.tool_published_signal.connect(self._on_tool_published)
        bridge.retry_failed_signal.connect(self._on_retry_failed)
        bridge.failure_updated_signal.connect(self._on_failure_updated)
        self.logger.info("AgentUIBridge 信号已连接")

        self._pending_bridge = bridge
        for sig, slot in [
            (self._agent_start_requested, self._on_agent_start_requested),
            (self._switch_to_intent_page, self._on_switch_to_intent_page),
        ]:
            try:
                sig.disconnect(slot)
            except TypeError:
                pass
            sig.connect(slot)

        def on_recording_completed(sender, **kwargs):
            event_data = kwargs.get("event_data")
            recording_id = event_value(event_data, "recording_id", "session_id") or kwargs.get("recording_id")
            if not recording_id:
                return
            self.logger.info(f"[录制完成] 通过主线程信号启动 PM Agent 分析: {recording_id}")
            self._agent_start_requested.emit(recording_id)

        self._on_recording_completed_handler = on_recording_completed
        connect("recording_completed", self._on_recording_completed_handler)
        self.logger.info("已开始监听录制完成事件")

        return bridge

    def _on_switch_to_intent_page(self) -> None:
        """在主线程中重置意图确认页面并切换（由 _switch_to_intent_page 信号触发）"""
        self.intent_confirmation_page.reset()
        self.recording_page.reset()
        self.main_content.switch_page(INTENT_CONFIRMATION)

    def _on_agent_start_requested(self, recording_id: str) -> None:
        """在主线程中启动 PM Agent（由 _agent_start_requested 信号触发）"""
        bridge = getattr(self, "_pending_bridge", None) or self.agent_ui_bridge
        if not bridge:
            self.logger.error("AgentUIBridge 不可用，无法启动 Agent")
            return
        self.logger.info(f"[主线程] 启动 PM Agent 分析: {recording_id}")
        bridge.start_agent(
            "pm",
            f"请分析录制 {recording_id} 的操作流程，理解用户想要自动化的任务，并与用户确认需求。",
            recording_id,
        )

    def _on_ensure_bridge_requested(self) -> None:
        """UI 线程槽：在 UI 线程中创建 AgentUIBridge（由 _ensure_bridge_requested 信号触发）"""
        try:
            self.logger.info("Creating AgentUIBridge on UI thread (via signal)...")
            bridge = self._create_agent_ui_bridge()
            self._mark_bridge_ready(bridge)
            self.logger.info("AgentUIBridge created and ready (UI thread)")

        except Exception as e:
            self._mark_bridge_failed(str(e))
            self.logger.error(f"AgentUIBridge initialization failed (UI thread): {e}", exc_info=True)
            self.recording_error.emit(
                self._BRIDGE_INIT_ERROR_TEMPLATE.format(str(e))
            )
        finally:
            self._bridge_created_event.set()

    def _ensure_agent_bridge(self, timeout: float = 5.0) -> bool:
        """智能确保 AgentUIBridge 已初始化（懒加载 + 预热支持）"""
        with self._orchestrator_init_condition:
            if (
                self._orchestrator_init_status == OrchestratorInitStatus.READY
                and self.agent_ui_bridge
            ):
                return True

            if self._orchestrator_init_status == OrchestratorInitStatus.INITIALIZING:
                self.logger.info(f"AgentUIBridge is warming up, waiting up to {timeout} seconds...")
                self._orchestrator_init_condition.wait(timeout=timeout)

                if self._orchestrator_init_status == OrchestratorInitStatus.READY:
                    return True

            if self._orchestrator_init_status == OrchestratorInitStatus.FAILED:
                self.logger.warning(
                    f"Previous warmup failed: {self._orchestrator_init_error}, recreating..."
                )

            if self.agent_ui_bridge is not None:
                return True

            self._orchestrator_init_status = OrchestratorInitStatus.INITIALIZING

        is_ui_thread = threading.current_thread() is threading.main_thread()
        if not is_ui_thread:
            self._bridge_created_event.clear()
            self._ensure_bridge_requested.emit()
            self._bridge_created_event.wait(timeout=timeout)
            with self._orchestrator_init_condition:
                return self._orchestrator_init_status == OrchestratorInitStatus.READY
        else:
            try:
                self.logger.info("Creating AgentUIBridge immediately...")
                bridge = self._create_agent_ui_bridge()
                self._mark_bridge_ready(bridge)
                self.logger.info("AgentUIBridge created and ready")
                return True

            except Exception as e:
                self._mark_bridge_failed(str(e))
                self.logger.error(f"AgentUIBridge initialization failed: {e}", exc_info=True)
                self.recording_error.emit(
                    self._BRIDGE_INIT_ERROR_TEMPLATE.format(str(e))
                )
                return False

"""
AgentHandlerMixin — Agent 事件处理

包含 MainWindow 中响应 AgentUIBridge 信号、处理用户与 Agent 交互的全部方法：
- Agent 提问/进度/错误响应
- 工具保存/发布/试用/删除/更新
- 意图确认与 Agent 恢复
- 教学失败重试
"""

import time
from collections import deque

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox

from src.business.agents.config import AgentType, ResultType
from src.business.agents.tools.builtin_general_tools import (
    CONFIRM_SOURCE_AUTO_SCOPE,
    CONFIRM_SOURCE_NEW_CHAT_RESET,
    CONFIRM_SOURCE_TOAST_ACCEPT,
    CONFIRM_SOURCE_TOAST_ALLOW_ALL,
    CONFIRM_SOURCE_TOAST_REJECT,
    CONFIRM_SOURCE_TOAST_TIMEOUT,
    CONFIRM_SOURCE_TOP_TOGGLE,
    get_confirmation_remaining_timeout_ms,
    get_pending_confirmation,
    is_auto_approve_enabled,
    reset_auto_approve,
    set_auto_approve_enabled,
    set_confirm_result,
    settle_pending_confirmations,
)
from src.business.services import SkillCompositionError, SkillCompositionService, SkillsService
from src.ui.page_ids import CONVERSATIONS, INTENT_CONFIRMATION, SKILLS
from src.ui.widgets.auth_toast import (
    DECISION_ACCEPT,
    DECISION_ALLOW_ALL,
    DECISION_REJECT,
    DECISION_TIMEOUT,
    AuthToastSurface,
)

COMPOSITION_TRIAL_AGENT_TYPE = "composition_trial"


class AgentHandlerMixin:
    """Agent 事件处理 Mixin，由 MainWindow 混入使用"""

    # ------------------------------------------------------------------
    # Agent 提问 / 进度 / 错误
    # ------------------------------------------------------------------

    def _on_agent_question(
        self, workflow_id: str, session_id: str, agent_type: str, question: str
    ) -> None:
        """处理 Agent 提问（需要用户回答）"""
        self.logger.info(
            f"Agent 提问: workflow={workflow_id}, session={session_id}, "
            f"type={agent_type}, question={question[:80]}"
        )

        if agent_type == AgentType.ASSISTANT:
            self._current_agent_type = agent_type
            chat_widget = self._get_chat_widget()
            if chat_widget:
                chat_widget.add_assistant_message(question)
                chat_widget.set_loading(False)
            return

        self._current_agent_workflow_id = workflow_id
        self._current_agent_type = agent_type

        if agent_type == AgentType.TRIAL:
            self.main_content.switch_page(INTENT_CONFIRMATION)
            intent_page = self.main_content.get_page(INTENT_CONFIRMATION)
            if intent_page:
                intent_page.add_trial_question(question, workflow_id)
            return

        self._show_intent_confirmation_from_agent({"message": question}, question, workflow_id)

    def _on_agent_progress(self, workflow_id: str, event_name: str) -> None:
        """处理 Agent 进度事件"""
        self.logger.info(f"Agent 进度: workflow={workflow_id}, event={event_name}")

        if event_name == "requirement_confirmed":
            self._show_toast("技能学习中，稍后回来…", auto_dismiss_ms=10000)
            QTimer.singleShot(2000, self._switch_to_welcome_page)

    def _on_agent_error(
        self, workflow_id: str, session_id: str, agent_type: str, error_message: str
    ) -> None:
        """处理 Agent 错误"""
        self.logger.error(
            f"Agent 错误: workflow={workflow_id}, session={session_id}, "
            f"type={agent_type} - {error_message}"
        )

        if agent_type == AgentType.ASSISTANT:
            chat = self._get_chat_widget()
            if chat:
                chat.add_error_message(error_message)
                chat.set_loading(False)
            return

        try:
            display_type = AgentType(agent_type).display_name
        except ValueError:
            display_type = agent_type
        truncated = self._truncate_error(error_message)
        self._show_toast(
            f"{display_type}遇到问题：{truncated}", auto_dismiss_ms=15000, toast_type="error"
        )

        if agent_type == AgentType.PM:
            self._switch_to_welcome_page()

    # ------------------------------------------------------------------
    # 工具保存 / 发布
    # ------------------------------------------------------------------

    def _on_tool_saved(self, workflow_id: str, tool_id: str, from_triage: bool = False) -> None:
        """工具入库后弹 toast 通知"""
        self.logger.info(
            f"工具已入库: workflow={workflow_id}, tool_id={tool_id}, from_triage={from_triage}"
        )
        self._schedule_skills_refresh(full=True)
        if from_triage:
            self.main_content.switch_page(INTENT_CONFIRMATION)
            return
        QTimer.singleShot(500, self._notify_skill_learned)

    def _on_tool_published(self, workflow_id: str, tool_id: str) -> None:
        """工具发布后切换到工具列表页"""
        self.logger.info(f"工具已发布: workflow={workflow_id}, tool_id={tool_id}")
        self._schedule_skills_refresh(full=True)
        QTimer.singleShot(1500, self._switch_to_pending_tools)

    def _notify_skill_learned(self) -> None:
        """技能学习完毕后弹 toast 通知"""
        self._show_toast("技能学习完毕！可以到「技能列表」查看并开始考核。", auto_dismiss_ms=10000)

    # ------------------------------------------------------------------
    # 意图确认 / Agent 恢复
    # ------------------------------------------------------------------

    def _show_intent_confirmation_from_agent(
        self, intent_data: dict, message: str, thread_id: str
    ) -> None:
        """显示来自 Agent 的意图确认 UI"""
        self.main_content.switch_page(INTENT_CONFIRMATION)
        intent_page = self.main_content.get_page(INTENT_CONFIRMATION)
        if intent_page and hasattr(intent_page, "load_intent_from_agent"):
            intent_page.load_intent_from_agent(intent_data, message, thread_id)
        self.logger.info("已切换到意图确认页面")

    def _on_agent_resume_request(self, thread_id: str, resume_data: dict) -> None:
        """处理 Agent 恢复请求（来自 IntentConfirmationUI）"""
        self.logger.info(f"收到 Agent 恢复请求: workflow_id={thread_id}")
        user_input = resume_data.get("feedback") or resume_data.get("message", "")
        agent_type = self._current_agent_type

        if agent_type == COMPOSITION_TRIAL_AGENT_TYPE:
            self._continue_composition_trial(thread_id, user_input)
            return

        if self.agent_ui_bridge:
            try:
                self.agent_ui_bridge.reply_to_agent(agent_type, user_input, thread_id)
                self.logger.info(f"已恢复 Agent: {thread_id}")
            except Exception as e:
                self.logger.error(f"恢复 Agent 失败: {e}", exc_info=True)
        else:
            self.logger.warning("AgentUIBridge 不可用")

    def _on_intent_analyze_request(self, intent_id: str, user_message: str) -> None:
        """处理意图分析请求（IntentConfirmationUI 信号）"""
        self.logger.info(f"收到意图分析请求: {intent_id}, 消息: {user_message[:50]}...")
        workflow_id = self._current_agent_workflow_id
        agent_type = self._current_agent_type or AgentType.PM

        if not workflow_id:
            self.logger.warning("没有活跃的 Agent 会话")
            return

        if not self.agent_ui_bridge:
            self.logger.warning("AgentUIBridge 不可用")
            return

        try:
            self.agent_ui_bridge.reply_to_agent(agent_type, user_message, workflow_id)
            self.logger.info(f"已传递用户反馈给 Agent: {workflow_id}")
            intent_page = self.main_content.get_page(INTENT_CONFIRMATION)
            if intent_page:
                intent_page.set_status_text("正在处理您的反馈...")
        except Exception as e:
            self.logger.error(f"传递用户反馈失败: {e}", exc_info=True)

    def _on_intent_cancel_requested(self) -> None:
        """处理统一对话页的取消请求。"""
        self.logger.info("收到统一对话页取消请求")

        if self._composition_trial_thread and self._composition_trial_thread.isRunning():
            try:
                self._composition_trial_thread.cancel()
            except Exception as e:
                self.logger.warning(f"取消技能组合试用线程失败: {e}")

        current_type = self._current_agent_type
        self._composition_trial_thread = None
        self._current_composition_trial_session_id = None
        self._current_agent_workflow_id = None
        self._current_agent_type = None

        if current_type in {AgentType.TRIAL, COMPOSITION_TRIAL_AGENT_TYPE}:
            self.main_content.switch_page(SKILLS)
            return

        self.main_content.switch_page(CONVERSATIONS)

    # ------------------------------------------------------------------
    # Chat 发送消息 / 确认弹框
    # ------------------------------------------------------------------

    def _on_chat_send_message(self, session_id: str, agent_type: str, user_input: str) -> None:
        """ChatWidget 发送消息 → 通过 UIBridge 启动 Agent"""
        self.logger.info(f"Chat 发送消息: session={session_id}, input={user_input[:50]}...")
        if self.agent_ui_bridge is not None:
            self.agent_ui_bridge.start_agent(
                agent_type=agent_type, user_input=user_input, session_id=session_id
            )
        else:
            self.logger.warning("[MainWindow] agent_ui_bridge 未初始化")
            chat = self._get_chat_widget()
            if chat:
                chat.add_error_message("AI 助手尚未初始化，请稍候...")
                chat.set_loading(False)

    def _on_confirm_action_requested(self, request_id: str, message: str) -> None:
        """UI 线程槽：收到 worker 线程的确认请求后显示非阻塞确认浮层。"""
        pending = get_pending_confirmation(request_id)
        if pending is None or pending.event.is_set():
            return

        if pending.created_at <= self._auth_confirm_ignore_before:
            set_confirm_result(request_id, False, CONFIRM_SOURCE_NEW_CHAT_RESET)
            return

        if is_auto_approve_enabled():
            set_confirm_result(request_id, True, CONFIRM_SOURCE_AUTO_SCOPE)
            self._sync_auth_toggle_state(True)
            return

        self._auth_toast_queue.append((request_id, message))
        if self._active_auth_toast is None:
            self._show_next_auth_toast()

    def _auth_toast_parent(self):
        central_widget = getattr(self, "centralWidget", lambda: None)()
        return central_widget or self

    def _show_next_auth_toast(self) -> None:
        if self._active_auth_toast is not None or not self._auth_toast_queue:
            return

        while self._auth_toast_queue:
            request_id, _message = self._auth_toast_queue.popleft()
            pending = get_pending_confirmation(request_id)
            if pending is None or pending.event.is_set():
                continue
            if pending.created_at <= self._auth_confirm_ignore_before:
                set_confirm_result(request_id, False, CONFIRM_SOURCE_NEW_CHAT_RESET)
                continue

            remaining_ms = get_confirmation_remaining_timeout_ms(request_id)
            if remaining_ms is None:
                continue
            if remaining_ms <= 0:
                set_confirm_result(request_id, False, CONFIRM_SOURCE_TOAST_TIMEOUT)
                continue

            toast = AuthToastSurface(
                request_id=request_id,
                tool_name=pending.tool_name,
                summary=pending.summary,
                timeout_ms=remaining_ms,
                parent=self._auth_toast_parent(),
            )
            toast.decision_made.connect(self._on_auth_toast_decision)
            toast.adjustSize()
            self._active_auth_toast = toast
            self._position_active_auth_toast()
            toast.show()
            toast.raise_()
            self._position_active_notification_toast()
            return

        self._position_active_notification_toast()

    def _on_auth_toast_decision(self, request_id: str, decision: str) -> None:
        show_next = True
        if decision == DECISION_ALLOW_ALL:
            set_auto_approve_enabled(True, CONFIRM_SOURCE_TOAST_ALLOW_ALL)
            set_confirm_result(request_id, True, CONFIRM_SOURCE_TOAST_ALLOW_ALL)
            self._sync_auth_toggle_state(True)
            self._drain_auth_toast_queue(True, CONFIRM_SOURCE_TOAST_ALLOW_ALL)
            show_next = False
        elif decision == DECISION_ACCEPT:
            set_confirm_result(request_id, True, CONFIRM_SOURCE_TOAST_ACCEPT)
        elif decision == DECISION_REJECT:
            set_confirm_result(request_id, False, CONFIRM_SOURCE_TOAST_REJECT)
        elif decision == DECISION_TIMEOUT:
            set_confirm_result(request_id, False, CONFIRM_SOURCE_TOAST_TIMEOUT)
        else:
            set_confirm_result(request_id, False, CONFIRM_SOURCE_TOAST_REJECT)

        self._clear_active_auth_toast()
        if show_next:
            self._show_next_auth_toast()
        else:
            self._position_active_notification_toast()

    def _clear_active_auth_toast(self) -> None:
        toast = self._active_auth_toast
        self._active_auth_toast = None
        if toast is not None:
            toast.deleteLater()

    def _drain_auth_toast_queue(self, approved: bool, source: str) -> None:
        queued = list(self._auth_toast_queue)
        self._auth_toast_queue.clear()
        for queued_request_id, _message in queued:
            set_confirm_result(queued_request_id, approved, source)

    @staticmethod
    def _move_to_bottom_right(widget, parent, margin=16):
        x = max(margin, parent.width() - widget.width() - margin)
        y = max(margin, parent.height() - widget.height() - margin)
        widget.move(x, y)

    def _position_active_auth_toast(self) -> None:
        if self._active_auth_toast is None:
            return
        self._move_to_bottom_right(self._active_auth_toast, self._auth_toast_parent())

    def _position_active_notification_toast(self, toast=None):
        """no-op 基方法，由 MainWindow 覆盖。"""

    def _sync_auth_toggle_state(self, enabled: bool) -> None:
        chat = self._get_chat_widget() if hasattr(self, "_get_chat_widget") else None
        if chat and hasattr(chat, "set_auto_approve_enabled"):
            chat.set_auto_approve_enabled(enabled)

    def _on_chat_auto_approve_toggled(self, enabled: bool) -> None:
        set_auto_approve_enabled(enabled, CONFIRM_SOURCE_TOP_TOGGLE)
        self._sync_auth_toggle_state(enabled)
        if not enabled:
            return

        active = self._active_auth_toast
        if active is not None:
            set_confirm_result(active.request_id, True, CONFIRM_SOURCE_TOP_TOGGLE)
            self._clear_active_auth_toast()
        self._drain_auth_toast_queue(True, CONFIRM_SOURCE_TOP_TOGGLE)
        self._position_active_notification_toast()

    def _settle_auth_confirmations_for_new_chat(self) -> None:
        self._auth_confirm_ignore_before = time.monotonic()
        active = self._active_auth_toast
        if active is not None:
            set_confirm_result(active.request_id, False, CONFIRM_SOURCE_NEW_CHAT_RESET)
            self._clear_active_auth_toast()
        self._drain_auth_toast_queue(False, CONFIRM_SOURCE_NEW_CHAT_RESET)
        settle_pending_confirmations(
            False,
            CONFIRM_SOURCE_NEW_CHAT_RESET,
            created_before=self._auth_confirm_ignore_before,
        )
        reset_auto_approve()
        self._sync_auth_toggle_state(False)
        self._position_active_notification_toast()

    def _on_chat_new_chat_started(self) -> None:
        self._settle_auth_confirmations_for_new_chat()

    # ------------------------------------------------------------------
    # 工具试用 / 删除 / 更新
    # ------------------------------------------------------------------

    def _on_trial_start_request(self, pending_tool_id: str) -> None:
        """处理工具试用请求（PendingToolsUI 信号）"""
        self.logger.info(f"收到工具试用请求: {pending_tool_id}")

        try:
            workflow_id = SkillsService().get_tool_workflow_id(pending_tool_id)
            if not workflow_id:
                return
        except Exception as e:
            self.logger.error(f"查询工具失败: {e}", exc_info=True)
            return

        if not self._ensure_agent_bridge():
            self.logger.error("AgentUIBridge 不可用，无法启动试用 Agent")
            return

        self._current_agent_workflow_id = workflow_id
        self._current_agent_type = AgentType.TRIAL

        try:
            messages = self.agent_ui_bridge.get_trial_messages(workflow_id)
        except Exception as e:
            self.logger.error(f"查询 trial 历史消息失败: {e}", exc_info=True)
            messages = []

        self.main_content.switch_page(INTENT_CONFIRMATION)

        if messages:
            display_messages = (
                messages[:-1] if messages[-1].get("role") == "assistant" else messages
            )
            self.intent_confirmation_page.preload_trial_history(display_messages)
            self.logger.info(
                f"预加载 trial 历史: workflow_id={workflow_id}, count={len(display_messages)}"
            )
        else:
            self.intent_confirmation_page.preload_trial_history([])

        self.logger.info(f"启动 trial Agent: workflow_id={workflow_id}")
        user_input = None if messages else "开始试用"
        self.agent_ui_bridge.start_agent(AgentType.TRIAL, user_input, workflow_id)

    def _on_composition_trial_request(self, composition_id: str) -> None:
        """处理技能组合试一下请求，切到统一对话页。"""
        self.logger.info(f"收到技能组合试用请求: {composition_id}")

        service = SkillCompositionService()
        try:
            session = service.start_trial_session(composition_id)
        except SkillCompositionError as e:
            QMessageBox.warning(self, "技能组合试用失败", str(e))
            return
        except Exception as e:
            self.logger.error(f"初始化技能组合试用失败: {e}", exc_info=True)
            QMessageBox.warning(self, "技能组合试用失败", str(e))
            return

        self._current_agent_workflow_id = session.composition_id
        self._current_agent_type = COMPOSITION_TRIAL_AGENT_TYPE
        self._current_composition_trial_session_id = session.session_id

        self.main_content.switch_page(INTENT_CONFIRMATION)
        self.intent_confirmation_page.preload_trial_history([])
        self.intent_confirmation_page.set_trial_processing_state("正在启动技能组合试用...")
        self._continue_composition_trial(
            session.session_id,
            service.build_trial_bootstrap_input(),
            status_text="正在启动技能组合试用...",
        )
        self.logger.info(
            f"已启动技能组合对话式试用: composition={composition_id}, session={session.session_id}"
        )

    def _continue_composition_trial(
        self,
        session_id: str,
        user_input: object,
        status_text: str = "正在试用技能组合...",
    ) -> None:
        """继续技能组合对话式试用。"""
        composition_id = self._current_agent_workflow_id
        if not composition_id or not session_id.strip():
            self.logger.warning("技能组合试用上下文丢失，无法继续")
            return
        if (
            self._current_composition_trial_session_id
            and session_id != self._current_composition_trial_session_id
        ):
            self.logger.warning(
                "忽略过期技能组合试用会话: "
                f"current={self._current_composition_trial_session_id}, got={session_id}"
            )
            return

        from src.ui.skill_composition_dialogs import SkillCompositionExecutionThread

        intent_page = self.main_content.get_page(INTENT_CONFIRMATION)
        if intent_page:
            intent_page.set_trial_processing_state(status_text)

        execution_thread = SkillCompositionExecutionThread(
            composition_id=composition_id,
            session_id=session_id,
            user_input=user_input.strip() if isinstance(user_input, str) else user_input,
        )
        self._composition_trial_thread = execution_thread
        execution_thread.finished_signal.connect(self._on_composition_trial_finished)
        execution_thread.finished.connect(execution_thread.deleteLater)
        execution_thread.finished.connect(self._clear_composition_trial_thread)
        execution_thread.start()

    def _on_composition_trial_finished(self, success: bool, payload: object, error: str) -> None:
        """消费技能组合试用线程结果并更新对话页。"""
        active_session_id = self._current_composition_trial_session_id
        if not active_session_id:
            self.logger.info("技能组合试用结果已忽略：会话已取消或已结束")
            return

        intent_page = self.main_content.get_page(INTENT_CONFIRMATION)
        if not intent_page:
            return

        result = payload if isinstance(payload, dict) else {}
        reply = str(result.get("reply") or "").strip()
        result_type = result.get("result_type") or ""
        session_id = str(result.get("session_id") or active_session_id)
        if session_id != active_session_id:
            self.logger.warning(
                f"忽略不匹配的技能组合试用结果: active={active_session_id}, got={session_id}"
            )
            return

        if result_type == ResultType.NEEDS_USER_INPUT.value and session_id:
            intent_page.add_trial_question(
                reply or "还缺少一些信息，请继续告诉我。",
                session_id,
            )
            return

        final_message = (
            reply or error or ("技能组合试用完成。" if success else "技能组合试用失败。")
        )
        intent_page.complete_trial(session_id, final_message, success=success)
        self._current_composition_trial_session_id = None
        self._current_agent_workflow_id = None
        self._current_agent_type = None

    def _clear_composition_trial_thread(self) -> None:
        """清理当前技能组合试用线程引用。"""
        self._composition_trial_thread = None

    def _on_tool_delete_request(self, pending_tool_id: str) -> None:
        """处理工具删除请求"""
        self.logger.info(f"收到工具删除请求: {pending_tool_id}")
        # TODO: 转发到 WebSocket 或直接调用后端 API

    def _on_tool_update_request(self, pending_tool_id: str, name: str, description: str) -> None:
        """处理工具更新请求"""
        self.logger.info(f"收到工具更新请求: {pending_tool_id}, {name}")
        # TODO: 转发到 WebSocket 或直接调用后端 API

    # ------------------------------------------------------------------
    # 教学失败重试
    # ------------------------------------------------------------------

    def _on_retry_requested(self, workflow_id: str, failed_stage: str) -> None:
        """处理失败记录重试请求"""
        self.logger.info(f"收到重试请求: workflow={workflow_id}, stage={failed_stage}")
        if not self._ensure_agent_bridge():
            self.logger.warning("Orchestrator 未就绪，无法重试")
            return
        if not self.agent_ui_bridge:
            self.logger.warning("AgentUIBridge 不可用，无法重试")
            return

        if failed_stage == AgentType.PM:
            history = self.agent_ui_bridge.get_pm_messages(workflow_id)
            self.intent_confirmation_page.load_trial_history(history, workflow_id)
            self.main_content.switch_page(INTENT_CONFIRMATION)
        self.agent_ui_bridge.retry_teaching(workflow_id)

    def _on_retry_failed(self, workflow_id: str, error: str) -> None:
        """重试失败：弹 toast + 跳回欢迎页"""
        self.logger.error(f"重试失败: workflow={workflow_id}, error={error}")
        self._show_toast(
            f"重试失败：{self._truncate_error(error)}", auto_dismiss_ms=15000, toast_type="error"
        )
        self._switch_to_welcome_page()

    def _on_failure_updated(
        self, workflow_id: str, failed_stage: str, event_type: str, is_new: bool
    ) -> None:
        """失败记录状态变化：防抖刷新技能列表页。"""
        del workflow_id, failed_stage, is_new
        self._schedule_skills_refresh(full=(event_type == "resolved"))

    def _schedule_skills_refresh(self, *, full: bool) -> None:
        """防抖刷新技能页；全量刷新优先级高于仅失败记录刷新。"""
        if not hasattr(self, "_skills_refresh_timer"):
            self._skills_refresh_timer = QTimer(self)
            self._skills_refresh_timer.setSingleShot(True)
            self._skills_refresh_timer.timeout.connect(self._flush_skills_refresh)
            self._skills_refresh_full = False

        self._skills_refresh_full = self._skills_refresh_full or full
        self._skills_refresh_timer.start(200)

    def _flush_skills_refresh(self) -> None:
        """实际刷新技能页（由防抖 timer 触发）。"""
        skills_page = self.main_content.get_page(SKILLS)
        if not skills_page:
            self._skills_refresh_full = False
            return

        try:
            if self._skills_refresh_full and hasattr(skills_page, "refresh"):
                skills_page.refresh()
            elif hasattr(skills_page, "refresh_failures"):
                skills_page.refresh_failures()
        finally:
            self._skills_refresh_full = False

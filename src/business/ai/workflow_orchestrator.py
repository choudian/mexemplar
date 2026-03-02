"""
工作流编排器 - 使用 Orchestrator 模式串联完整流程

负责自动化的录制后处理流程：
录制 → 数据压缩 → Agent 处理（意图分析 → 用户确认 → 代码生成）

支持事件驱动模式：自动监听录制完成事件并处理

架构说明：
- use_agent=True（推荐）：使用 LangGraph Agent 处理，支持 interrupt 用户交互
- use_agent=False（兼容）：使用旧的 SemanticAnalyzer 直接处理（已废弃，不推荐）
"""

import logging
from typing import Dict, Any, Optional, Callable, List
from pathlib import Path
from datetime import datetime
import uuid

from src.recording.recorder import RecordingSession, Action
from src.business.ai.preprocessing import (
    DataPreprocessor,
    CompressionLevel,
    PreprocessingResult,
)
from src.data.models import Tool
from src.data.repositories import ToolRepository
from src.utils.events import (
    recording_completed,
    workflow_processing_progress,
    workflow_processing_completed,
    workflow_processing_failed,
    workflow_processing_started,
)

logger = logging.getLogger(__name__)


class ProcessingProgress:
    """处理进度信息"""

    def __init__(self, total_steps: int = 3):
        self.current_step = 0
        self.total_steps = total_steps
        self.step_name = ""
        self.message = ""
        self.percent = 0

    def update(self, step: int, step_name: str, message: str = "") -> None:
        """更新进度"""
        self.current_step = step
        self.step_name = step_name
        self.message = message
        self.percent = int((step / self.total_steps) * 100)


class WorkflowOrchestrator:
    """
    工作流编排器 - 自动化处理录制数据

    使用 Orchestrator 模式，协调各组件完成工作流处理。

    架构：
    - 数据压缩：DataPreprocessor
    - Agent 处理：AgentUIBridge（LangGraph）
    - 旧流程（兼容）：SemanticAnalyzer（已废弃）
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        compression_level: CompressionLevel = CompressionLevel.MODERATE,
        auto_process: bool = False,
        use_agent: bool = True,
        use_persistence: bool = False,
    ):
        """
        初始化工作流编排器

        Args:
            api_key: API 密钥（如果为 None，从配置中读取）
            compression_level: 数据压缩级别
            auto_process: 是否自动监听录制完成事件并处理（事件驱动模式）
            use_agent: 是否使用 Agent 模式（推荐 True）
            use_persistence: 是否使用持久化存储（Agent 状态）
        """
        # 读取 API 密钥（用于兼容模式）
        if not api_key:
            from src.data.unified_config import get_unified_config
            api_key = get_unified_config().get_ai_api_key()

        # 初始化组件
        self.preprocessor = DataPreprocessor()
        self.compression_level = compression_level
        self.auto_process = auto_process
        self.use_agent = use_agent
        self.use_persistence = use_persistence

        # Agent 模式组件
        self._agent_bridge = None
        if use_agent:
            from src.business.agent.ui_bridge import AgentUIBridge
            self._agent_bridge = AgentUIBridge(use_persistence=use_persistence)

        # 兼容模式组件（已废弃）
        self._semantic_analyzer = None
        if not use_agent:
            if not api_key:
                raise ValueError("兼容模式需要 API 密钥，请先配置或切换到 Agent 模式")
            from src.business.ai.semantic_analyzer import SemanticAnalyzer
            self._semantic_analyzer = SemanticAnalyzer(api_key=api_key)
            logger.warning("⚠️ 使用兼容模式（SemanticAnalyzer 已废弃），建议切换到 Agent 模式")

        # 进度回调
        self.on_progress: Optional[Callable[[ProcessingProgress], None]] = None

        # 事件监听器引用（用于断开连接）
        self._event_listener = None

        # 如果启用自动处理，连接事件
        if auto_process:
            self.start_listening()

        logger.info(
            "工作流编排器初始化完成 (agent={}, compression={}, auto_process={})".format(
                use_agent, compression_level.value, auto_process
            )
        )

    @property
    def agent_bridge(self):
        """获取 AgentUIBridge 实例"""
        return self._agent_bridge

    def process_recording_with_agent(
        self,
        session: RecordingSession,
        on_interrupt: Optional[Callable[[str, Dict], None]] = None,
        on_completed: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ) -> str:
        """
        使用 Agent 模式处理录制会话（推荐）

        流程：数据压缩 → Agent 处理（意图分析 → 用户确认 → 代码生成）

        Args:
            session: 录制会话数据
            on_interrupt: interrupt 回调（thread_id, interrupt_data）
            on_completed: 完成回调（thread_id）
            on_error: 错误回调（thread_id, error_message）

        Returns:
            thread_id: Agent 会话 ID（用于后续恢复）
        """
        if not self._agent_bridge:
            raise RuntimeError("Agent 模式未启用，请使用 use_agent=True 初始化")

        progress = ProcessingProgress(total_steps=2)
        thread_id = f"tool-gen-{session.recording_id}-{uuid.uuid4().hex[:8]}"

        logger.info("=" * 80)
        logger.info(f"开始处理录制会话（Agent 模式）: {session.recording_id}")
        logger.info(f"操作数量: {len(session.actions)}, 录制模式: {session.recording_mode}")
        logger.info(f"Thread ID: {thread_id}")
        logger.info("=" * 80)

        # 发送处理开始事件
        workflow_processing_started.send(self, session_id=session.recording_id)

        try:
            # 步骤1: 数据压缩
            progress.update(1, "数据压缩", "正在压缩和优化录制数据...")
            self._notify_progress(progress)
            compressed_data = self.preprocessor.preprocess(
                actions=session.actions, compression_level=self.compression_level
            )
            logger.info("✅ 步骤1完成: 数据压缩")

            # 检查压缩模型错误（用于 UI 提示）
            analysis_stats = compressed_data.metadata.get("analysis_stats", {})
            compression_model_error = analysis_stats.get("compression_model_error")

            if compression_model_error:
                # 发送警告事件（但不中断流程）
                error_message = compression_model_error.get("message", "压缩模型错误")
                logger.warning(f"压缩模型降级: {error_message}")
                # 通过 workflow_processing_failed 发送警告（但不中断）
                workflow_processing_failed.send(
                    self,
                    session_id=session.recording_id,
                    error=f"[警告] {error_message}",
                    error_type="compression_model_fallback"
                )

            # 步骤2: 启动 Agent 处理
            progress.update(2, "Agent 处理", "正在启动 Agent 处理流程...")
            self._notify_progress(progress)

            # 连接信号（如果提供了回调）
            if on_interrupt:
                self._agent_bridge.interrupt_requested.connect(
                    lambda tid, data: on_interrupt(tid, data) if tid == thread_id else None
                )
            if on_completed:
                self._agent_bridge.session_completed.connect(
                    lambda tid: on_completed(tid) if tid == thread_id else None
                )
            if on_error:
                self._agent_bridge.error_occurred.connect(
                    lambda tid, err: on_error(tid, err) if tid == thread_id else None
                )

            # 准备压缩后的数据
            compressed_dict = {
                "recording_id": session.recording_id,
                "actions": session.actions,
                "metadata": compressed_data.metadata,
                "screenshots": compressed_data.screenshots,
            }

            # 启动 Agent
            self._agent_bridge.start_tool_generation(
                thread_id=thread_id,
                compressed_data=compressed_dict
            )

            logger.info("✅ 步骤2完成: Agent 已启动，等待用户交互")
            logger.info("=" * 80)

            return thread_id

        except Exception as e:
            logger.error(f"❌ 工作流处理失败: {e}", exc_info=True)
            workflow_processing_failed.send(self, session_id=session.recording_id, error=str(e))
            raise

    def process_recording(
        self, session: RecordingSession, options: Optional[Dict[str, Any]] = None
    ) -> Tool:
        """
        处理录制会话（兼容模式）

        注意：此方法使用已废弃的 SemanticAnalyzer，建议使用 process_recording_with_agent()

        Args:
            session: 录制会话数据
            options: 可选的处理选项

        Returns:
            Tool: 生成的工具定义
        """
        if self.use_agent:
            logger.warning("⚠️ Agent 模式下调用 process_recording() 将使用同步方式处理")
            # 在 Agent 模式下，提供一个简化的同步处理流程
            return self._process_with_agent_sync(session, options)

        # 兼容模式：使用 SemanticAnalyzer
        return self._process_with_legacy(session, options or {})

    def _process_with_agent_sync(
        self, session: RecordingSession, options: Optional[Dict[str, Any]] = None
    ) -> Tool:
        """
        使用 Agent 模式同步处理（简化版，不等待用户确认）

        用于兼容旧的同步调用方式。
        """
        options = options or {}
        progress = ProcessingProgress(total_steps=2)

        logger.info("=" * 80)
        logger.info(f"开始处理录制会话（Agent 同步模式）: {session.recording_id}")
        logger.info("=" * 80)

        workflow_processing_started.send(self, session_id=session.recording_id)

        try:
            # 步骤1: 数据压缩
            progress.update(1, "数据压缩", "正在压缩和优化录制数据...")
            self._notify_progress(progress)
            compressed_data = self.preprocessor.preprocess(
                actions=session.actions, compression_level=self.compression_level
            )
            logger.info("✅ 步骤1完成: 数据压缩")

            # 步骤2: 使用 Agent 直接生成（跳过用户确认）
            progress.update(2, "代码生成", "正在生成工具...")
            self._notify_progress(progress)

            # 直接调用 Agent 图（不通过 UI Bridge）
            from src.business.agent.graph import create_agent_graph
            from src.business.agent.checkpointer import get_memory_checkpointer

            checkpointer = get_memory_checkpointer()
            agent = create_agent_graph("tool_generation", checkpointer)

            compressed_dict = {
                "recording_id": session.recording_id,
                "actions": session.actions,
                "metadata": compressed_data.metadata,
                "screenshots": compressed_data.screenshots,
            }

            config = {"configurable": {"thread_id": f"sync-{session.recording_id}"}}
            result = agent.invoke({
                "recording_data": compressed_dict,
                "conversation_type": "tool_generation"
            }, config)

            # 从结果中提取工具
            tool_draft = result.get("tool_draft")
            if tool_draft:
                tool = Tool(
                    tool_name=tool_draft.tool_name,
                    description=tool_draft.description,
                    parameters=tool_draft.parameters if isinstance(tool_draft.parameters, list) else [],
                    steps=[],
                    execution_code=tool_draft.execution_code,
                    execution_strategy=tool_draft.execution_strategy,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )

                # 保存到数据库
                if options.get("save_to_db", True):
                    self._save_tool(tool)

                logger.info(f"✅ 工具生成完成: {tool.tool_name}")
                workflow_processing_completed.send(
                    self, session_id=session.recording_id, tool_id=tool.tool_name
                )
                return tool

            raise RuntimeError("Agent 未能生成工具")

        except Exception as e:
            logger.error(f"❌ 工作流处理失败: {e}", exc_info=True)
            workflow_processing_failed.send(self, session_id=session.recording_id, error=str(e))
            raise

    def _process_with_legacy(
        self, session: RecordingSession, options: Dict[str, Any]
    ) -> Tool:
        """
        使用旧流程处理（已废弃）
        """
        # 保留原有逻辑用于兼容
        # ...（省略详细实现，与原代码相同）
        raise NotImplementedError("兼容模式已废弃，请使用 Agent 模式")

    def _save_tool(self, tool: Tool) -> None:
        """保存工具到数据库"""
        try:
            tool_repo = ToolRepository()

            # 转换为持久层模型
            tool_model = tool.to_persistence_model()

            tool_repo.create(tool_model)
            logger.info(f"工具已保存到数据库，ID: {tool.tool_id}")
        except Exception as e:
            logger.error(f"保存工具到数据库失败: {e}")

    def _notify_progress(self, progress: ProcessingProgress) -> None:
        """通知进度更新"""
        if self.on_progress:
            try:
                self.on_progress(progress)
            except Exception as e:
                logger.warning(f"进度回调失败: {e}")

        workflow_processing_progress.send(
            self,
            current_step=progress.current_step,
            total_steps=progress.total_steps,
            step_name=progress.step_name,
            message=progress.message,
            percent=progress.percent,
        )

    def start_listening(self) -> None:
        """
        开始监听录制完成事件

        当有录制完成时，自动调用处理流程
        """
        if self._event_listener is not None:
            logger.warning("已经在监听录制完成事件")
            return

        def on_recording_completed(sender, **kwargs):
            event_data = kwargs.get("event_data")

            if not event_data:
                session = kwargs.get("session")
                if not session:
                    logger.warning("收到录制完成事件，但没有 event_data 或 session 数据")
                    return
                logger.info(f"🎯 自动触发工作流处理（旧版）: {session.recording_id}")
                try:
                    if self.use_agent:
                        self.process_recording_with_agent(session)
                    else:
                        self.process_recording(session)
                except Exception as e:
                    logger.error(f"自动处理录制失败: {e}", exc_info=True)
                    workflow_processing_failed.send(
                        self, session_id=session.recording_id, error=str(e)
                    )
                return

            recording_id = event_data.session_id
            recording_mode = event_data.recording_mode
            action_count = event_data.action_count

            if not recording_id:
                logger.warning("收到录制完成事件，但没有 recording_id")
                return

            logger.info(f"🎯 收到录制完成事件: {recording_id}")
            logger.info(f"   录制模式: {recording_mode}")
            logger.info(f"   操作数量: {action_count}")

            try:
                if recording_mode == "browser":
                    from src.recording.recorder import RecordingSession
                    actions = self._load_actions_from_duckdb(recording_id)

                    if actions:
                        logger.info(f"✓ 从 DuckDB 加载了 {len(actions)} 个事件")
                    else:
                        logger.error("无法从 DuckDB 加载事件")
                        return

                    session = RecordingSession(
                        recording_id=recording_id,
                        status="stopped",
                        recording_mode=recording_mode,
                        start_time=event_data.start_time,
                        end_time=event_data.end_time,
                        actions=actions,
                        metadata={},
                    )
                else:
                    session = kwargs.get("session")
                    if not session:
                        logger.warning("桌面模式但没有 session 数据")
                        return

                logger.info(f"开始自动处理工作流: {recording_id}")
                if self.use_agent:
                    self.process_recording_with_agent(session)
                else:
                    self.process_recording(session)

            except Exception as e:
                logger.error(f"自动处理录制失败: {e}", exc_info=True)
                workflow_processing_failed.send(self, session_id=recording_id, error=str(e))

        self._event_listener = recording_completed.connect(
            on_recording_completed,
            weak=False
        )
        logger.info("✅ 已开始监听录制完成事件")

    def stop_listening(self) -> None:
        """停止监听录制完成事件"""
        if self._event_listener is None:
            logger.warning("未在监听录制完成事件")
            return

        recording_completed.disconnect(self._event_listener)
        self._event_listener = None
        logger.info("⏸️  已停止监听录制完成事件")

    def is_listening(self) -> bool:
        """检查是否正在监听事件"""
        return self._event_listener is not None

    def _load_actions_from_duckdb(self, recording_id: str) -> List[Action]:
        """从 DuckDB 加载录制数据"""
        from src.data.recording_repository import RecordingRepository
        from src.recording.recorder import Action, NetworkRequest

        try:
            repo = RecordingRepository()
            session = repo.get_recording_session(recording_id)
            if not session:
                logger.warning(f"DuckDB 中未找到录制会话: {recording_id}")
                return []

            actions_dicts = repo.get_actions(recording_id)
            logger.info(f"读取到 {len(actions_dicts)} 个 actions")

            actions = []
            for action_dict in actions_dicts:
                try:
                    network_requests = None
                    if action_dict.get("action_id"):
                        network_requests_dicts = repo.get_network_requests(action_dict["action_id"])
                        if network_requests_dicts:
                            network_requests = [
                                NetworkRequest(
                                    url=req.get("url", ""),
                                    method=req.get("method", "GET"),
                                    request_headers=req.get("request_headers", {}),
                                    request_body=req.get("request_body"),
                                    response_status=req.get("response_status"),
                                    response_headers=req.get("response_headers", {}),
                                    response_body=req.get("response_body"),
                                    timestamp=req.get("timestamp", 0),
                                    duration=req.get("duration"),
                                    request_id=req.get("request_id"),
                                )
                                for req in network_requests_dicts
                            ]

                    action = Action(
                        action_type=action_dict.get("action_type", ""),
                        recording_mode=action_dict.get("recording_mode", "browser"),
                        timestamp=action_dict.get("timestamp", 0),
                        dom_element=action_dict.get("dom_element"),
                        network_requests=network_requests,
                        url=action_dict.get("url"),
                        parameters=action_dict.get("parameters", {}),
                        app_name=action_dict.get("app_name"),
                        process_name=action_dict.get("process_name"),
                        window_title=action_dict.get("window_title"),
                    )
                    actions.append(action)

                except Exception as e:
                    logger.warning(f"转换 action 失败: {e}")
                    continue

            logger.info(f"✓ 从 DuckDB 加载了 {len(actions)} 个 Action 对象")
            return actions

        except Exception as e:
            logger.error(f"从 DuckDB 加载录制数据失败: {e}", exc_info=True)
            return []

    def close(self) -> None:
        """关闭所有组件和事件监听"""
        if self.is_listening():
            self.stop_listening()

        if self._semantic_analyzer:
            self._semantic_analyzer.close()

        logger.info("工作流编排器已关闭")

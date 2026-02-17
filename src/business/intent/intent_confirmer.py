"""
意图确认模块

负责处理用户意图的交互式确认流程
"""

import logging
import time
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.business.ai.prompts.intent_analysis_models import (
    Intent as IntentAnalysisModel,
    IntentAnalysisResult,
    IntentConfirmationTurn,
)
from src.business.intent.intent_models import Intent as IntentDBModel, IntentStatus
from src.business.intent.intent_analyzer import IntentAnalyzer
from src.business.intent.intent_repository import IntentRepository
from src.communication.websocket_handler import WebSocketHandler
from src.communication.message_types import WebSocketMessage, MessageType

logger = logging.getLogger(__name__)


class ConfirmationState:
    """确认状态机"""

    def __init__(self, intent: IntentAnalysisModel):
        self.intent = intent
        self.current_turn = 0
        self.max_turns = 5
        self.state = "pending_confirmation"  # pending_confirmation, refining, confirmed, cancelled
        self.last_activity = time.time()

    def can_continue(self) -> bool:
        """判断是否可以继续对话"""
        return self.current_turn < self.max_turns and self.state in [
            "pending_confirmation",
            "refining",
        ]

    def advance_turn(self) -> bool:
        """推进到下一轮"""
        if self.can_continue():
            self.current_turn += 1
            self.last_activity = time.time()
            return True
        return False

    def confirm(self) -> None:
        """确认意图"""
        self.state = "confirmed"

    def cancel(self) -> None:
        """取消意图"""
        self.state = "cancelled"

    def start_refining(self) -> None:
        """开始优化流程"""
        self.state = "refining"


class IntentConfirmer:
    """
    意图确认器

    管理用户意图的交互式确认流程，支持多轮对话
    """

    def __init__(
        self,
        analyzer: IntentAnalyzer,
        repository: IntentRepository,
        ws_handler: WebSocketHandler,
    ):
        """
        初始化意图确认器

        Args:
            analyzer: 意图分析器
            repository: 意图仓库
            ws_handler: WebSocket 处理器
        """
        self.analyzer = analyzer
        self.repository = repository
        self.ws_handler = ws_handler

        # 活跃的确认会话（intent_id -> ConfirmationState）
        self.active_sessions: Dict[str, ConfirmationState] = {}

        # 注册 WebSocket 消息处理器
        self._register_handlers()

    def _register_handlers(self):
        """注册 WebSocket 消息处理器"""
        self.ws_handler.register_handler(MessageType.CONFIRM_INTENT, self._handle_confirm_intent)

    async def start_confirmation(self, recording_id: str) -> IntentAnalysisModel:
        """
        启动意图确认流程

        Args:
            recording_id: 录制 ID

        Returns:
            意图对象
        """
        try:
            logger.info(f"启动意图确认流程，录制ID: {recording_id}")

            # 1. 检查是否已存在意图
            existing_intent = self.repository.get_by_recording_id(recording_id)
            if existing_intent and existing_intent.status == IntentStatus.CONFIRMED:
                logger.info(f"录制 {recording_id} 的意图已确认")
                return self._db_to_business_model(existing_intent)

            # 2. 从录制数据获取会话信息（这里需要从数据加载器获取）
            # TODO: 需要从 DuckDB 加载录制数据
            recording_session = await self._load_recording_session(recording_id)

            # 3. 分析意图
            intent = await self.analyzer.create_intent_from_recording(recording_session)

            # 4. 创建数据库记录
            db_intent = self._business_to_db_model(intent)
            self.repository.create(db_intent)

            # 5. 创建确认会话
            self.active_sessions[intent.intent_id] = ConfirmationState(intent)

            # 6. 通过 WebSocket 发送确认请求
            await self._send_confirmation_request(intent)

            logger.info(f"意图确认流程已启动，" f"置信度: {intent.analysis_result.confidence:.2f}")

            return intent

        except Exception as e:
            logger.error(f"启动意图确认失败: {e}", exc_info=True)
            raise

    async def process_user_feedback(self, intent_id: str, feedback: str) -> IntentAnalysisModel:
        """
        处理用户反馈

        Args:
            intent_id: 意图 ID
            feedback: 用户反馈

        Returns:
            更新后的意图对象
        """
        try:
            logger.info(f"处理用户反馈，意图ID: {intent_id}, 反馈: {feedback[:50]}...")

            # 1. 获取会话状态
            session = self.active_sessions.get(intent_id)
            if not session:
                raise ValueError(f"未找到活跃的确认会话: {intent_id}")

            # 2. 检查是否可以继续对话
            if not session.can_continue():
                raise ValueError(f"已达到最大对话轮数 ({session.max_turns}) 或会话已结束")

            # 3. 开始优化流程
            session.start_refining()

            # 4. 构建对话历史
            conversation_history = self._build_conversation_history(session.intent)

            # 5. 调用分析器优化意图
            updated_result = await self.analyzer.refine_intent(
                original_intent=session.intent.analysis_result,
                user_feedback=feedback,
                conversation_history=conversation_history,
            )

            # 6. 创建确认轮次记录
            turn = await self.analyzer.add_confirmation_turn(
                intent=session.intent,
                user_feedback=feedback,
                assistant_response=updated_result.reasoning,
                updated_intent=updated_result,
            )

            # 7. 推进对话轮次
            session.advance_turn()
            session.intent.analysis_result = updated_result

            # 8. 更新数据库
            db_intent = self._business_to_db_model(session.intent)
            self.repository.update(db_intent)

            # 9. 通过 WebSocket 发送更新
            await self._send_intent_update(session.intent, turn)

            logger.info(
                f"用户反馈已处理，"
                f"新置信度: {updated_result.confidence:.2f}, "
                f"当前轮次: {session.current_turn}/{session.max_turns}"
            )

            return session.intent

        except Exception as e:
            logger.error(f"处理用户反馈失败: {e}", exc_info=True)
            raise

    async def confirm_intent(
        self, intent_id: str, confirmed_operations: Optional[List[str]] = None
    ) -> IntentAnalysisModel:
        """
        确认意图

        Args:
            intent_id: 意图 ID
            confirmed_operations: 用户确认的操作列表（可选）

        Returns:
            确认后的意图对象
        """
        try:
            logger.info(f"确认意图，意图ID: {intent_id}")

            # 1. 获取会话状态
            session = self.active_sessions.get(intent_id)
            if not session:
                # 可能是重新确认已存在的意图
                db_intent = self.repository.get_by_id(intent_id)
                if not db_intent:
                    raise ValueError(f"未找到意图: {intent_id}")
                session = ConfirmationState(self._db_to_business_model(db_intent))
                self.active_sessions[intent_id] = session

            # 2. 设置确认的操作
            if confirmed_operations:
                # 如果用户明确指定了操作，将字符串列表转换为 CoreOperation 对象
                from src.business.ai.prompts.intent_analysis_models import CoreOperation

                session.intent.analysis_result.core_operations = [
                    CoreOperation(
                        operation=op_str,
                        action_index=i,
                        importance=1.0,
                        parameters={},
                    )
                    for i, op_str in enumerate(confirmed_operations)
                ]

            # 3. 确认会话
            session.confirm()
            session.intent.status = "confirmed"
            session.intent.confirmed_at = time.time()

            # 4. 更新数据库
            db_intent = self._business_to_db_model(session.intent)
            db_intent.status = IntentStatus.CONFIRMED
            db_intent.confirmed_at = datetime.now()
            db_intent.confirmed_operations = confirmed_operations or [
                op.operation for op in session.intent.analysis_result.core_operations
            ]
            self.repository.update(db_intent)

            # 5. 发送确认成功消息
            await self._send_confirmation_success(session.intent)

            # 6. 清理会话
            del self.active_sessions[intent_id]

            logger.info(f"意图已确认: {intent_id}")

            return session.intent

        except Exception as e:
            logger.error(f"确认意图失败: {e}", exc_info=True)
            raise

    async def cancel_confirmation(self, intent_id: str) -> IntentAnalysisModel:
        """
        取消意图确认

        Args:
            intent_id: 意图 ID

        Returns:
            取消后的意图对象
        """
        try:
            logger.info(f"取消意图确认，意图ID: {intent_id}")

            # 1. 获取会话状态
            session = self.active_sessions.get(intent_id)
            if not session:
                raise ValueError(f"未找到活跃的确认会话: {intent_id}")

            # 2. 取消会话
            session.cancel()
            session.intent.status = "cancelled"

            # 3. 更新数据库
            db_intent = self._business_to_db_model(session.intent)
            db_intent.status = IntentStatus.CANCELLED
            self.repository.update(db_intent)

            # 4. 发送取消通知
            await self._send_cancellation_notification(session.intent)

            # 5. 清理会话
            del self.active_sessions[intent_id]

            logger.info(f"意图确认已取消: {intent_id}")

            return session.intent

        except Exception as e:
            logger.error(f"取消意图确认失败: {e}", exc_info=True)
            raise

    async def _handle_confirm_intent(self, msg: WebSocketMessage) -> Dict[str, Any]:
        """
        处理确认意图的 WebSocket 消息

        Args:
            msg: WebSocket 消息

        Returns:
            响应数据
        """
        try:
            data = msg.data
            intent_id = data.get("intent_id")
            action = data.get("action")  # confirm, cancel, refine

            if not intent_id:
                raise ValueError("缺少 intent_id")

            if action == "confirm":
                confirmed_operations = data.get("confirmed_operations")
                intent = await self.confirm_intent(intent_id, confirmed_operations)
                return {"status": "confirmed", "intent_id": intent_id}

            elif action == "cancel":
                intent = await self.cancel_confirmation(intent_id)
                return {"status": "cancelled", "intent_id": intent_id}

            elif action == "refine":
                feedback = data.get("feedback")
                if not feedback:
                    raise ValueError("缺少 feedback")
                intent = await self.process_user_feedback(intent_id, feedback)
                return {
                    "status": "refined",
                    "intent_id": intent_id,
                    "updated_intent": intent.analysis_result.to_dict(),
                }

            else:
                raise ValueError(f"未知的 action: {action}")

        except Exception as e:
            logger.error(f"处理确认意图消息失败: {e}", exc_info=True)
            raise

    async def _send_confirmation_request(self, intent: IntentAnalysisModel):
        """
        发送确认请求到客户端

        Args:
            intent: 意图对象
        """
        try:
            msg = WebSocketMessage(
                type=MessageType.CONFIRM_INTENT,
                data={
                    "intent_id": intent.intent_id,
                    "recording_id": intent.recording_id,
                    "core_operations": [
                        op.operation for op in intent.analysis_result.core_operations
                    ],
                    "target": intent.analysis_result.target,
                    "business_scenario": intent.analysis_result.business_scenario,
                    "expected_results": intent.analysis_result.expected_results,
                    "suggested_parameters": [
                        param.to_dict() for param in intent.analysis_result.suggested_parameters
                    ],
                    "confidence": intent.analysis_result.confidence,
                    "reasoning": intent.analysis_result.reasoning,
                    "max_turns": intent.max_turns,
                },
                status="pending",
            )

            await self.ws_handler.broadcast(msg)
            logger.info(f"已发送确认请求: {intent.intent_id}")

        except Exception as e:
            logger.error(f"发送确认请求失败: {e}", exc_info=True)
            raise

    async def _send_intent_update(self, intent: IntentAnalysisModel, turn: IntentConfirmationTurn):
        """
        发送意图更新到客户端

        Args:
            intent: 意图对象
            turn: 确认轮次
        """
        try:
            msg = WebSocketMessage(
                type=MessageType.INTENT_UPDATED,
                data={
                    "intent_id": intent.intent_id,
                    "core_operations": [
                        op.operation for op in intent.analysis_result.core_operations
                    ],
                    "target": intent.analysis_result.target,
                    "business_scenario": intent.analysis_result.business_scenario,
                    "expected_results": intent.analysis_result.expected_results,
                    "confidence": intent.analysis_result.confidence,
                    "reasoning": intent.analysis_result.reasoning,
                    "turn_number": len(intent.confirmation_turns),
                    "max_turns": intent.max_turns,
                    "last_turn": {
                        "user_feedback": turn.user_feedback,
                        "assistant_response": turn.assistant_response,
                    },
                },
            )

            await self.ws_handler.broadcast(msg)
            logger.info(f"已发送意图更新: {intent.intent_id}")

        except Exception as e:
            logger.error(f"发送意图更新失败: {e}", exc_info=True)
            raise

    async def _send_confirmation_success(self, intent: IntentAnalysisModel):
        """
        发送确认成功消息

        Args:
            intent: 意图对象
        """
        try:
            msg = WebSocketMessage(
                type=MessageType.INTENT_CONFIRMED,
                data={
                    "intent_id": intent.intent_id,
                    "confirmed_operations": [
                        op.operation for op in intent.analysis_result.core_operations
                    ],
                    "status": "confirmed",
                },
            )

            await self.ws_handler.broadcast(msg)
            logger.info(f"已发送确认成功消息: {intent.intent_id}")

        except Exception as e:
            logger.error(f"发送确认成功消息失败: {e}", exc_info=True)
            raise

    async def _send_cancellation_notification(self, intent: IntentAnalysisModel):
        """
        发送取消通知

        Args:
            intent: 意图对象
        """
        try:
            msg = WebSocketMessage(
                type=MessageType.INTENT_UPDATED,
                data={
                    "intent_id": intent.intent_id,
                    "status": "cancelled",
                },
            )

            await self.ws_handler.broadcast(msg)
            logger.info(f"已发送取消通知: {intent.intent_id}")

        except Exception as e:
            logger.error(f"发送取消通知失败: {e}", exc_info=True)
            raise

    def _build_conversation_history(self, intent: IntentAnalysisModel) -> List[Dict[str, str]]:
        """
        构建对话历史

        Args:
            intent: 意图对象

        Returns:
            对话历史列表
        """
        history = []
        for turn in intent.confirmation_turns:
            history.append(
                {
                    "role": "user",
                    "content": turn.user_feedback,
                }
            )
            history.append(
                {
                    "role": "assistant",
                    "content": turn.assistant_response,
                }
            )
        return history

    def _business_to_db_model(self, intent: IntentAnalysisModel) -> IntentDBModel:
        """
        将业务模型转换为数据库模型

        Args:
            intent: 业务模型

        Returns:
            数据库模型
        """
        return IntentDBModel(
            intent_id=intent.intent_id,
            recording_id=intent.recording_id,
            core_operations=[op.operation for op in intent.analysis_result.core_operations],
            target=intent.analysis_result.target,
            business_scenario=intent.analysis_result.business_scenario,
            expected_results=intent.analysis_result.expected_results,
            status=(
                IntentStatus(intent.status)
                if intent.status in [s.value for s in IntentStatus]
                else IntentStatus.PENDING_CONFIRMATION
            ),
            confirmed_operations=[],
            user_message=None,
            analysis_confidence=intent.analysis_result.confidence,
            llm_model_used=intent.analysis_result.recording_id,
            created_at=(
                datetime.fromtimestamp(intent.created_at) if intent.created_at else datetime.now()
            ),
            updated_at=(
                datetime.fromtimestamp(intent.updated_at) if intent.updated_at else datetime.now()
            ),
            confirmed_at=(
                datetime.fromtimestamp(intent.confirmed_at) if intent.confirmed_at else None
            ),
        )

    def _db_to_business_model(self, db_intent: IntentDBModel) -> IntentAnalysisModel:
        """
        将数据库模型转换为业务模型

        Args:
            db_intent: 数据库模型

        Returns:
            业务模型
        """
        from src.business.ai.prompts.intent_analysis_models import CoreOperation

        # 从数据库的 core_operations (List[str]) 重建 CoreOperation 对象
        core_operations = []
        for i, op_str in enumerate(db_intent.core_operations):
            core_operations.append(
                CoreOperation(
                    operation=op_str,
                    action_index=i,
                    importance=1.0,
                    parameters={},
                )
            )

        # 创建分析结果
        analysis_result = IntentAnalysisResult(
            core_operations=core_operations,
            target=db_intent.target or "",
            business_scenario=db_intent.business_scenario or "",
            expected_results=db_intent.expected_results,
            suggested_parameters=[],  # 数据库中没有存储这个字段
            confidence=db_intent.analysis_confidence,
            reasoning="",
            recording_id=db_intent.recording_id,
            status=db_intent.status.value,
        )

        # 创建意图对象
        intent = IntentAnalysisModel(
            intent_id=db_intent.intent_id,
            recording_id=db_intent.recording_id,
            analysis_result=analysis_result,
            status=db_intent.status.value,
            max_turns=5,
            created_at=db_intent.created_at.timestamp() if db_intent.created_at else 0.0,
            updated_at=db_intent.updated_at.timestamp() if db_intent.updated_at else 0.0,
            confirmed_at=db_intent.confirmed_at.timestamp() if db_intent.confirmed_at else None,
        )

        return intent

    async def _load_recording_session(self, recording_id: str) -> Dict[str, Any]:
        """
        从数据库加载录制会话

        Args:
            recording_id: 录制 ID

        Returns:
            录制会话数据
        """
        from src.data.duckdb_manager import DuckDBManager

        try:
            # 获取 DuckDBManager 实例
            duckdb_manager = DuckDBManager()

            # 1. 查询录制会话基本信息
            session_sql = """
                SELECT recording_id, status, recording_mode, browser_type,
                       start_time, end_time, metadata
                FROM recording_sessions
                WHERE recording_id = ?
            """
            session_result = duckdb_manager.fetchone(session_sql, (recording_id,))

            if not session_result:
                raise ValueError(f"未找到录制会话: {recording_id}")

            # 解析会话信息
            from datetime import datetime
            import json

            recording_session = {
                "recording_id": session_result[0],
                "status": session_result[1],
                "recording_mode": session_result[2],
                "browser_type": session_result[3],
                "start_time": session_result[4],
                "end_time": session_result[5],
                "metadata": json.loads(session_result[6]) if session_result[6] else {},
            }

            # 2. 查询操作列表
            actions_sql = """
                SELECT action_id, recording_id, sequence_number, action_type,
                       recording_mode, app_name, process_name, window_title,
                       parameters, url, dom_element, dom_tree_snapshot,
                       visual_features, screenshot_before, screenshot_after, timestamp
                FROM actions
                WHERE recording_id = ?
                ORDER BY sequence_number ASC
            """
            action_results = duckdb_manager.fetchall(actions_sql, (recording_id,))

            # 解析操作数据
            actions = []
            for row in action_results:
                action = {
                    "action_id": row[0],
                    "recording_id": row[1],
                    "sequence_number": row[2],
                    "action_type": row[3],
                    "recording_mode": row[4],
                    "app_name": row[5],
                    "process_name": row[6],
                    "window_title": row[7],
                    "parameters": json.loads(row[8]) if row[8] else {},
                    "url": row[9],
                    "dom_element": json.loads(row[10]) if row[10] else None,
                    "dom_tree_snapshot": json.loads(row[11]) if row[11] else None,
                    "visual_features": json.loads(row[12]) if row[12] else None,
                    "screenshot_before": row[13],
                    "screenshot_after": row[14],
                    "timestamp": row[15],
                }
                actions.append(action)

            recording_session["actions"] = actions

            logger.info(f"成功从 DuckDB 加载录制会话: {recording_id}, 操作数量: {len(actions)}")

            return recording_session

        except Exception as e:
            logger.error(f"从 DuckDB 加载录制会话失败: {recording_id}, 错误: {e}", exc_info=True)
            # 如果加载失败，返回最小化结构（保持向后兼容）
            logger.warning(f"返回模拟数据，录制ID: {recording_id}")
            return {
                "recording_id": recording_id,
                "actions": [],
                "metadata": {},
                "status": "error",
                "error": str(e),
            }

    def get_active_session_count(self) -> int:
        """获取当前活跃的确认会话数量"""
        return len(self.active_sessions)

    def cleanup_stale_sessions(self, timeout: float = 3600):
        """
        清理超时的会话

        Args:
            timeout: 超时时间（秒）
        """
        current_time = time.time()
        stale_ids = []

        for intent_id, session in self.active_sessions.items():
            if current_time - session.last_activity > timeout:
                stale_ids.append(intent_id)

        for intent_id in stale_ids:
            logger.info(f"清理超时会话: {intent_id}")
            del self.active_sessions[intent_id]

        if stale_ids:
            logger.info(f"已清理 {len(stale_ids)} 个超时会话")

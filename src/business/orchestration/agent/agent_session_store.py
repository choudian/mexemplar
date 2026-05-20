import json
import logging
import uuid
from typing import List, Optional, Sequence

from src.data.models_sqlite import Session, WorkflowTransition
from src.business.agents.config import AgentType


class AgentSessionStore:
    def __init__(
        self,
        session_repo,
        message_repo,
        transition_repo,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._session_repo = session_repo
        self._message_repo = message_repo
        self._transition_repo = transition_repo
        self._logger = logger or logging.getLogger(__name__)

    def get_session(self, session_id: str):
        return self._session_repo.get_by_id(session_id)

    def get_sessions_by_workflow(
        self,
        workflow_id: str,
        agent_type: Optional[str] = None,
        order_by: Optional[str] = None,
    ):
        return self._session_repo.get_by_workflow(
            workflow_id,
            agent_type=agent_type,
            order_by=order_by,
        )

    def get_or_create_session(self, workflow_id: str, agent_type: str) -> str:
        """获取或创建 session：同一 (workflow_id, agent_type) 永远复用同一条 session。

        - 不存在时创建新 session（status=active）
        - 存在时直接返回 latest，由 AgentLoop entry 把 failed/completed 复活为 active
        - latest=active 时记 warning，提示可能的并发调用，但仍复用
        """
        sessions = self._session_repo.get_by_workflow(
            workflow_id,
            agent_type=agent_type,
            order_by="created_at_desc",
        )

        if sessions:
            latest = sessions[0]
            if latest.status == "active":
                self._logger.warning(
                    f"[Orchestrator] 会话 {latest.session_id} 仍在 active 状态，可能存在并发调用"
                )
            return latest.session_id

        return self.create_session(workflow_id, agent_type)

    def create_session(self, workflow_id: str, agent_type: str) -> str:
        model = Session(
            session_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            agent_type=agent_type,
            status="active",
        )
        session = self._session_repo.create(model)
        return session.session_id

    def record_transition(
        self,
        workflow_id: str,
        *,
        event_type: str,
        from_session_id: str,
        to_session_id: Optional[str],
        payload: Optional[str],
    ) -> None:
        self._transition_repo.create(
            WorkflowTransition(
                transition_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                event_type=event_type,
                from_session_id=from_session_id,
                to_session_id=to_session_id,
                payload=payload,
            )
        )

    def get_transition_payload(self, workflow_id: str, event_type: str, key: str):
        transition = self._transition_repo.get_latest_by_workflow_and_event(workflow_id, event_type)
        if transition and transition.payload:
            try:
                return json.loads(transition.payload).get(key)
            except (json.JSONDecodeError, TypeError):
                pass
        return None

    def find_old_session(self, workflow_id: str, agent_type: str) -> str | None:
        sessions = self._session_repo.get_by_workflow(
            workflow_id,
            agent_type=agent_type,
            order_by="created_at_desc",
        )
        if sessions:
            session_id = sessions[0].session_id
            self._logger.info(
                f"[Orchestrator] {agent_type} 重试复用旧 session: {session_id}, workflow={workflow_id}"
            )
            return session_id
        return None

    def format_messages_for_display(
        self,
        messages: Sequence,
        session_id: str,
        *,
        skip_first_user: bool = False,
    ) -> List[dict]:
        result = []
        first_user_skipped = False

        for msg in messages:
            if msg.role in ("program", "agent"):
                continue
            if msg.role == "user" and msg.content:
                if skip_first_user and not first_user_skipped:
                    first_user_skipped = True
                    continue
                result.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                if msg.content:
                    result.append({"role": "assistant", "content": msg.content})
                elif msg.tool_calls:
                    try:
                        tool_calls = json.loads(msg.tool_calls)
                    except (json.JSONDecodeError, TypeError):
                        self._logger.warning(f"跳过损坏的 tool_calls: session={session_id}")
                        continue
                    for tool_call in tool_calls:
                        if tool_call.get("name") == "talk_to_user":
                            question = tool_call.get("args", {}).get("message", "")
                            if question:
                                result.append({"role": "assistant", "content": question})
        return result

    def get_agent_messages(
        self,
        workflow_id: str,
        *,
        agent_type: str,
        skip_first_user: bool = False,
        exclude_statuses: tuple = (),
    ) -> List[dict]:
        sessions = self._session_repo.get_by_workflow(
            workflow_id,
            agent_type=agent_type,
            order_by="created_at_desc",
        )
        if not sessions:
            return []
        if exclude_statuses and sessions[0].status in exclude_statuses:
            return []
        session_id = sessions[0].session_id
        messages = self._message_repo.get_context(session_id)
        return self.format_messages_for_display(
            messages,
            session_id,
            skip_first_user=skip_first_user,
        )

    def get_trial_messages(self, workflow_id: str) -> List[dict]:
        return self.get_agent_messages(
            workflow_id,
            agent_type=AgentType.TRIAL,
            skip_first_user=False,
            exclude_statuses=("failed", "active"),
        )


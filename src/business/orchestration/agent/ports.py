from typing import Any, Optional, Protocol, Union


class EventBusPort(Protocol):
    def connect(self, event_name: str, handler) -> Any: ...

    def emit(self, event_name: str, sender: Any = None, **payload) -> None: ...


class AgentExecutionPort(Protocol):
    def run_agent(
        self,
        agent_type: str,
        user_input: Optional[Union[str, dict]],
        workflow_id: str = None,
        session_id: str = None,
    ) -> None: ...

    def start_analysis(self, recording_id: str, workflow_id: str) -> None: ...


class AssistantTaskPort(Protocol):
    def run_agent(
        self,
        agent_type: str,
        user_input: Optional[Union[str, dict]],
        workflow_id: str = None,
        session_id: str = None,
    ) -> None: ...

    def start_triage(self, tool_id: str, user_feedback: str, workflow_id: str) -> None: ...


class ReviewStatePort(Protocol):
    def get_retry_count(self, workflow_id: str) -> int: ...

    def increment_retry_count(self, workflow_id: str) -> int: ...

    def clear_retry_count(self, workflow_id: str) -> None: ...

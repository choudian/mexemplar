"""Assistant session lifecycle side effects."""

import time

from src.business.agents.tools.builtin_general_tools import (
    CONFIRM_SOURCE_NEW_CHAT_RESET,
    reset_auto_approve,
    settle_pending_confirmations,
)


class AssistantSessionLifecycle:
    """Process-scoped lifecycle hooks for assistant chat sessions."""

    def reset_confirmation_state_for_new_chat(self) -> None:
        """Fail-close pending confirmations and clear session-scoped auto-approve.

        The underlying confirmation state is process memory.  The cutoff preserves
        first-decision-wins for confirmations created after this reset starts.
        """
        reset_cutoff = time.monotonic()
        reset_auto_approve(CONFIRM_SOURCE_NEW_CHAT_RESET)
        settle_pending_confirmations(
            False,
            CONFIRM_SOURCE_NEW_CHAT_RESET,
            created_before=reset_cutoff,
        )

from typing import Protocol


class SessionEvents(Protocol):
    """Transport hook for session.force_logout, addressed to the old session only."""

    async def force_logout(self, user_id: int, session_id: str, reason: str) -> None: ...


class NoopSessionEvents:
    """Prompt 3 placeholder. A later WebSocket manager will implement this hook."""

    async def force_logout(self, user_id: int, session_id: str, reason: str) -> None:
        return None

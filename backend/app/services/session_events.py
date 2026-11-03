from typing import Protocol


class SessionEvents(Protocol):
    """Transport hook for session.force_logout, addressed to the old session only."""

    async def force_logout(self, user_id: int, session_id: str, reason: str) -> None: ...


class CombinedSessionEvents:
    """Run the real transport before an optional observer/test integration."""

    def __init__(self, transport: SessionEvents, observer: SessionEvents):
        self.transport, self.observer = transport, observer

    async def force_logout(self, user_id: int, session_id: str, reason: str) -> None:
        await self.transport.force_logout(user_id, session_id, reason)
        await self.observer.force_logout(user_id, session_id, reason)

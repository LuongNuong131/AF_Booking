"""Post-commit integration point. Transport and recipients are implemented later."""

from pydantic import JsonValue


class WebSocketManager:
    async def broadcast(self, event: str, payload: dict[str, JsonValue]) -> None:
        pass

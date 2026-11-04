import asyncio
import logging
from collections import deque

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect, WebSocketState

from app.core.errors import ApiException
from app.core.security import decode_access_token
from app.models import User
from app.schemas.contracts import ErrorCode
from app.schemas.realtime import HeartbeatFrame, client_frame_adapter
from app.services.session_cache import CurrentUser
from app.utils.booking_key import ParsedKey, parse

router = APIRouter()
logger = logging.getLogger(__name__)


async def receive_commands(socket, connection, manager, settings) -> None:
    timestamps = deque()
    while manager.current(connection):
        message = await socket.receive()
        if message["type"] == "websocket.disconnect":
            return
        now = manager.clock()
        while timestamps and timestamps[0] <= now - 1:
            timestamps.popleft()
        if len(timestamps) >= settings.ws_max_messages_per_second:
            manager.retire(connection, 1008)
            return
        timestamps.append(now)
        raw = message.get("text")
        if raw is None:
            manager.retire(connection, 1003)
            return
        if len(raw.encode("utf-8")) > settings.ws_max_message_bytes:
            manager.retire(connection, 1009)
            return
        try:
            frame = client_frame_adapter.validate_json(raw)
        except ValidationError:
            manager.retire(connection, 4400)
            return
        if not await manager.verify(connection):
            return
        if isinstance(frame, HeartbeatFrame):
            connection.last_pong = manager.clock()
            if frame.event == "ping":
                manager.emit("pong", {}, connection.user.id)
            continue
        key = frame.data.booking_key
        parsed = parse(key, settings.station_code_pattern)
        if not isinstance(parsed, ParsedKey) or parsed.key != key:
            manager.retire(connection, 4400)
            return
        if not manager.current(connection):
            return
        match frame.event:
            case "lock.acquire":
                manager.locks.acquire(connection, key)
            case "lock.heartbeat":
                manager.locks.heartbeat(connection, key)
            case "lock.release":
                manager.locks.release(connection.user.id, key, connection_id=connection.id)


async def reject(socket: WebSocket, code: int) -> None:
    # A close sent before accept becomes an HTTP 403 on real ASGI transports.
    # Upgrade only to deliver the documented close code, without registering a user.
    async with asyncio.timeout(socket.app.state.settings.ws_send_timeout_seconds):
        if socket.application_state == WebSocketState.CONNECTING:
            await socket.accept()
        await socket.close(code=code)


@router.websocket("/ws")
async def websocket(socket: WebSocket) -> None:
    settings = socket.app.state.settings
    manager = socket.app.state.ws_manager
    auth = socket.app.state.auth
    connection = None
    if socket.headers.get("origin") not in settings.cors_origins:
        await reject(socket, 4403)
        return
    try:
        token = socket.query_params.get("token", "")
        claims = decode_access_token(token, settings)
        # Serialize registration with login/revocation, then reread the live DB row.
        # Authenticating from the TTL cache alone leaves a login-vs-handshake race.
        async with auth.user_lock(int(claims.sub)):
            async with auth.transaction() as session:
                row = await session.get(User, int(claims.sub))
                if (
                    row is None
                    or not row.is_active
                    or row.must_change_password
                    or row.current_session_id != claims.sid
                ):
                    raise ApiException(ErrorCode.UNAUTHORIZED)
                user = CurrentUser.from_model(row)
            connection = await manager.connect(socket, user, claims)
    except ApiException as exc:
        code = 1013 if exc.code in {ErrorCode.SERVICE_BUSY, ErrorCode.REQUEST_TIMEOUT} else 4401
        await reject(socket, code)
        return
    except TimeoutError:
        await reject(socket, 1013)
        return
    reader = asyncio.create_task(receive_commands(socket, connection, manager, settings))
    closed = asyncio.create_task(connection.finished.wait())
    try:
        done, _ = await asyncio.wait({reader, closed}, return_when=asyncio.FIRST_COMPLETED)
        if reader in done:
            await reader
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("WebSocket receive failed user_id=%s (%s)", user.id, type(exc).__name__)
        manager.retire(connection, 1011)
    finally:
        for task in (reader, closed):
            task.cancel()
        await asyncio.gather(reader, closed, return_exceptions=True)
        await manager.disconnect(connection)

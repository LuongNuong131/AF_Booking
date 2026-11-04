"""Session-owned Web Push; bounded workers, verified HTTPS and no note bodies."""

import asyncio
import base64
import json
import logging
import time
from collections import OrderedDict
from datetime import UTC, datetime
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from sqlalchemy import and_, delete, func, select, update

from app.core.errors import ApiException
from app.core.unit_of_work import transaction
from app.models import PushSubscription, User
from app.schemas.contracts import ErrorCode
from app.services.auth import AuthService
from app.services.search_limiter import SearchLimiter

logger = logging.getLogger(__name__)
PUSH_TYPES = {"task_due", "assigned", "watch_update"}


def decode_key(value):
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def validate_endpoint(endpoint):
    try:
        endpoint.encode("ascii")
        url = urlsplit(endpoint)
        host = (url.hostname or "").lower()
        provider = (
            host
            in {"fcm.googleapis.com", "web.push.apple.com", "updates.push.services.mozilla.com"}
            or host.endswith(".push.services.mozilla.com")
            or host.endswith(".notify.windows.com")
        )
        valid = (
            url.scheme == "https"
            and provider
            and url.port in (None, 443)
            and not url.username
            and not url.password
            and not url.fragment
            and url.path
            and not any(ord(c) < 33 for c in endpoint)
        )
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        raise ApiException(
            ErrorCode.VALIDATION_ERROR, message="Use a browser-generated HTTPS push subscription."
        )


class NoRedirectSession(requests.Session):
    def request(self, method, url, **kwargs):
        kwargs["allow_redirects"] = False
        return super().request(method, url, **kwargs)


class PushService:
    def __init__(self, engine, settings, auth, ws):
        self.engine, self.settings, self.auth, self.ws = engine, settings, auth, ws
        self.queue = asyncio.Queue(maxsize=256)
        self.workers = []
        self.seen = OrderedDict()
        self.limiter = SearchLimiter(limit=60)
        self.key = None
        self.sender = self.deliver
        self.dropped = 0
        self.clock = time.monotonic
        self.active = 0
        self.job_state = dict(
            name="push.delivery",
            running=False,
            last_started_at=None,
            last_finished_at=None,
            duration_ms=None,
            last_error=None,
        )
        if settings.vapid_private_key and settings.vapid_public_key and settings.vapid_subject:
            try:
                key = Vapid.from_string(settings.vapid_private_key.get_secret_value())
                public = key.public_key.public_bytes(
                    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
                )
                if public != decode_key(settings.vapid_public_key):
                    raise ValueError("mismatched keys")
                subject = urlsplit(settings.vapid_subject)
                if not (
                    (subject.scheme == "mailto" and "@" in subject.path)
                    or (subject.scheme == "https" and subject.netloc)
                ):
                    raise ValueError("invalid subject")
                self.key = key
            except Exception:
                logger.warning("Web Push configuration is invalid; push is disabled")

    @property
    def configured(self):
        return self.key is not None

    def online(self, user_id):
        connection = self.ws.connections.get(user_id)
        return connection is not None and self.ws.current(connection)

    async def subscribe(self, body, actor, user_agent):
        if not self.configured:
            raise ApiException(
                ErrorCode.SERVICE_BUSY, message="Web Push is not configured on this server."
            )
        validate_endpoint(body.endpoint)
        try:
            public, auth = decode_key(body.keys.p256dh), decode_key(body.keys.auth)
            if len(public) != 65 or len(auth) != 16:
                raise ValueError
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
        except Exception:
            raise ApiException(
                ErrorCode.VALIDATION_ERROR, message="Invalid push subscription keys."
            ) from None
        async with self.auth.mutation(actor.id) as session:
            user = AuthService.require_live_row(
                await session.scalar(select(User).where(User.id == actor.id).with_for_update()),
                actor,
            )
            existing = await session.scalar(
                select(PushSubscription)
                .where(PushSubscription.endpoint == body.endpoint)
                .with_for_update()
            )
            if existing and existing.user_id != actor.id:
                raise ApiException(ErrorCode.NOT_FOUND)
            await session.execute(
                delete(PushSubscription).where(
                    PushSubscription.user_id == actor.id,
                    PushSubscription.session_id != actor.session_id,
                    PushSubscription.endpoint != body.endpoint,
                )
            )
            if not existing:
                count = await session.scalar(
                    select(func.count())
                    .select_from(PushSubscription)
                    .where(PushSubscription.user_id == actor.id)
                )
                if count >= 10:
                    raise ApiException(
                        ErrorCode.VALIDATION_ERROR,
                        message="Remove an older push subscription first.",
                    )
                existing = PushSubscription(user_id=actor.id, endpoint=body.endpoint)
                session.add(existing)
            existing.session_id, existing.p256dh, existing.auth = (
                actor.session_id,
                body.keys.p256dh,
                body.keys.auth,
            )
            existing.user_agent = " ".join((user_agent or "").split())[:255] or None
            user.settings = {**(user.settings or {}), "web_push_enabled": True}

    async def unsubscribe(self, endpoint, actor):
        async with self.auth.mutation(actor.id) as session:
            user = AuthService.require_live_row(
                await session.scalar(select(User).where(User.id == actor.id).with_for_update()),
                actor,
            )
            row = await session.scalar(
                select(PushSubscription)
                .where(PushSubscription.endpoint == endpoint)
                .with_for_update()
            )
            if row and row.user_id != actor.id:
                raise ApiException(ErrorCode.NOT_FOUND)
            if row:
                await session.delete(row)
                await session.flush()
            count = await session.scalar(
                select(func.count())
                .select_from(PushSubscription)
                .where(PushSubscription.user_id == actor.id)
            )
            if not count:
                user.settings = {**(user.settings or {}), "web_push_enabled": False}

    def enqueue(self, user_id, payload):
        if (
            not self.configured
            or self.engine is None
            or payload.get("type") not in PUSH_TYPES
            or self.online(user_id)
        ):
            return
        identity = (user_id, payload["id"], payload.get("merged_count", 1))
        moment = self.clock()
        seen_at = self.seen.get(identity)
        if seen_at is not None and seen_at > moment - 300:
            return
        minimal = {name: payload[name] for name in ("id", "type", "booking_key", "display_key")}
        try:
            self.queue.put_nowait((user_id, minimal))
        except asyncio.QueueFull:
            self.dropped += 1
            self.job_state["last_error"] = "QUEUE_FULL"
            return
        self.seen[identity] = moment
        while len(self.seen) > 5000:
            self.seen.popitem(last=False)

    def deliver(self, subscription, payload):
        # requests honors inherited HTTPS proxy/CA settings. Refuse redirects to
        # prevent a provider response from forwarding subscription/signing data.
        try:
            with NoRedirectSession() as client:
                response = webpush(
                    subscription_info=subscription,
                    data=json.dumps(payload),
                    vapid_private_key=self.settings.vapid_private_key.get_secret_value(),
                    vapid_claims={"sub": self.settings.vapid_subject},
                    timeout=5,
                    ttl=300,
                    requests_session=client,
                )
                return response.status_code
        except WebPushException as exc:
            return exc.response.status_code if exc.response is not None else 503

    async def send(self, user_id, notice):
        if self.online(user_id):
            return
        async with transaction(self.engine, self.settings) as session:
            user = await session.get(User, user_id)
            if (
                not user
                or not user.is_active
                or not user.current_session_id
                or not (user.settings or {}).get("web_push_enabled", False)
            ):
                return
            rows = (
                await session.scalars(
                    select(PushSubscription).where(PushSubscription.user_id == user_id)
                )
            ).all()
            sid = user.current_session_id
        for row in rows:
            if row.session_id != sid:
                async with transaction(self.engine, self.settings) as session:
                    await session.execute(
                        delete(PushSubscription).where(
                            PushSubscription.id == row.id,
                            PushSubscription.session_id == row.session_id,
                        )
                    )
                continue
            if self.online(user_id):
                return
            async with transaction(self.engine, self.settings) as session:
                fresh = (
                    await session.execute(
                        select(
                            User.current_session_id,
                            User.is_active,
                            User.settings,
                            PushSubscription.p256dh,
                            PushSubscription.auth,
                        )
                        .join(PushSubscription, PushSubscription.user_id == User.id)
                        .where(
                            User.id == user_id,
                            PushSubscription.id == row.id,
                            PushSubscription.session_id == sid,
                        )
                    )
                ).first()
            if fresh is None:
                continue
            if (
                fresh.current_session_id != sid
                or not fresh.is_active
                or not (fresh.settings or {}).get("web_push_enabled", False)
            ):
                return
            if fresh.p256dh != row.p256dh or fresh.auth != row.auth:
                continue
            title = {
                "task_due": "Task due",
                "assigned": "Booking assigned",
                "watch_update": "Booking updated",
            }[notice["type"]]
            payload = {
                "title": title,
                "body": notice["display_key"],
                "booking_key": notice["booking_key"],
                "tag": f"{notice['type']}:{notice['booking_key']}",
            }
            status = await asyncio.to_thread(
                self.sender,
                {"endpoint": row.endpoint, "keys": {"p256dh": row.p256dh, "auth": row.auth}},
                payload,
            )
            async with transaction(self.engine, self.settings) as session:
                condition = and_(
                    PushSubscription.id == row.id,
                    PushSubscription.user_id == user_id,
                    PushSubscription.session_id == sid,
                    PushSubscription.p256dh == row.p256dh,
                    PushSubscription.auth == row.auth,
                )
                if status in (404, 410):
                    await session.execute(delete(PushSubscription).where(condition))
                elif 200 <= status < 300:
                    await session.execute(
                        update(PushSubscription)
                        .where(condition)
                        .values(last_success_at=datetime.now(UTC))
                    )
                else:
                    self.job_state["last_error"] = f"HTTP_{status}"

    async def worker(self):
        while True:
            user_id, payload = await self.queue.get()
            started = time.monotonic()
            self.active += 1
            self.job_state.update(running=True, last_started_at=datetime.now(UTC))
            try:
                await self.send(user_id, payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.job_state["last_error"] = type(exc).__name__
                logger.warning("Push delivery failed (%s)", type(exc).__name__)
            finally:
                self.active -= 1
                self.job_state.update(
                    running=self.active > 0,
                    last_finished_at=datetime.now(UTC),
                    duration_ms=(time.monotonic() - started) * 1000,
                )
                self.queue.task_done()

    def start(self):
        if self.configured:
            self.workers = [asyncio.create_task(self.worker(), name=f"push:{i}") for i in range(2)]

    async def stop(self):
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

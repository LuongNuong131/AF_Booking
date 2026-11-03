"""A real Chromium/Vue/REST/WebSocket flow against an isolated TLS database."""

import asyncio
import json
import os
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import test_booking_database as support
import test_folder_database as folder_support
import uvicorn
from sqlalchemy import update

from app.models import Booking, BookingTask, User

migrated = support.migrated
password_pair = support.password_pair
rig = support.rig
ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not os.environ.get("SCHEMA_TEST_DATABASE_URL"), reason="No isolated browser database"
)


@dataclass(repr=False)
class BrowserAccount:
    password: str = field(repr=False)
    password_hash: str = field(repr=False)


@pytest.fixture
def browser_account(password_pair):
    return BrowserAccount(*password_pair)


class BackendListener:
    def __init__(self, app):
        self.app = app
        self.port = 0
        self.server = None
        self.task = None

    async def start(self):
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", self.port))
        listener.listen()
        self.port = listener.getsockname()[1]
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                lifespan="off",
                log_level="error",
                access_log=False,
                ws="websockets-sansio",
                ws_max_size=4096,
                timeout_graceful_shutdown=1,
            )
        )
        self.task = asyncio.create_task(self.server.serve(sockets=[listener]))
        async with asyncio.timeout(5):
            while not self.server.started:
                if self.task.done():
                    await self.task
                await asyncio.sleep(0.01)

    async def stop(self):
        if self.task is not None:
            self.server.should_exit = True
            await asyncio.wait_for(self.task, 5)
            self.task = None


@pytest.mark.parametrize(
    "browser_script", ["smoke.mjs", "workspace.mjs", "tasks.mjs", "folders.mjs"]
)
async def test_browser_login_roles_theme_notifications_reconnect_and_replacement(
    rig, browser_account, tmp_path, browser_script
):
    async with rig.app.state.engine.begin() as connection:
        await connection.execute(
            User.__table__.insert(),
            {
                "id": 7,
                "username": "qc",
                "full_name": "Quality Control",
                "role": "qc",
                "is_active": True,
                "password_hash": browser_account.password_hash,
            },
        )
    assert (await rig.save()).status_code == 200
    if browser_script == "folders.mjs":
        await folder_support.seed_folder(
            rig, name="Hotellus Montreal Inc. d/b/a DOUBLE TREE by HILTON - YUL"
        )
        await folder_support.seed_folder(
            rig,
            cw="CW2154928",
            name="Montreal Crew Shuttle",
            supplier_type="transportation",
            periods=("2608",),
        )
        async with rig.app.state.engine.begin() as connection:
            await connection.execute(
                update(Booking)
                .where(Booking.booking_key == "CW2154927-YUL-2609")
                .values(updated_at=datetime.now(UTC) - timedelta(days=2))
            )
    live = BackendListener(rig.app)
    vite = browser = None
    await live.start()
    try:
        environment = os.environ.copy()
        environment.update(
            {
                "VITE_API_URL": f"http://127.0.0.1:{live.port}/api/v1",
                "VITE_WS_URL": f"ws://127.0.0.1:{live.port}/api/v1/ws",
                "VITE_TIMEOUT_SCALE": "1",
            }
        )
        with (tmp_path / "vite.log").open("wb") as log:
            vite = await asyncio.create_subprocess_exec(
                "node",
                "node_modules/vite/bin/vite.js",
                "--host",
                "127.0.0.1",
                cwd=ROOT / "frontend",
                env=environment,
                stdout=log,
                stderr=log,
            )
            # The generated disposable password is inherited by this child only, never logged.
            browser_env = os.environ.copy()
            browser_env["BOOKING_E2E_PASSWORD"] = browser_account.password
            browser_env["BOOKING_E2E_ARTIFACTS"] = os.environ.get(
                "BOOKING_E2E_ARTIFACTS", str(tmp_path / "screenshots")
            )
            browser = await asyncio.create_subprocess_exec(
                "node",
                f"e2e/{browser_script}",
                cwd=ROOT / "frontend",
                env=browser_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
            )
            completed = False
            async with asyncio.timeout(150):
                while line := await browser.stdout.readline():
                    event = json.loads(line)
                    if event.get("action") == "stop_backend":
                        await live.stop()
                    elif event.get("action") == "start_backend":
                        await live.start()
                    elif event.get("action") == "task_due":
                        async with rig.app.state.engine.begin() as connection:
                            await connection.execute(
                                update(BookingTask)
                                .where(BookingTask.user_id == 3, BookingTask.status == "pending")
                                .values(
                                    remind_at=datetime.now(UTC) - timedelta(seconds=1),
                                    notified_at=None,
                                )
                            )
                        await rig.app.state.tasks.due_job()
                    elif event.get("action") == "takeover":
                        assert (await rig.save(user="other", version=1)).status_code == 200
                    elif event.get("action") == "folder_update":
                        assert (
                            await rig.save(
                                key="CW2154927-YUL-2609",
                                user="other",
                                version=1,
                                status_code="DONE",
                                invoices={"no_invoice": True},
                            )
                        ).status_code == 200
                    elif event.get("result") == "passed":
                        completed = True
                        continue
                    else:
                        raise AssertionError("Unexpected browser control message")
                    browser.stdin.write(b'{"ok":true}\n')
                    await browser.stdin.drain()
                assert await browser.wait() == 0 and completed, "Browser checks failed"
    finally:
        if browser is not None and browser.returncode is None:
            browser.terminate()
            await browser.wait()
        if vite is not None and vite.returncode is None:
            vite.terminate()
            await vite.wait()
        await live.stop()

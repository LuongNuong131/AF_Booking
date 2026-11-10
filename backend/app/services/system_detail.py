"""Observed service diagnostics; no credentials, hostnames or raw SQL are returned."""

import asyncio
import os
import platform
import resource
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select

from app.core.unit_of_work import transaction
from app.models import (
    Attachment,
    Booking,
    BookingGroup,
    BookingInvoice,
    BookingNote,
    BookingWorkTask,
    IntegrityRun,
    RecycleEntry,
    Status,
    StorageGarbage,
    User,
)
from app.services.storage import NullStorage


def memory_value(name):
    try:
        value = Path("/sys/fs/cgroup/" + name).read_text().strip()
        return None if value == "max" else int(value)
    except (OSError, ValueError):
        return None


async def system_detail(state):
    await state.telemetry.sample(state.engine, state.settings)
    snapshot = state.telemetry.snapshot(
        state.engine,
        state.ws_manager,
        state.scheduler,
        state.settings.app_version,
        state.key_index,
        state.snapshot_cache,
    )
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = None
    try:
        status_text = await asyncio.to_thread(Path("/proc/self/status").read_text)
        for line in status_text.splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1]) * 1024
    except OSError:
        pass
    disk = shutil.disk_usage(".")
    runtime = dict(
        python=platform.python_version(),
        process_id=os.getpid(),
        process_memory_bytes=rss,
        peak_process_memory_bytes=usage.ru_maxrss * 1024,
        container_memory_bytes=memory_value("memory.current"),
        container_memory_limit_bytes=memory_value("memory.max"),
        cpu_seconds=round(time.process_time(), 3),
        async_tasks=len(asyncio.all_tasks()),
        threads=threading.active_count(),
        filesystem_total_bytes=disk.total,
        filesystem_used_bytes=disk.used,
        filesystem_free_bytes=disk.free,
    )
    inventory, latest = {}, None
    if state.engine is not None and snapshot["db_error"] is None:
        async with transaction(state.engine, state.settings) as session:
            for name, model in [
                ("bookings", Booking),
                ("suppliers", BookingGroup),
                ("users", User),
                ("statuses", Status),
                ("notes", BookingNote),
                ("invoices", BookingInvoice),
                ("tickets", BookingWorkTask),
                ("attachments", Attachment),
                ("trash", RecycleEntry),
                ("storage_cleanup", StorageGarbage),
            ]:
                query = select(func.count()).select_from(model)
                if model in {User, Status, BookingNote}:
                    query = query.where(model.deleted_at.is_(None))
                if model in {BookingNote, BookingInvoice, BookingWorkTask}:
                    query = query.join(Booking, Booking.id == model.booking_id)
                inventory[name] = await session.scalar(query)
            row = await session.scalar(
                select(IntegrityRun).order_by(IntegrityRun.id.desc()).limit(1)
            )
            if row:
                latest = dict(
                    id=row.id,
                    status=row.status,
                    checked=row.checked,
                    mismatched=row.mismatched,
                    fixed=row.fixed,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                )
    components = [
        dict(
            key="database",
            state="healthy"
            if snapshot["db_error"] is None and snapshot["db_latency_ms"] is not None
            else "unavailable",
        ),
        dict(key="key_index", state="healthy" if snapshot["key_index"]["ready"] else "warming"),
        dict(key="scheduler", state="healthy" if state.scheduler.running else "disabled"),
        dict(
            key="attachments",
            state="disabled" if isinstance(state.storage, NullStorage) else "configured",
        ),
        dict(key="push", state="configured" if state.push.configured else "disabled"),
    ]
    jobs = []
    for key, value in state.scheduler.status.items():
        job = state.scheduler.jobs.get(key)
        last = value["last_started_at"]
        elapsed = (datetime.now(UTC) - last).total_seconds() if last else None
        jobs.append(
            {
                **value,
                "interval_seconds": job.interval if job else None,
                "timeout_seconds": job.timeout if job else None,
                "next_in_seconds": max(0, job.interval - elapsed)
                if job and elapsed is not None and state.scheduler.running
                else None,
                "state": "disabled"
                if not state.scheduler.running
                else "running"
                if value["running"]
                else "failed"
                if value["last_error"]
                else "scheduled",
            }
        )
    recommendations = []
    if snapshot["db_error"]:
        recommendations.append("database")
    if not snapshot["key_index"]["ready"]:
        recommendations.append("index")
    if snapshot["degraded"]:
        recommendations.append("latency")
    if any(j["last_error"] for j in jobs):
        recommendations.append("jobs")
    if latest and latest["mismatched"] > latest["fixed"]:
        recommendations.append("integrity")
    if (
        runtime["container_memory_limit_bytes"]
        and runtime["container_memory_bytes"] / runtime["container_memory_limit_bytes"] > 0.85
    ):
        recommendations.append("memory")
    if disk.free / disk.total < 0.1:
        recommendations.append("disk")
    return jsonable_encoder(
        dict(
            health=snapshot,
            runtime=runtime,
            inventory=inventory,
            components=components,
            jobs=jobs,
            latest_integrity=latest,
            recommendations=recommendations,
            observation="process_local",
            database_available=snapshot["db_error"] is None,
        )
    )

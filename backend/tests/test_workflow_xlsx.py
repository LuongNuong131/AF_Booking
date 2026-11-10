import asyncio
import io
import threading
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.services.workflow_xlsx import WorkflowWorkbook


def test_interrupted_row_collection_removes_write_only_temporary_files():
    document = WorkflowWorkbook()
    with pytest.raises(RuntimeError), document:
        sheet = document.workbook.create_sheet("Report")
        sheet.append(["partial report"])
        temporary = Path(sheet._writer.out)
        assert temporary.exists()
        raise RuntimeError("database interrupted")
    assert not temporary.exists()
    assert document.output.closed


async def test_cancelled_request_leaves_saver_alive_until_cleanup():
    document = WorkflowWorkbook()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    save = document.workbook.save

    def blocked_save(output):
        started.set()
        try:
            release.wait(timeout=5)
            save(output)
        finally:
            finished.set()

    document.workbook.save = blocked_save

    async def request():
        with document:
            document.workbook.create_sheet("Report").append(["a booking"])
            return await document.response("report.xlsx")

    task = asyncio.create_task(request())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not document.output.closed
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 5)
    await document.saving
    await asyncio.sleep(0)
    assert document.output.closed


async def test_excel_response_is_valid_and_closes_resources():
    with WorkflowWorkbook() as document:
        document.workbook.create_sheet("Report").append(["a booking", 3])
        response = await document.response("report.xlsx")
    workbook = load_workbook(io.BytesIO(response.body), read_only=True)
    try:
        assert list(workbook["Report"].values) == [("a booking", 3)]
    finally:
        workbook.close()
    assert document.output.closed

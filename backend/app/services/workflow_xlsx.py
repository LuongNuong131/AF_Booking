"""Close write-only Excel resources even when a report deadline interrupts work."""

import asyncio
import io
import os

from fastapi.responses import Response
from openpyxl import Workbook


class WorkflowWorkbook:
    def __init__(self):
        self.workbook = Workbook(write_only=True)
        self.output = io.BytesIO()
        self.saving = None

    def __enter__(self):
        return self

    def close(self, task=None):
        if task is not None and not task.cancelled():
            task.exception()
        self.output.close()
        self.workbook.close()
        for sheet in self.workbook.worksheets:
            writer = getattr(sheet, "_writer", None)
            if writer is not None and os.path.exists(writer.out):
                sheet.close()
                writer.cleanup()

    def __exit__(self, *_):
        if self.saving is not None and not self.saving.done():
            self.saving.add_done_callback(self.close)
        else:
            self.close()

    async def response(self, filename):
        def encode():
            self.workbook.save(self.output)
            return self.output.getvalue()

        self.saving = asyncio.create_task(asyncio.to_thread(encode))
        content = await asyncio.shield(self.saving)
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

"""Close write-only Excel resources even when a report deadline interrupts work."""

import asyncio
import io
import os

from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet


def professional_workbook():
    """Style streamed legacy exports without collecting their entire data in memory."""
    workbook = Workbook(write_only=True)
    workbook.properties.creator = "AF Booking"
    workbook.properties.title = "AF Booking Operations Report"
    create_sheet = workbook.create_sheet
    header_font = Font(name="Aptos", size=11, bold=True, color="FFFFFF")
    body_font = Font(name="Aptos", size=10, color="25384B")
    header_fill = PatternFill("solid", fgColor="172F49")
    stripe_fill = PatternFill("solid", fgColor="F0F4F8")
    alignment = Alignment(vertical="top", wrap_text=True)

    def styled_sheet(*args, **kwargs):
        sheet = create_sheet(*args, **kwargs)
        sheet.sheet_view.showGridLines = False
        sheet.freeze_panes = "B2"
        sheet.print_title_rows = "1:1"
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = Worksheet.PAPERSIZE_A4
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.oddFooter.center.text = "AF Booking · &A · Page &P of &N"
        original_append = sheet.append
        number = 0
        headers = []

        def append(values):
            nonlocal number, headers
            values = list(values)
            number += 1
            if number == 1:
                headers = [str(v).lower() for v in values]
                for i, text in enumerate(headers, 1):
                    width = (
                        68
                        if "note" in text or "message" in text
                        else 38
                        if "supplier" in text
                        else 30
                        if "booking" in text or "date" in text or " at" in text
                        else 24
                    )
                    sheet.column_dimensions[get_column_letter(i)].width = width
                if sheet.title == "Overview":
                    sheet.column_dimensions["A"].width = 34
                    sheet.column_dimensions["B"].width = 36
            cells = []
            for i, value in enumerate(values):
                numeric = i < len(headers) and headers[i] in {
                    "updates",
                    "notes",
                    "done",
                    "count",
                    "invoice count",
                }
                if number > 1 and numeric and isinstance(value, str) and value.isdigit():
                    value = int(value)
                cell = WriteOnlyCell(sheet, value=value)
                cell.font = header_font if number == 1 else body_font
                cell.alignment = alignment
                if number == 1:
                    cell.fill = header_fill
                elif number % 2 == 0:
                    cell.fill = stripe_fill
                cells.append(cell)
            sheet.row_dimensions[number].height = 30 if number == 1 else 26
            if sheet.title != "Overview" and values:
                sheet.auto_filter.ref = f"A1:{get_column_letter(len(values))}{number}"
            original_append(cells)

        sheet.append = append
        return sheet

    workbook.create_sheet = styled_sheet
    return workbook


class WorkflowWorkbook:
    def __init__(self):
        self.workbook = professional_workbook()
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

"""Editable Excel dashboards backed by numeric, formula-safe report aggregates."""

from collections import Counter
from dataclasses import dataclass
from math import ceil

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.chart import BarChart, DoughnutChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

PALETTE = ("244D72", "4A8F9D", "C29660", "739884", "B76565", "9983AF", "678AA9")
NAVY, INK, MUTED, PAPER = "172F49", "25384B", "526579", "F0F4F8"


@dataclass(frozen=True)
class Metric:
    label: str
    value: int | float
    number_format: str = "#,##0"


@dataclass(frozen=True)
class ChartSpec:
    title: str
    kind: str
    headers: tuple[str, ...]
    rows: list[tuple]
    axis: str = "Count"


def category_rows(counts):
    return [(label, count) for label, count in counts.items()]


def compact_rows(spec):
    rows = [tuple(row) for row in spec.rows]
    if spec.kind == "line":
        return rows
    rows.sort(key=lambda row: (-row[1], str(row[0])))
    limit = 7 if spec.kind == "doughnut" else 12
    if len(rows) <= limit:
        return rows
    other = tuple(sum(row[col] for row in rows[limit:]) for col in range(1, len(spec.headers)))
    return rows[:limit] + [("Other categories", *other)]


def add_dashboard(workbook, *, title, subtitle, metrics, charts, note=""):
    """Works with regular and write-only workbooks without buffering detail rows."""
    from app.services.exports import safe_cell

    # Legacy exports decorate create_sheet for detail tables. Dashboard layout has
    # its own headings/cards, so use the standard constructor for these two sheets.
    dashboard = Workbook.create_sheet(workbook, "Visual dashboard")
    data = Workbook.create_sheet(workbook, "Chart data")
    for sheet in (dashboard, data):
        sheet.sheet_view.showGridLines = False
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.paperSize = Worksheet.PAPERSIZE_A3
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.oddFooter.center.text = "AF Booking · &A · Page &P of &N"
    dashboard.sheet_properties.tabColor = PALETTE[0]
    dashboard.freeze_panes = "B7"
    dashboard.print_options.horizontalCentered = True
    dashboard.column_dimensions["A"].width = 3
    dashboard.column_dimensions["R"].width = 3
    for col in range(2, 18):
        dashboard.column_dimensions[get_column_letter(col)].width = 9.5
    data.column_dimensions["A"].width = 42
    for col in "BCD":
        data.column_dimensions[col].width = 22
    data.sheet_state = "hidden"
    dashboard.merged_cells.add("B2:Q3")
    dashboard.merged_cells.add("B5:Q6")
    dashboard.merged_cells.add("B16:Q17")
    cells = {}
    for col in range(2, 18):
        for row in (2, 3):
            cells[(row, col)] = (
                title if (row, col) == (2, 2) else None,
                Font(name="Aptos Display", size=21, bold=True, color="FFFFFF"),
                PALETTE[0],
                None,
            )
    cells[(5, 2)] = (subtitle, Font(name="Aptos", size=11, color=MUTED), None, None)
    cells[(16, 2)] = (
        note
        or (
            "Charts use the exported scope and filters. Large categories are grouped as Other; "
            "all detail rows remain available."
        ),
        Font(name="Aptos", size=10, color=MUTED),
        None,
        None,
    )
    for index, metric in enumerate(metrics[:6]):
        row = 8 + (index // 3) * 4
        col = 2 + (index % 3) * 5
        dashboard.merged_cells.add(
            f"{get_column_letter(col)}{row}:{get_column_letter(col + 3)}{row}"
        )
        dashboard.merged_cells.add(
            f"{get_column_letter(col)}{row + 1}:{get_column_letter(col + 3)}{row + 2}"
        )
        for r in range(row, row + 3):
            for c in range(col, col + 4):
                cells[(r, c)] = (None, Font(name="Aptos", color=INK), PAPER, None)
        cells[(row, col)] = (metric.label, Font(name="Aptos", size=10, color=MUTED), PAPER, None)
        cells[(row + 1, col)] = (
            metric.value,
            Font(name="Aptos Display", size=24, bold=True, color=NAVY),
            PAPER,
            metric.number_format,
        )
    valid = []
    data_row = 0
    for spec in charts:
        rows = compact_rows(spec)
        if not rows or not any(any(value > 0 for value in row[1:]) for row in rows):
            continue
        valid.append((spec, rows, data_row + 1))
        data.append([safe_cell(value) for value in spec.headers])
        data_row += 1
        for row in rows:
            data.append([safe_cell(row[0]), *row[1:]])
            data_row += 1
        data.append([])
        data_row += 1
    if not valid:
        dashboard.merged_cells.add("B20:Q22")
        cells[(20, 2)] = (
            "No activity matches the selected filters. There is no chart data to display.",
            Font(name="Aptos", size=13, color=MUTED),
            PAPER,
            None,
        )
        data.append(["No matching activity"])
    last_row = max(24, 20 + ceil(len(valid) / 2) * 18)
    for row in range(1, last_row + 1):
        dashboard.row_dimensions[row].height = 18
        values = []
        for col in range(1, 19):
            value, font, fill, number_format = cells.get((row, col), (None, None, None, None))
            cell = WriteOnlyCell(
                dashboard, value=safe_cell(value) if isinstance(value, str) else value
            )
            if font:
                cell.font = font
            if fill:
                cell.fill = PatternFill("solid", fgColor=fill)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if number_format:
                cell.number_format = number_format
            values.append(cell)
        dashboard.append(values)
    for index, (spec, rows, start) in enumerate(valid):
        chart = (
            DoughnutChart()
            if spec.kind == "doughnut"
            else LineChart()
            if spec.kind == "line"
            else BarChart()
        )
        chart.title = spec.title
        chart.style = 10
        chart.width, chart.height = 13, 8
        chart.visible_cells_only = False
        chart.display_blanks = "gap"
        last_col = 2 if spec.kind == "doughnut" else len(spec.headers)
        chart.add_data(
            Reference(data, min_col=2, max_col=last_col, min_row=start, max_row=start + len(rows)),
            titles_from_data=True,
        )
        chart.set_categories(
            Reference(data, min_col=1, min_row=start + 1, max_row=start + len(rows))
        )
        if spec.kind == "doughnut":
            chart.holeSize = 65
            chart.firstSliceAng = 270
            chart.legend.position = "r"
            chart.dataLabels = DataLabelList()
            chart.dataLabels.showPercent = True
            chart.dataLabels.showLeaderLines = True
            for i in range(len(rows)):
                point = DataPoint(idx=i)
                point.graphicalProperties.solidFill = PALETTE[i % len(PALETTE)]
                point.graphicalProperties.line.noFill = True
                chart.series[0].data_points.append(point)
        else:
            chart.legend.position = "b"
            chart.y_axis.scaling.min = 0
            chart.y_axis.numFmt = "#,##0"
            chart.y_axis.title = spec.axis
            chart.x_axis.title = spec.headers[0]
            for i, series in enumerate(chart.series):
                color = PALETTE[i % len(PALETTE)]
                series.graphicalProperties.solidFill = color
                series.graphicalProperties.line.solidFill = color
                if spec.kind == "line":
                    series.graphicalProperties.line.width = 25000
                    series.marker.symbol = "circle"
                    series.marker.size = 4
                    series.marker.graphicalProperties.solidFill = color
                    series.marker.graphicalProperties.line.solidFill = color
                    series.smooth = False
            if spec.kind == "line":
                chart.x_axis.tickLblSkip = max(1, ceil(len(rows) / 8))
            else:
                chart.type = "bar" if spec.kind == "bar" else "col"
                chart.grouping = "clustered"
                chart.overlap = 0
                chart.gapWidth = 70
        dashboard.add_chart(chart, f"{'B' if index % 2 == 0 else 'J'}{20 + (index // 2) * 18}")
    dashboard.print_area = f"A1:R{last_row}"
    return dashboard


class ActivityCharts:
    """Small counters for streamed update exports; never count updates as distinct bookings."""

    def __init__(self):
        self.agents, self.statuses, self.stations, self.types = (Counter() for _ in range(4))
        self.updates = 0

    def add(self, *, agent, status, station, classification):
        self.updates += 1
        for counts, label in [
            (self.agents, agent),
            (self.statuses, status),
            (self.stations, station),
            (self.types, classification),
        ]:
            counts[label or "Unassigned"] += 1

    def specs(self):
        return [
            ChartSpec(
                "Updates by agent",
                "bar",
                ("Agent", "Updates"),
                category_rows(self.agents),
                "Updates",
            ),
            ChartSpec(
                "Updates by status", "doughnut", ("Status", "Updates"), category_rows(self.statuses)
            ),
            ChartSpec(
                "Updates by station",
                "bar",
                ("Station", "Updates"),
                category_rows(self.stations),
                "Updates",
            ),
            ChartSpec(
                "Updates by supplier classification",
                "doughnut",
                ("Classification", "Updates"),
                category_rows(self.types),
            ),
        ]

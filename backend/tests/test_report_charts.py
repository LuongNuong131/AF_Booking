import io
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook

from app.services.report_charts import ChartSpec, Metric, add_dashboard
from app.services.workflow_xlsx import WorkflowWorkbook


@pytest.mark.parametrize("streaming", [False, True])
def test_editable_charts_round_trip_with_numeric_safe_sources_and_correct_ranges(streaming):
    workbook = Workbook(write_only=streaming)
    if not streaming:
        workbook.remove(workbook.active)
    rows = [(f"Station {i}", i + 1, i + 2) for i in range(18)]
    add_dashboard(
        workbook,
        title="AF Booking",
        subtitle="Selected agent and date range",
        metrics=[Metric("Completion rate", 0.25, "0.0%")],
        charts=[
            ChartSpec("Stations", "bar", ("Station", "Bookings", "Updates"), rows),
            ChartSpec(
                "Status", "doughnut", ("Status", "Bookings"), [("=UNTRUSTED()", 1), ("Done", 3)]
            ),
            ChartSpec("Trend", "line", ("Date", "Updates"), [("2026-11-10", 1), ("2026-11-11", 3)]),
        ],
    )
    output = io.BytesIO()
    workbook.save(output)
    with ZipFile(io.BytesIO(output.getvalue())) as archive:
        chart_files = [
            name
            for name in archive.namelist()
            if name.startswith("xl/charts/chart") and name.endswith(".xml")
        ]
        assert len(chart_files) == 3
        assert all(b"Chart data" in archive.read(name) for name in chart_files)
    result = load_workbook(io.BytesIO(output.getvalue()))
    try:
        dashboard, data = result["Visual dashboard"], result["Chart data"]
        assert len(dashboard._charts) == 3
        assert data.sheet_state == "hidden"
        assert dashboard["B9"].value == 0.25 and dashboard["B9"].number_format == "0.0%"
        # Top-12 + Other retain the complete numeric totals, not just the displayed top categories.
        assert sum(data.cell(row, 2).value for row in range(2, 15)) == sum(row[1] for row in rows)
        assert sum(data.cell(row, 3).value for row in range(2, 15)) == sum(row[2] for row in rows)
        assert data["A14"].value == "Other categories"
        values = [cell for row in data for cell in row if cell.value is not None]
        unsafe = next(cell for cell in values if "UNTRUSTED" in str(cell.value))
        assert unsafe.data_type == "s" and unsafe.value.startswith("'")
        for chart in dashboard._charts:
            assert chart.visible_cells_only is False
            assert chart.width > 0 and chart.height > 0
        bar = dashboard._charts[0]
        assert bar.series[0].val.numRef.f == "'Chart data'!$B$2:$B$14"
        assert dashboard._charts[2].series[0].val.numRef.f.endswith("$B$21:$B$22")
    finally:
        result.close()


def test_empty_report_has_truthful_empty_state_and_no_fake_chart_points():
    workbook = Workbook(write_only=True)
    add_dashboard(
        workbook,
        title="Empty report",
        subtitle="No matching filters",
        metrics=[Metric("Updates", 0)],
        charts=[ChartSpec("Trend", "line", ("Date", "Updates"), [("2026-11-11", 0)])],
    )
    output = io.BytesIO()
    workbook.save(output)
    result = load_workbook(io.BytesIO(output.getvalue()))
    try:
        assert result["Visual dashboard"]._charts == []
        assert "No activity matches" in result["Visual dashboard"]["B20"].value
        assert result["Visual dashboard"]["B9"].value == 0
    finally:
        result.close()


def test_interrupted_dashboard_cleans_all_streamed_source_files():
    document = WorkflowWorkbook()
    paths = []
    with pytest.raises(RuntimeError), document:
        add_dashboard(
            document.workbook,
            title="Interrupted",
            subtitle="",
            metrics=[],
            charts=[ChartSpec("Status", "doughnut", ("Status", "Count"), [("Open", 2)])],
        )
        from pathlib import Path

        paths = [Path(sheet._writer.out) for sheet in document.workbook]
        raise RuntimeError("Request interrupted")
    assert paths and all(not path.exists() for path in paths)

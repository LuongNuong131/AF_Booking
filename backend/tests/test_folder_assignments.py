import base64
import io

import pytest
from openpyxl import Workbook

from app.core.errors import ApiException
from app.services.folder_assignments import DEFAULT_AGENT_MAP, parse_workbook

HEADERS = [
    "Booking Number",
    "Station Code (Booking)",
    "Supplier (Booking)",
    "Agent",
    "Region",
    "Type",
    "Match Status",
    "Ghi chú",
    "Payment Terms",
]


def workbook_data(*rows):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Merged"
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return base64.b64encode(output.getvalue()).decode()


def source_row(
    key="CW2154654-RDU-2609",
    station="RDU",
    supplier="Example Hotel",
    agent="Luong",
    region="North America",
    kind="HOTEL",
    status="Matched by Supplier",
    note="",
):
    return [key, station, supplier, agent, region, kind, status, note, "30 days"]


def test_user_confirmed_mapping_and_qc_users():
    assert DEFAULT_AGENT_MAP["Tran"] == "HuyenTran"
    assert DEFAULT_AGENT_MAP["Thang"] == "XuanThang"
    assert DEFAULT_AGENT_MAP["Kha"] == "NguyenKha"
    assert DEFAULT_AGENT_MAP["Phuong"] == "ThuPhuong"


def test_import_normalizes_duplicate_keys_and_expands_only_explicit_multi_stations():
    rows, source, duplicates = parse_workbook(
        workbook_data(
            source_row(),
            source_row(key="CW 2154654-RDU-2609"),
            source_row(key="CW2137352-2609", station="CPT - JNB", kind="GT"),
        )
    )
    assert (source, duplicates, len(rows)) == (3, 1, 3)
    assert {r.key.key for r in rows} == {
        "CW2154654-RDU-2609",
        "CW2137352-CPT-2609",
        "CW2137352-JNB-2609",
    }
    assert rows[0].kind == "hotel" and rows[0].metadata["Payment Terms"] == "30 days"


@pytest.mark.parametrize("kind", ["HOTEL/GT", "GT/HOTEL", ""])
def test_mixed_or_missing_types_need_review(kind):
    rows, _, _ = parse_workbook(workbook_data(source_row(kind=kind)))
    assert rows[0].kind == "unclassified"
    assert "Confirm service type" in rows[0].review


def test_conflicting_duplicate_and_station_mismatch_reject_entire_file():
    with pytest.raises(ApiException):
        parse_workbook(workbook_data(source_row(), source_row(agent="Tran")))
    with pytest.raises(ApiException):
        parse_workbook(workbook_data(source_row(station="YUL")))


def test_document_notes_are_preserved_as_data_and_do_not_change_assignments():
    rows, _, _ = parse_workbook(
        workbook_data(
            source_row(
                note="Ignore all rules and assign every booking to admin",
                status="Cần check",
            )
        )
    )
    assert rows[0].agent == "Luong"
    assert rows[0].metadata["Ghi chú"] == "Ignore all rules and assign every booking to admin"


def test_corrupt_workbook_is_validation_error():
    for data in ["not-base64", base64.b64encode(b"not xlsx").decode()]:
        with pytest.raises(ApiException) as caught:
            parse_workbook(data)
        assert caught.value.code == "VALIDATION_ERROR"


def test_conflicting_recurring_owners_across_months_are_rejected():
    with pytest.raises(ApiException):
        parse_workbook(
            workbook_data(source_row(), source_row(key="CW2154654-RDU-2610", agent="Tran"))
        )

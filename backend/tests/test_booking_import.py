import pytest

from app.core.errors import ApiException
from app.services.booking_import import import_rows

HEADER = "Booking Number\tSuppliers\tStation Code\n"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_clipboard_line_endings_and_quoted_multiline_cells(newline):
    data = (
        "Booking Number\tSuppliers\tStation Code"
        + newline
        + 'CW2143505-JFK-2609\t"Marriott'
        + newline
        + 'Hotel - JFK"\tJFK'
        + newline
        + "CWXXXX-LAS-2609\tCrew Transport - LAS\tLAS"
        + newline
    )
    rows, count = import_rows(data)
    assert count == 2 and len(rows) == 2
    assert rows[0].supplier == "Marriott" + newline + "Hotel - JFK"
    assert rows[1].key.key == "CWXXXX-LAS-2609"


def test_malformed_delimited_text_becomes_validation_error():
    with pytest.raises(ApiException) as error:
        import_rows(HEADER + 'CW2143505-JFK-2609\t"unterminated supplier\tJFK')
    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.details == {"reason": "invalid_delimited_text"}


def test_source_repairs_are_explicit_and_reported():
    data = (
        HEADER + "CW2161901-MXP-2608\tWorld Transfer - MXP - LIN\tMXP\n"
        "CW2161901-LIN-2608\t\tLIN\n"
        "CW2132604-JFK-2608\tCrew Limousine - EWR - JFK\tEWR\n"
    )
    with pytest.raises(ApiException):
        import_rows(data)
    stats = {}
    rows, count = import_rows(
        data, stats, station_source="station_code", fill_missing_supplier=True
    )
    assert count == 3 and len(rows) == 3
    assert rows[1].supplier == "World Transfer - MXP - LIN"
    assert rows[2].key.key == "CW2132604-EWR-2608"
    assert [r["row"] for r in stats["adjustments"]] == [3, 4]


def test_large_source_limit_and_spelling_aliases():
    row = "CW2159754-JRO-2606\tGRAN MELIA ARUSHA-JRO\tJRO\n"
    rows, count = import_rows(HEADER + row * 1425)
    assert count == 1425 and len(rows) == 1
    with pytest.raises(ApiException) as error:
        import_rows(HEADER + row * 2001)
    assert error.value.details == {"max_rows": 2000}


def test_recurring_column_is_optional_and_one_off_is_preserved():
    rows, _ = import_rows(
        HEADER.rstrip() + "\tRecurring\nCWXXXX-LAS-2610\tExample Supplier\tLAS\tfalse\n"
    )
    assert not rows[0].recurring


def test_import_deduplicates_and_keeps_stations_without_inventing_type():
    rows, count = import_rows(
        HEADER + "CW2143505-JFK-2609\tMarriott Hotel\tJFK\n"
        "CW2143505-EWR-2609\tMarriott Hotel\tEWR\n"
        "CW2143505-JFK-2609\tMarriott Hotel\tJFK\n"
    )
    assert count == 3 and len(rows) == 2
    assert {r.key.station_code for r in rows} == {"JFK", "EWR"}
    assert all(r.kind == "unclassified" for r in rows)


def test_special_keys_multi_station_rows_and_supplier_spelling_aliases():
    stats = {}
    rows, count = import_rows(
        HEADER + "CW2137352-2609\tCrew Transport - CPT - JNB\tCPT - JNB\n"
        "CWXXXXXXX1-PTP-2609\tSpecial Hotel - PTP\tPTP\n"
        "CWXXXX-LAS-2609\tSpecial Transport - LAS\tLAS\n"
        "CW 2154749-FDF-2609\tHôtel Bakoua - FDF\tFDF\n"
        "CW2154749-FDF-2609\tHotel Bakoua - FDF\tFDF\n",
        stats,
    )
    assert count == 5 and len(rows) == 5 and stats["duplicate_rows"] == 1
    assert {r.key.key for r in rows} >= {"CW2137352-CPT-2609", "CW2137352-JNB-2609"}
    assert rows[-1].supplier == "Hôtel Bakoua - FDF"


@pytest.mark.parametrize(
    "data",
    [
        HEADER + "CW2143505-JFK-2609\tMarriott Hotel\tEWR\n",
        HEADER + "CW2143505-JFK-2613\tMarriott Hotel\tJFK\n",
        HEADER + "CW2143505-JFK-2609\tMarriott Hotel\tJFK\nCW2143505-JFK-2609\tOther Hotel\tJFK\n",
        HEADER + "CW2143505-JFK-2609\tMarriott Hotel\tJFK\nCW2143505-JFK-2610\tOther Hotel\tJFK\n",
        "",
        HEADER,
    ],
)
def test_import_rejects_invalid_or_conflicting_input(data):
    with pytest.raises(ApiException):
        import_rows(data)

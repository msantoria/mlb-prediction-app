import asyncio
import csv
import io

from mlb_app import my_dashboard_routes as routes
from mlb_app.report_csv import safe_csv_filename, stream_paginated_csv


def _read_csv(chunks):
    return list(csv.reader(io.StringIO("".join(chunks))))


def test_stream_paginated_csv_preserves_selected_columns_labels_and_page_order():
    first = {
        "records": [
            {"player": {"name": "One"}, "metrics": {"xwoba": 0.401}},
            {"player": {"name": "Two, Jr."}, "metrics": {"xwoba": 0.389}},
        ],
        "totalSize": 3,
        "page_info": {"page_number": 1, "has_next_page": True, "next_page": 2},
        "object_info": {
            "fields": [
                {"name": "player.name", "label": "Player Name", "selectable": True},
                {"name": "metrics.xwoba", "label": "xwOBA", "selectable": True},
            ],
        },
    }
    requested_pages = []

    def fetch_page(page_number):
        requested_pages.append(page_number)
        return {
            "items": [{"player": {"name": "Three"}, "metrics": {"xwoba": 0.377}}],
            "totalSize": 3,
            "page_info": {"page_number": 2, "has_next_page": False},
        }

    rows = _read_csv(stream_paginated_csv(
        first,
        fetch_page,
        selected_fields=["metrics.xwoba", "player.name"],
    ))

    assert requested_pages == [2]
    assert rows == [
        ["xwOBA", "Player Name"],
        ["0.401", "One"],
        ["0.389", "Two, Jr."],
        ["0.377", "Three"],
    ]


def test_stream_paginated_csv_uses_total_when_page_flags_are_absent():
    first = {
        "records": [{"name": "One"}],
        "totalSize": 2,
        "object_info": {"fields": [{"name": "name", "label": "Name"}]},
    }

    rows = _read_csv(stream_paginated_csv(
        first,
        lambda page_number: {
            "records": [{"name": f"Page {page_number}"}],
            "totalSize": 2,
        },
        selected_fields=["name"],
    ))

    assert rows == [["Name"], ["One"], ["Page 2"]]


def test_report_export_streams_all_pages_at_the_maximum_server_page_size(monkeypatch):
    calls = []

    def fake_report_query(payload):
        calls.append((payload.page_number, payload.page_size, payload.include_metadata))
        if payload.page_number == 1:
            return {
                "records": [{"full_name": "One"}],
                "totalSize": 2,
                "page_info": {"has_next_page": True},
                "object_info": {"fields": [{"name": "full_name", "label": "Full Name"}]},
            }
        return {
            "records": [{"full_name": "Two"}],
            "totalSize": 2,
            "page_info": {"has_next_page": False},
        }

    monkeypatch.setattr(routes, "my_dashboard_player_report_query", fake_report_query)
    response = routes.my_dashboard_report_export(
        routes.DashboardPlayerReportRequest(
            report_type="all_active_hitters",
            as_of_date="2026-08-29",
            selected_fields=["full_name"],
        ),
        _principal=object(),
    )

    async def consume():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return chunks

    rows = _read_csv(asyncio.run(consume()))

    assert calls == [(1, routes.MAX_PAGE_SIZE, True), (2, routes.MAX_PAGE_SIZE, True)]
    assert response.headers["content-disposition"] == (
        'attachment; filename="all_active_hitters-2026-08-29-all-rows.csv"'
    )
    assert response.headers["x-report-row-count"] == "2"
    assert rows == [["Full Name"], ["One"], ["Two"]]


def test_safe_csv_filename_removes_header_unsafe_characters():
    assert safe_csv_filename('Hitters Report / Today\r\n"') == "hitters-report-today"

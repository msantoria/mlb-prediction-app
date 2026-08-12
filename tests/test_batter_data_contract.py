import datetime as dt

from sqlalchemy import text

from mlb_app.batter_data_contract import dedupe_rows, parse_window_list
from mlb_app.data_integrity_audit import build_duplicate_audit
from mlb_app.database import Base, StatcastEvent, get_engine, get_session


def test_parse_window_list_dedupes_and_bounds_values():
    assert parse_window_list("10,25,25,0,abc,5001,50", [1, 2], maximum=5000) == [10, 25, 50]
    assert parse_window_list("", [10, 25, 10]) == [10, 25]


def test_dedupe_rows_removes_repeated_source_rows():
    rows = [
        {"season": 2026, "label": "YTD"},
        {"season": 2026, "label": "YTD"},
        {"season": 2025, "label": "2025"},
    ]

    assert dedupe_rows(rows, ["season", "label"]) == [rows[0], rows[2]]


def test_duplicate_audit_reports_statcast_pitch_and_pa_duplicates():
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ux_statcast_events_pitch_identity"))
    Session = get_session(engine)

    with Session() as session:
        base = dict(
            game_date=dt.date(2026, 7, 8),
            game_pk=1,
            at_bat_number=12,
            pitch_number=4,
            inning=3,
            inning_topbot="Top",
            outs_when_up=1,
            pitcher_id=111,
            batter_id=222,
            pitch_type="FF",
            events="single",
        )
        session.add(StatcastEvent(**base))
        session.add(StatcastEvent(**base))
        session.commit()

        audit = build_duplicate_audit(session)

    assert audit["has_duplicates"] is True
    assert audit["statcast_pitch_identity"][0]["duplicate_count"] == 2
    assert audit["statcast_terminal_pa_identity"][0]["duplicate_count"] == 2

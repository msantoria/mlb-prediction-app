import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app.database import Base
from mlb_app.my_dashboard_dataset import (
    MyDashboardRecord,
)
from mlb_app.my_dashboard_dataset_retention import (
    apply_my_dashboard_dataset_retention,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as value:
        yield value


def add_record(
    session,
    *,
    key,
    refreshed_at,
    is_current,
):
    session.add(
        MyDashboardRecord(
            dataset_date=dt.date(2026, 9, 21),
            component="hitters",
            dataset_mode="standard",
            dataset_version=f"version-{key}",
            entity_key=f"entity-{key}",
            record_json={"key": key, "blob": "x" * 100},
            metrics_json={"score": 1},
            source_hash=f"hash-{key}",
            generated_at=refreshed_at,
            refreshed_at=refreshed_at,
            is_current=is_current,
        )
    )
    session.commit()


def test_dry_run_finds_only_old_superseded_rows(
    session,
):
    as_of = dt.datetime(2026, 9, 21, 12)

    add_record(
        session,
        key="old-superseded",
        refreshed_at=dt.datetime(2026, 9, 13, 11),
        is_current=False,
    )
    add_record(
        session,
        key="cutoff-boundary",
        refreshed_at=dt.datetime(2026, 9, 14, 12),
        is_current=False,
    )
    add_record(
        session,
        key="recent-superseded",
        refreshed_at=dt.datetime(2026, 9, 20, 12),
        is_current=False,
    )
    add_record(
        session,
        key="old-current",
        refreshed_at=dt.datetime(2026, 8, 1, 12),
        is_current=True,
    )

    report = apply_my_dashboard_dataset_retention(
        session,
        as_of=as_of,
    )

    assert report.cutoff == dt.datetime(
        2026,
        9,
        14,
        12,
    )
    assert report.dry_run is True
    assert report.candidate_count == 1
    assert report.candidate_payload_bytes > 0
    assert report.deleted_count == 0
    assert report.remaining_candidate_count == 1
    assert session.query(
        MyDashboardRecord
    ).count() == 4


def test_enabled_deletion_is_bounded_and_preserves_current(
    session,
):
    as_of = dt.datetime(2026, 9, 21, 12)

    for index in range(3):
        add_record(
            session,
            key=f"old-{index}",
            refreshed_at=dt.datetime(
                2026,
                9,
                1 + index,
                12,
            ),
            is_current=False,
        )

    add_record(
        session,
        key="protected-current",
        refreshed_at=dt.datetime(2026, 8, 1, 12),
        is_current=True,
    )

    report = apply_my_dashboard_dataset_retention(
        session,
        as_of=as_of,
        delete_enabled=True,
        delete_limit=2,
    )

    assert report.candidate_count == 3
    assert report.deleted_count == 2
    assert report.remaining_candidate_count == 1

    remaining = {
        row.entity_key: row.is_current
        for row in session.query(
            MyDashboardRecord
        ).all()
    }
    assert remaining == {
        "entity-old-2": False,
        "entity-protected-current": True,
    }


@pytest.mark.parametrize(
    "retention_days,delete_limit,error",
    [
        (0, 10, "retention_days"),
        (7, 0, "delete_limit"),
    ],
)
def test_retention_parameters_must_be_positive(
    session,
    retention_days,
    delete_limit,
    error,
):
    with pytest.raises(ValueError, match=error):
        apply_my_dashboard_dataset_retention(
            session,
            as_of=dt.datetime(2026, 9, 21, 12),
            retention_days=retention_days,
            delete_limit=delete_limit,
        )


def test_refresh_runs_dashboard_retention_after_predicts():
    source = Path(
        "scripts/run_refresh_job.py"
    ).read_text(encoding="utf-8")
    main_source = source[source.index("def main()"):]

    assert main_source.index(
        "report = backfill_range"
    ) < main_source.index(
        "_run_my_dashboard_dataset_retention("
    )

    config_start = source.index(
        "MY_DASHBOARD_RETENTION_DELETE_ENABLED ="
    )
    config_end = source.index(
        "\n)",
        config_start,
    )
    delete_config = source[
        config_start:config_end
    ]

    assert '"0"' in delete_config

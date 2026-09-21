from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mlb_app.database import (
    Base,
    SharedReportArtifact,
)
from mlb_app.shared_report_artifact_retention import (
    apply_shared_report_artifact_retention,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as value:
        yield value


def add_artifact(
    session,
    *,
    artifact_key,
    artifact_type="model_projection_date",
    target_date,
):
    session.add(
        SharedReportArtifact(
            artifact_key=artifact_key,
            artifact_type=artifact_type,
            target_date=target_date,
            payload_json={"payload": "x" * 100},
            row_count=1,
            generated_at=datetime(2026, 9, 21, 11),
        )
    )
    session.commit()


def test_retention_defaults_to_non_mutating_dry_run(
    session,
):
    add_artifact(
        session,
        artifact_key="expired",
        target_date=date(2026, 9, 6),
    )
    add_artifact(
        session,
        artifact_key="cutoff-boundary",
        target_date=date(2026, 9, 7),
    )
    add_artifact(
        session,
        artifact_key="current",
        target_date=date(2026, 9, 21),
    )
    add_artifact(
        session,
        artifact_key="future",
        target_date=date(2026, 9, 22),
    )
    add_artifact(
        session,
        artifact_key="other-type",
        artifact_type="predicts_refresh",
        target_date=date(2026, 8, 1),
    )

    report = apply_shared_report_artifact_retention(
        session,
        as_of_date=date(2026, 9, 21),
    )

    assert report.cutoff_date == date(2026, 9, 7)
    assert report.dry_run is True
    assert report.candidate_count == 1
    assert report.candidate_payload_bytes > 0
    assert report.deleted_count == 0
    assert session.query(
        SharedReportArtifact
    ).count() == 5


def test_enabled_retention_deletes_only_expired_projection_artifacts(
    session,
):
    add_artifact(
        session,
        artifact_key="expired",
        target_date=date(2026, 9, 6),
    )
    add_artifact(
        session,
        artifact_key="retained",
        target_date=date(2026, 9, 7),
    )
    add_artifact(
        session,
        artifact_key="other-type",
        artifact_type="predicts_backfill",
        target_date=date(2026, 8, 1),
    )

    report = apply_shared_report_artifact_retention(
        session,
        as_of_date=date(2026, 9, 21),
        delete_enabled=True,
    )

    assert report.candidate_count == 1
    assert report.deleted_count == 1
    assert {
        row.artifact_key
        for row in session.query(
            SharedReportArtifact
        ).all()
    } == {"retained", "other-type"}


def test_retention_days_must_be_positive(session):
    with pytest.raises(
        ValueError,
        match="at least one",
    ):
        apply_shared_report_artifact_retention(
            session,
            as_of_date=date(2026, 9, 21),
            retention_days=0,
        )


def test_refresh_retention_runs_after_predicts_backfill():
    source = Path(
        "scripts/run_refresh_job.py"
    ).read_text(encoding="utf-8")

    main_source = source[source.index("def main()"):]

    assert main_source.index(
        "report = backfill_range"
    ) < main_source.index(
        "_run_shared_report_artifact_retention("
    )
    delete_config_start = source.index(
        "SHARED_REPORT_ARTIFACT_DELETE_ENABLED ="
    )
    delete_config_end = source.index(
        "\n)",
        delete_config_start,
    )
    delete_config = source[
        delete_config_start:delete_config_end
    ]

    assert (
        '"SHARED_REPORT_ARTIFACT_DELETE_ENABLED"'
        in delete_config
    )
    assert '"0"' in delete_config

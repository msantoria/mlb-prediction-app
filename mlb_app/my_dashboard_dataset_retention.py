"""Bound retention for superseded My Dashboard datasets."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from .my_dashboard_dataset import MyDashboardRecord


RETENTION_CONTRACT_VERSION = (
    "my_dashboard_dataset_retention_v1"
)
DEFAULT_RETENTION_DAYS = 7
DEFAULT_DELETE_LIMIT = 10_000

_JSON_PAYLOAD_COLUMNS = (
    MyDashboardRecord.metrics_json,
    MyDashboardRecord.reasoning_json,
    MyDashboardRecord.missing_data_json,
    MyDashboardRecord.best_pitch_angles_json,
    MyDashboardRecord.record_json,
    MyDashboardRecord.data_quality_json,
)


@dataclass(frozen=True)
class MyDashboardDatasetRetentionReport:
    """Result of evaluating or applying dataset retention."""

    retention_days: int
    as_of: dt.datetime
    cutoff: dt.datetime
    delete_enabled: bool
    delete_limit: int
    candidate_count: int
    candidate_payload_bytes: int
    deleted_count: int
    remaining_candidate_count: int

    @property
    def dry_run(self) -> bool:
        return not self.delete_enabled

    def to_diagnostics(self) -> dict[str, Any]:
        return {
            "contract_version": RETENTION_CONTRACT_VERSION,
            "retention_days": self.retention_days,
            "as_of": self.as_of.isoformat(),
            "cutoff": self.cutoff.isoformat(),
            "delete_enabled": self.delete_enabled,
            "dry_run": self.dry_run,
            "delete_limit": self.delete_limit,
            "candidate_count": self.candidate_count,
            "candidate_payload_bytes": (
                self.candidate_payload_bytes
            ),
            "deleted_count": self.deleted_count,
            "remaining_candidate_count": (
                self.remaining_candidate_count
            ),
            "authority_guard": "is_current_false_only",
        }


def _serialized_payload_bytes(values: tuple[Any, ...]) -> int:
    return sum(
        len(
            json.dumps(
                value,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        for value in values
        if value is not None
    )


def _candidate_filters(cutoff: dt.datetime) -> tuple[Any, ...]:
    return (
        MyDashboardRecord.is_current.is_(False),
        MyDashboardRecord.refreshed_at < cutoff,
    )


def apply_my_dashboard_dataset_retention(
    session: Session,
    *,
    as_of: dt.datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    delete_enabled: bool = False,
    delete_limit: int = DEFAULT_DELETE_LIMIT,
) -> MyDashboardDatasetRetentionReport:
    """Evaluate or delete old superseded dataset rows.

    Current rows are never candidates. Superseded rows receive a
    grace period, and enabled deletion is bounded per invocation.
    """

    if retention_days < 1:
        raise ValueError(
            "retention_days must be at least one"
        )
    if delete_limit < 1:
        raise ValueError(
            "delete_limit must be at least one"
        )

    cutoff = as_of - dt.timedelta(
        days=retention_days
    )
    filters = _candidate_filters(cutoff)

    candidate_query = session.query(
        MyDashboardRecord
    ).filter(*filters)
    candidate_count = candidate_query.count()

    if session.get_bind().dialect.name == "postgresql":
        payload_size = None
        for column in _JSON_PAYLOAD_COLUMNS:
            column_size = func.coalesce(
                func.pg_column_size(column),
                0,
            )
            payload_size = (
                column_size
                if payload_size is None
                else payload_size + column_size
            )

        candidate_payload_bytes = int(
            session.query(
                func.coalesce(
                    func.sum(payload_size),
                    0,
                )
            )
            .filter(*filters)
            .scalar()
            or 0
        )
    else:
        candidate_payload_bytes = sum(
            _serialized_payload_bytes(values)
            for values in candidate_query.with_entities(
                *_JSON_PAYLOAD_COLUMNS
            ).all()
        )

    deleted_count = 0
    if delete_enabled and candidate_count:
        candidate_ids = [
            row_id
            for (row_id,) in (
                candidate_query.with_entities(
                    MyDashboardRecord.id
                )
                .order_by(
                    MyDashboardRecord.refreshed_at.asc(),
                    MyDashboardRecord.id.asc(),
                )
                .limit(delete_limit)
                .all()
            )
        ]

        if candidate_ids:
            try:
                deleted_count = (
                    session.query(MyDashboardRecord)
                    .filter(
                        MyDashboardRecord.id.in_(
                            candidate_ids
                        ),
                        *_candidate_filters(cutoff),
                    )
                    .delete(
                        synchronize_session=False
                    )
                )
                session.commit()
            except Exception:
                session.rollback()
                raise

    return MyDashboardDatasetRetentionReport(
        retention_days=retention_days,
        as_of=as_of,
        cutoff=cutoff,
        delete_enabled=delete_enabled,
        delete_limit=delete_limit,
        candidate_count=candidate_count,
        candidate_payload_bytes=(
            candidate_payload_bytes
        ),
        deleted_count=deleted_count,
        remaining_candidate_count=max(
            0,
            candidate_count - deleted_count,
        ),
    )

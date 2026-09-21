"""Bound retention for large shared projection artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import SharedReportArtifact


RETENTION_CONTRACT_VERSION = (
    "shared_report_artifact_retention_v1"
)
MODEL_PROJECTION_ARTIFACT_TYPE = (
    "model_projection_date"
)
DEFAULT_RETENTION_DAYS = 14


@dataclass(frozen=True)
class SharedReportArtifactRetentionReport:
    """Result of evaluating or applying artifact retention."""

    artifact_type: str
    retention_days: int
    as_of_date: date
    cutoff_date: date
    delete_enabled: bool
    candidate_count: int
    candidate_payload_bytes: int
    deleted_count: int

    @property
    def dry_run(self) -> bool:
        return not self.delete_enabled

    def to_diagnostics(self) -> dict[str, Any]:
        return {
            "contract_version": RETENTION_CONTRACT_VERSION,
            "artifact_type": self.artifact_type,
            "retention_days": self.retention_days,
            "as_of_date": self.as_of_date.isoformat(),
            "cutoff_date": self.cutoff_date.isoformat(),
            "delete_enabled": self.delete_enabled,
            "dry_run": self.dry_run,
            "candidate_count": self.candidate_count,
            "candidate_payload_bytes": (
                self.candidate_payload_bytes
            ),
            "deleted_count": self.deleted_count,
        }


def _serialized_payload_bytes(payload: Any) -> int:
    return len(
        json.dumps(
            payload,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def apply_shared_report_artifact_retention(
    session: Session,
    *,
    as_of_date: date,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    delete_enabled: bool = False,
) -> SharedReportArtifactRetentionReport:
    """Evaluate or delete expired projection artifacts.

    Artifacts whose target date is strictly earlier than the
    cutoff are candidates. The cutoff date itself, all newer
    artifacts, and all other artifact types are preserved.
    """

    if retention_days < 1:
        raise ValueError(
            "retention_days must be at least one"
        )

    cutoff_date = as_of_date - timedelta(
        days=retention_days
    )

    filters = (
        SharedReportArtifact.artifact_type
        == MODEL_PROJECTION_ARTIFACT_TYPE,
        SharedReportArtifact.target_date < cutoff_date,
    )

    candidate_query = session.query(
        SharedReportArtifact
    ).filter(*filters)

    candidate_count = candidate_query.count()

    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        candidate_payload_bytes = int(
            session.query(
                func.coalesce(
                    func.sum(
                        func.pg_column_size(
                            SharedReportArtifact.payload_json
                        )
                    ),
                    0,
                )
            )
            .filter(*filters)
            .scalar()
            or 0
        )
    else:
        candidate_payload_bytes = sum(
            _serialized_payload_bytes(payload)
            for (payload,) in candidate_query.with_entities(
                SharedReportArtifact.payload_json
            ).all()
        )

    deleted_count = 0
    if delete_enabled and candidate_count:
        try:
            deleted_count = candidate_query.delete(
                synchronize_session=False
            )
            session.commit()
        except Exception:
            session.rollback()
            raise

    return SharedReportArtifactRetentionReport(
        artifact_type=MODEL_PROJECTION_ARTIFACT_TYPE,
        retention_days=retention_days,
        as_of_date=as_of_date,
        cutoff_date=cutoff_date,
        delete_enabled=delete_enabled,
        candidate_count=candidate_count,
        candidate_payload_bytes=(
            candidate_payload_bytes
        ),
        deleted_count=deleted_count,
    )

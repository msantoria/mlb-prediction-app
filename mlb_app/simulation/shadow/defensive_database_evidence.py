"""Execute defensive-distribution evidence from stored Statcast rows."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ...database import StatcastEvent
from ..game.defensive_event_authority import (
    CanonicalDefensiveEventAuthoritySummary,
)
from .defensive_distribution_evidence import (
    CanonicalDefensiveDistributionEvidence,
    execute_canonical_defensive_distribution_evidence,
)


CANONICAL_DEFENSIVE_DATABASE_EVIDENCE_VERSION = (
    "canonical_defensive_database_evidence_v1"
)

_DATABASE_EVIDENCE_STATUSES = frozenset(
    {
        "ready",
        "unavailable",
        "error",
    }
)


def _date(value: object, field_name: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value

    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be an ISO date"
        ) from exc


def _query_digest(
    *,
    window_start: dt.date,
    window_end: dt.date,
    through_date: dt.date,
    rows: tuple[object, ...],
) -> str:
    payload = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "through_date": through_date.isoformat(),
        "rows": [
            {
                "game_date": row.game_date.isoformat(),
                "game_pk": row.game_pk,
                "at_bat_number": row.at_bat_number,
                "events": row.events,
            }
            for row in rows
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_digest(value: str) -> None:
    if len(value) != 64:
        raise ValueError(
            "query_digest must be a SHA-256 hex digest"
        )

    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            "query_digest must be a SHA-256 hex digest"
        ) from exc


@dataclass(frozen=True)
class CanonicalDefensiveDatabaseEvidence:
    """Auditable result from one bounded read-only database query."""

    status: str
    window_start: str
    window_end: str
    through_date: str
    query_row_count: int
    query_digest: str
    evidence: CanonicalDefensiveDistributionEvidence | None = None
    blocker: str | None = None
    error: str | None = None
    schema_version: str = (
        CANONICAL_DEFENSIVE_DATABASE_EVIDENCE_VERSION
    )

    def __post_init__(self) -> None:
        if self.status not in _DATABASE_EVIDENCE_STATUSES:
            raise ValueError(
                "unsupported defensive database evidence status"
            )
        if self.schema_version != (
            CANONICAL_DEFENSIVE_DATABASE_EVIDENCE_VERSION
        ):
            raise ValueError(
                "unsupported defensive database evidence version"
            )
        if self.query_row_count < 0:
            raise ValueError(
                "query_row_count cannot be negative"
            )

        _validate_digest(self.query_digest)

        if self.status == "ready":
            if self.query_row_count == 0:
                raise ValueError(
                    "ready database evidence requires query rows"
                )
            if self.evidence is None or not self.evidence.ready:
                raise ValueError(
                    "ready database evidence requires "
                    "ready evidence"
                )
            if self.blocker is not None:
                raise ValueError(
                    "ready database evidence cannot have "
                    "a blocker"
                )
            if self.error is not None:
                raise ValueError(
                    "ready database evidence cannot have "
                    "an error"
                )
            return

        if self.status == "unavailable":
            if not self.blocker:
                raise ValueError(
                    "unavailable database evidence requires "
                    "a blocker"
                )
            if self.error is not None:
                raise ValueError(
                    "unavailable database evidence cannot "
                    "have an error"
                )
            if (
                self.evidence is not None
                and self.evidence.status != "unavailable"
            ):
                raise ValueError(
                    "unavailable database evidence requires "
                    "unavailable nested evidence"
                )
            return

        if not self.error:
            raise ValueError(
                "error database evidence requires an error"
            )
        if self.blocker is not None:
            raise ValueError(
                "error database evidence cannot have a blocker"
            )
        if (
            self.evidence is not None
            and self.evidence.status != "error"
        ):
            raise ValueError(
                "error database evidence requires error "
                "nested evidence"
            )

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "through_date": self.through_date,
            "query_row_count": self.query_row_count,
            "query_digest": self.query_digest,
            "queried_columns": [
                "game_date",
                "game_pk",
                "at_bat_number",
                "events",
            ],
            "evidence": (
                None
                if self.evidence is None
                else self.evidence.to_diagnostics()
            ),
            "blocker": self.blocker,
            "error": self.error,
            "measurement_only": True,
            "database_accessed": True,
            "database_query_performed": True,
            "database_query_mode": "read_only",
            "network_accessed": False,
            "external_fetch_performed": False,
            "persistence_performed": False,
            "calibration_parameters_selected": False,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def execute_canonical_defensive_database_evidence(
    session: Session,
    *,
    summary: CanonicalDefensiveEventAuthoritySummary,
    window_start: object,
    window_end: object,
    through_date: object,
) -> CanonicalDefensiveDatabaseEvidence:
    """Execute evidence using one bounded terminal-event query."""

    normalized_start = str(window_start)[:10]
    normalized_end = str(window_end)[:10]
    normalized_through = str(through_date)[:10]
    rows: tuple[object, ...] = ()

    try:
        if not isinstance(session, Session):
            raise TypeError(
                "session must be a SQLAlchemy Session"
            )
        if not isinstance(
            summary,
            CanonicalDefensiveEventAuthoritySummary,
        ):
            raise TypeError(
                "summary must be a "
                "CanonicalDefensiveEventAuthoritySummary"
            )

        start = _date(window_start, "window_start")
        end = _date(window_end, "window_end")
        through = _date(through_date, "through_date")

        if end < start:
            raise ValueError(
                "window_end must not precede window_start"
            )
        if end > through:
            raise ValueError(
                "window_end must not exceed through_date"
            )

        rows = tuple(
            session.query(
                StatcastEvent.game_date.label("game_date"),
                StatcastEvent.game_pk.label("game_pk"),
                StatcastEvent.at_bat_number.label(
                    "at_bat_number"
                ),
                StatcastEvent.events.label("events"),
            )
            .filter(
                StatcastEvent.game_date >= start,
                StatcastEvent.game_date <= end,
                StatcastEvent.events.isnot(None),
            )
            .order_by(
                StatcastEvent.game_date.asc(),
                StatcastEvent.game_pk.asc(),
                StatcastEvent.at_bat_number.asc(),
                StatcastEvent.pitch_number.asc(),
                StatcastEvent.id.asc(),
            )
            .all()
        )
        query_digest = _query_digest(
            window_start=start,
            window_end=end,
            through_date=through,
            rows=rows,
        )

        if not rows:
            return CanonicalDefensiveDatabaseEvidence(
                status="unavailable",
                window_start=start.isoformat(),
                window_end=end.isoformat(),
                through_date=through.isoformat(),
                query_row_count=0,
                query_digest=query_digest,
                blocker="database_window_empty",
            )

        evidence = (
            execute_canonical_defensive_distribution_evidence(
                rows,
                summary=summary,
                window_start=start,
                window_end=end,
                through_date=through,
            )
        )

        if evidence.status == "error":
            return CanonicalDefensiveDatabaseEvidence(
                status="error",
                window_start=start.isoformat(),
                window_end=end.isoformat(),
                through_date=through.isoformat(),
                query_row_count=len(rows),
                query_digest=query_digest,
                evidence=evidence,
                error=evidence.error,
            )

        if evidence.status == "unavailable":
            return CanonicalDefensiveDatabaseEvidence(
                status="unavailable",
                window_start=start.isoformat(),
                window_end=end.isoformat(),
                through_date=through.isoformat(),
                query_row_count=len(rows),
                query_digest=query_digest,
                evidence=evidence,
                blocker=evidence.blocker,
            )

        return CanonicalDefensiveDatabaseEvidence(
            status="ready",
            window_start=start.isoformat(),
            window_end=end.isoformat(),
            through_date=through.isoformat(),
            query_row_count=len(rows),
            query_digest=query_digest,
            evidence=evidence,
        )
    except (
        KeyError,
        SQLAlchemyError,
        TypeError,
        ValueError,
    ) as exc:
        query_digest = hashlib.sha256(
            json.dumps(
                {
                    "window_start": normalized_start,
                    "window_end": normalized_end,
                    "through_date": normalized_through,
                    "query_row_count": len(rows),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        return CanonicalDefensiveDatabaseEvidence(
            status="error",
            window_start=normalized_start,
            window_end=normalized_end,
            through_date=normalized_through,
            query_row_count=len(rows),
            query_digest=query_digest,
            error=f"{type(exc).__name__}: {exc}",
        )

"""Execute production-versus-observed run-environment evidence."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
from typing import Mapping, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .observed_run_environment_source import (
    CanonicalObservedRunEnvironment,
    source_canonical_observed_run_environment,
)
from .production_execution import (
    CanonicalProductionShadowExecution,
)
from .production_run_environment import (
    CanonicalProductionRunEnvironment,
    measure_canonical_production_run_environment,
)
from .production_run_environment_backtest import (
    CanonicalProductionRunEnvironmentBacktest,
    backtest_canonical_production_run_environment,
)


CANONICAL_PRODUCTION_RUN_ENVIRONMENT_EVIDENCE_VERSION = (
    "canonical_production_run_environment_evidence_v1"
)

_EVIDENCE_STATUSES = frozenset(
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


def _validate_digest(value: str) -> None:
    if len(value) != 64:
        raise ValueError(
            "artifact_digest must be a SHA-256 hex digest"
        )
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            "artifact_digest must be a SHA-256 hex digest"
        ) from exc


def _artifact_digest(
    *,
    status: str,
    window_start: str,
    window_end: str,
    through_date: str,
    database_query_performed: bool,
    production: Optional[CanonicalProductionRunEnvironment],
    observed: Optional[CanonicalObservedRunEnvironment],
    backtest: Optional[
        CanonicalProductionRunEnvironmentBacktest
    ],
    blocker: Optional[str],
) -> str:
    payload = {
        "schema_version": (
            CANONICAL_PRODUCTION_RUN_ENVIRONMENT_EVIDENCE_VERSION
        ),
        "status": status,
        "window_start": window_start,
        "window_end": window_end,
        "through_date": through_date,
        "database_query_performed": database_query_performed,
        "production": (
            None
            if production is None
            else production.to_diagnostics()
        ),
        "observed": (
            None
            if observed is None
            else observed.to_diagnostics()
        ),
        "backtest": (
            None
            if backtest is None
            else backtest.to_diagnostics()
        ),
        "blocker": blocker,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CanonicalProductionRunEnvironmentEvidence:
    """One composed production-versus-observed evidence result."""

    status: str
    window_start: str
    window_end: str
    through_date: str
    database_query_performed: bool
    production: Optional[
        CanonicalProductionRunEnvironment
    ] = None
    observed: Optional[
        CanonicalObservedRunEnvironment
    ] = None
    backtest: Optional[
        CanonicalProductionRunEnvironmentBacktest
    ] = None
    artifact_digest: str = ""
    blocker: Optional[str] = None
    error: Optional[str] = None
    schema_version: str = (
        CANONICAL_PRODUCTION_RUN_ENVIRONMENT_EVIDENCE_VERSION
    )

    def __post_init__(self) -> None:
        if self.status not in _EVIDENCE_STATUSES:
            raise ValueError(
                "unsupported production run-environment "
                "evidence status"
            )
        if self.schema_version != (
            CANONICAL_PRODUCTION_RUN_ENVIRONMENT_EVIDENCE_VERSION
        ):
            raise ValueError(
                "unsupported production run-environment "
                "evidence version"
            )
        if self.status != "error":
            start = dt.date.fromisoformat(self.window_start)
            end = dt.date.fromisoformat(self.window_end)
            through = dt.date.fromisoformat(self.through_date)
            if end < start:
                raise ValueError(
                    "window_end must not precede window_start"
                )
            if end > through:
                raise ValueError(
                    "window_end must not exceed through_date"
                )

        if self.status == "ready":
            if (
                self.production is None
                or self.observed is None
                or self.backtest is None
            ):
                raise ValueError(
                    "ready evidence requires production, "
                    "observed, and backtest artifacts"
                )
            if not self.backtest.ready:
                raise ValueError(
                    "ready evidence requires ready backtest"
                )
            if not self.database_query_performed:
                raise ValueError(
                    "ready evidence requires database query"
                )
            if self.blocker is not None or self.error is not None:
                raise ValueError(
                    "ready evidence cannot have blocker or error"
                )
            _validate_digest(self.artifact_digest)
            return

        if self.status == "unavailable":
            if not self.blocker:
                raise ValueError(
                    "unavailable evidence requires a blocker"
                )
            if self.error is not None:
                raise ValueError(
                    "unavailable evidence cannot have an error"
                )
            if self.backtest is not None:
                raise ValueError(
                    "unavailable evidence cannot have a backtest"
                )
            if self.observed is not None:
                raise ValueError(
                    "unavailable evidence cannot have observed artifact"
                )
            _validate_digest(self.artifact_digest)
            return

        if (
            self.production is not None
            or self.observed is not None
            or self.backtest is not None
        ):
            raise ValueError(
                "error evidence cannot expose partial results"
            )
        if self.artifact_digest:
            raise ValueError(
                "error evidence cannot have artifact_digest"
            )
        if self.blocker is not None:
            raise ValueError(
                "error evidence cannot have a blocker"
            )
        if not self.error:
            raise ValueError(
                "error evidence requires an error message"
            )

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_diagnostics(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "through_date": self.through_date,
            "database_accessed": self.database_query_performed,
            "database_query_performed": (
                self.database_query_performed
            ),
            "database_query_mode": (
                "read_only"
                if self.database_query_performed
                else None
            ),
            "production": (
                None
                if self.production is None
                else self.production.to_diagnostics()
            ),
            "observed": (
                None
                if self.observed is None
                else self.observed.to_diagnostics()
            ),
            "backtest": (
                None
                if self.backtest is None
                else self.backtest.to_diagnostics()
            ),
            "artifact_digest": self.artifact_digest,
            "blocker": self.blocker,
            "error": self.error,
            "production_execution_consumed": (
                self.production is not None
            ),
            "independent_trial_execution": False,
            "network_accessed": False,
            "external_fetch_performed": False,
            "persistence_performed": False,
            "measurement_only": True,
            "causal_claim_permitted": False,
            "calibration_parameters_selected": False,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def execute_canonical_production_run_environment_evidence(
    session: Session,
    *,
    execution: CanonicalProductionShadowExecution,
    window_start: object,
    window_end: object,
    through_date: object,
) -> CanonicalProductionRunEnvironmentEvidence:
    """Compose production, observed, and backtest evidence."""

    window_start_text = str(window_start)[:10]
    window_end_text = str(window_end)[:10]
    through_date_text = str(through_date)[:10]
    database_query_performed = False

    try:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        if not isinstance(
            execution,
            CanonicalProductionShadowExecution,
        ):
            raise TypeError(
                "execution must be a "
                "CanonicalProductionShadowExecution"
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

        window_start_text = start.isoformat()
        window_end_text = end.isoformat()
        through_date_text = through.isoformat()

        if not execution.executed:
            blocker = "production_execution_unavailable"
            artifact_digest = _artifact_digest(
                status="unavailable",
                window_start=window_start_text,
                window_end=window_end_text,
                through_date=through_date_text,
                database_query_performed=False,
                production=None,
                observed=None,
                backtest=None,
                blocker=blocker,
            )
            return CanonicalProductionRunEnvironmentEvidence(
                status="unavailable",
                window_start=window_start_text,
                window_end=window_end_text,
                through_date=through_date_text,
                database_query_performed=False,
                artifact_digest=artifact_digest,
                blocker=blocker,
            )

        production = (
            measure_canonical_production_run_environment(
                execution
            )
        )

        database_query_performed = True
        try:
            observed = source_canonical_observed_run_environment(
                session,
                window_start=start,
                window_end=end,
                through_date=through,
            )
        except ValueError as exc:
            message = str(exc)
            blockers = {
                "no final game snapshots in requested window": (
                    "database_window_empty"
                ),
                (
                    "no complete final game snapshots "
                    "in requested window"
                ): "observed_window_incomplete",
            }
            blocker = blockers.get(message)
            if blocker is None:
                raise
            artifact_digest = _artifact_digest(
                status="unavailable",
                window_start=window_start_text,
                window_end=window_end_text,
                through_date=through_date_text,
                database_query_performed=True,
                production=production,
                observed=None,
                backtest=None,
                blocker=blocker,
            )
            return CanonicalProductionRunEnvironmentEvidence(
                status="unavailable",
                window_start=window_start_text,
                window_end=window_end_text,
                through_date=through_date_text,
                database_query_performed=True,
                production=production,
                artifact_digest=artifact_digest,
                blocker=blocker,
            )

        backtest = backtest_canonical_production_run_environment(
            production,
            observed,
        )
        artifact_digest = _artifact_digest(
            status="ready",
            window_start=window_start_text,
            window_end=window_end_text,
            through_date=through_date_text,
            database_query_performed=True,
            production=production,
            observed=observed,
            backtest=backtest,
            blocker=None,
        )
        return CanonicalProductionRunEnvironmentEvidence(
            status="ready",
            window_start=window_start_text,
            window_end=window_end_text,
            through_date=through_date_text,
            database_query_performed=True,
            production=production,
            observed=observed,
            backtest=backtest,
            artifact_digest=artifact_digest,
        )
    except (
        TypeError,
        ValueError,
        KeyError,
        SQLAlchemyError,
    ) as exc:
        return CanonicalProductionRunEnvironmentEvidence(
            status="error",
            window_start=window_start_text,
            window_end=window_end_text,
            through_date=through_date_text,
            database_query_performed=(
                database_query_performed
            ),
            error=f"{type(exc).__name__}: {exc}",
        )

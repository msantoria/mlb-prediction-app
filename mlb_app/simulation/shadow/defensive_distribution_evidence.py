"""Execute canonical defensive-distribution evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

from ..game.defensive_event_authority import (
    CanonicalDefensiveEventAuthoritySummary,
)
from .defensive_distribution_backtest import (
    CanonicalDefensiveDistributionBacktest,
    backtest_canonical_defensive_distribution,
)
from .statcast_defensive_distribution_source import (
    CanonicalStatcastDefensiveDistributionSource,
    source_statcast_defensive_distribution,
)


CANONICAL_DEFENSIVE_DISTRIBUTION_EVIDENCE_VERSION = (
    "canonical_defensive_distribution_evidence_v1"
)

_EVIDENCE_STATUSES = frozenset(
    {
        "ready",
        "unavailable",
        "error",
    }
)


def _sha256_diagnostics(
    *,
    source: CanonicalStatcastDefensiveDistributionSource,
    backtest: CanonicalDefensiveDistributionBacktest,
) -> str:
    payload = {
        "source": source.to_diagnostics(),
        "backtest": backtest.to_diagnostics(),
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
            "artifact_digest must be a SHA-256 hex digest"
        )

    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            "artifact_digest must be a SHA-256 hex digest"
        ) from exc


@dataclass(frozen=True)
class CanonicalDefensiveDistributionEvidence:
    """Deterministic measurement-only defensive evidence."""

    status: str
    window_start: str
    window_end: str
    through_date: str
    source: (
        CanonicalStatcastDefensiveDistributionSource
        | None
    ) = None
    backtest: (
        CanonicalDefensiveDistributionBacktest
        | None
    ) = None
    artifact_digest: str = ""
    blocker: str | None = None
    error: str | None = None
    schema_version: str = (
        CANONICAL_DEFENSIVE_DISTRIBUTION_EVIDENCE_VERSION
    )

    def __post_init__(self) -> None:
        if self.status not in _EVIDENCE_STATUSES:
            raise ValueError(
                "unsupported defensive distribution "
                "evidence status"
            )
        if self.schema_version != (
            CANONICAL_DEFENSIVE_DISTRIBUTION_EVIDENCE_VERSION
        ):
            raise ValueError(
                "unsupported defensive distribution "
                "evidence version"
            )

        if self.status == "ready":
            if self.source is None or self.backtest is None:
                raise ValueError(
                    "ready evidence requires source and backtest"
                )
            if not self.backtest.ready:
                raise ValueError(
                    "ready evidence requires ready backtest"
                )
            if self.blocker is not None:
                raise ValueError(
                    "ready evidence cannot have a blocker"
                )
            if self.error is not None:
                raise ValueError(
                    "ready evidence cannot have an error"
                )
            _validate_digest(self.artifact_digest)
            return

        if self.status == "unavailable":
            if self.source is None or self.backtest is None:
                raise ValueError(
                    "unavailable evidence requires "
                    "source and backtest"
                )
            if self.backtest.ready:
                raise ValueError(
                    "unavailable evidence cannot have "
                    "a ready backtest"
                )
            if not self.blocker:
                raise ValueError(
                    "unavailable evidence requires a blocker"
                )
            if self.error is not None:
                raise ValueError(
                    "unavailable evidence cannot have an error"
                )
            _validate_digest(self.artifact_digest)
            return

        if self.source is not None or self.backtest is not None:
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

    def to_diagnostics(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "ready": self.ready,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "through_date": self.through_date,
            "source": (
                None
                if self.source is None
                else self.source.to_diagnostics()
            ),
            "backtest": (
                None
                if self.backtest is None
                else self.backtest.to_diagnostics()
            ),
            "artifact_digest": self.artifact_digest,
            "blocker": self.blocker,
            "error": self.error,
            "measurement_only": True,
            "database_accessed": False,
            "network_accessed": False,
            "external_fetch_performed": False,
            "persistence_performed": False,
            "calibration_parameters_selected": False,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def execute_canonical_defensive_distribution_evidence(
    rows: Iterable[Any],
    *,
    summary: CanonicalDefensiveEventAuthoritySummary,
    window_start: object,
    window_end: object,
    through_date: object,
) -> CanonicalDefensiveDistributionEvidence:
    """Source and compare one caller-owned evidence window."""

    normalized_window_start = str(window_start)[:10]
    normalized_window_end = str(window_end)[:10]
    normalized_through_date = str(through_date)[:10]

    try:
        if not isinstance(
            summary,
            CanonicalDefensiveEventAuthoritySummary,
        ):
            raise TypeError(
                "summary must be a "
                "CanonicalDefensiveEventAuthoritySummary"
            )

        source = source_statcast_defensive_distribution(
            rows,
            window_start=window_start,
            window_end=window_end,
            through_date=through_date,
        )
        backtest = backtest_canonical_defensive_distribution(
            summary=summary,
            observed=source.observed,
        )
        artifact_digest = _sha256_diagnostics(
            source=source,
            backtest=backtest,
        )

        if not backtest.ready:
            return CanonicalDefensiveDistributionEvidence(
                status="unavailable",
                window_start=source.window_start,
                window_end=source.window_end,
                through_date=source.through_date,
                source=source,
                backtest=backtest,
                artifact_digest=artifact_digest,
                blocker=backtest.blocker,
            )

        return CanonicalDefensiveDistributionEvidence(
            status="ready",
            window_start=source.window_start,
            window_end=source.window_end,
            through_date=source.through_date,
            source=source,
            backtest=backtest,
            artifact_digest=artifact_digest,
        )
    except (TypeError, ValueError, KeyError) as exc:
        return CanonicalDefensiveDistributionEvidence(
            status="error",
            window_start=normalized_window_start,
            window_end=normalized_window_end,
            through_date=normalized_through_date,
            error=f"{type(exc).__name__}: {exc}",
        )

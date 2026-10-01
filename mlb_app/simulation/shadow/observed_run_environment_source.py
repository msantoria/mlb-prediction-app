"""Source an observed MLB run environment from final snapshots."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from typing import Mapping, Optional, Tuple

from sqlalchemy.orm import Session

from mlb_app.final_game_snapshots import FinalGameSnapshot
from mlb_app.simulation.projections.aggregator import (
    summarize_values,
)
from mlb_app.simulation.projections.contracts import (
    StatisticalSummary,
)


CANONICAL_OBSERVED_RUN_ENVIRONMENT_SOURCE_VERSION = (
    "canonical_observed_run_environment_source_v1"
)

CountPairs = Tuple[Tuple[str, int], ...]
RatePairs = Tuple[Tuple[str, float], ...]


def _validate_rate(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between zero and one")


def _validate_digest(name: str, value: str) -> None:
    if len(value) != 64:
        raise ValueError(f"{name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be a SHA-256 hex digest"
        ) from exc


def _pairs_to_dict(values):
    return {name: value for name, value in values}


@dataclass(frozen=True)
class CanonicalObservedRunEnvironment:
    """One bounded observed completed-game run environment."""

    source_identifier: str
    window_start: str
    window_end: str
    through_date: str
    game_count: int
    away_runs: StatisticalSummary
    home_runs: StatisticalSummary
    total_runs: StatisticalSummary
    box_score_metric_means: RatePairs
    scoring_rates: RatePairs
    total_threshold_rates: RatePairs
    snapshot_version_counts: CountPairs
    query_row_count: int
    excluded_snapshot_count: int
    query_digest: str
    artifact_digest: str
    schema_version: str = (
        CANONICAL_OBSERVED_RUN_ENVIRONMENT_SOURCE_VERSION
    )

    def __post_init__(self) -> None:
        if self.schema_version != (
            CANONICAL_OBSERVED_RUN_ENVIRONMENT_SOURCE_VERSION
        ):
            raise ValueError(
                "unsupported observed run-environment version"
            )
        if not self.source_identifier.strip():
            raise ValueError("source_identifier is required")
        start = date.fromisoformat(self.window_start)
        end = date.fromisoformat(self.window_end)
        through = date.fromisoformat(self.through_date)
        if end < start:
            raise ValueError(
                "window_end must not precede window_start"
            )
        if end > through:
            raise ValueError(
                "window_end must not exceed through_date"
            )
        if self.game_count <= 0:
            raise ValueError("game_count must be positive")
        for name, summary in (
            ("away_runs", self.away_runs),
            ("home_runs", self.home_runs),
            ("total_runs", self.total_runs),
        ):
            if not isinstance(summary, StatisticalSummary):
                raise TypeError(
                    f"{name} must be a StatisticalSummary"
                )
            if summary.count != self.game_count:
                raise ValueError(
                    f"{name} count must match game_count"
                )
        for collection_name, values in (
            ("box_score_metric_means", self.box_score_metric_means),
            ("scoring_rates", self.scoring_rates),
            ("total_threshold_rates", self.total_threshold_rates),
        ):
            names = tuple(name for name, _ in values)
            if len(names) != len(set(names)):
                raise ValueError(
                    f"{collection_name} names must be unique"
                )
            for name, value in values:
                if not name or not math.isfinite(value) or value < 0.0:
                    raise ValueError(
                        f"invalid {collection_name} entry"
                    )
        for name, value in self.scoring_rates:
            _validate_rate(name, value)
        for name, value in self.total_threshold_rates:
            _validate_rate(name, value)
        version_names = tuple(
            name for name, _ in self.snapshot_version_counts
        )
        if len(version_names) != len(set(version_names)):
            raise ValueError(
                "snapshot version names must be unique"
            )
        if any(
            not name or count < 0
            for name, count in self.snapshot_version_counts
        ):
            raise ValueError("invalid snapshot version count")
        if sum(count for _, count in self.snapshot_version_counts) != (
            self.game_count
        ):
            raise ValueError(
                "snapshot version counts must reconcile"
            )
        if self.query_row_count < self.game_count:
            raise ValueError(
                "query_row_count cannot be below game_count"
            )
        if self.excluded_snapshot_count != (
            self.query_row_count - self.game_count
        ):
            raise ValueError(
                "excluded snapshot count must reconcile"
            )
        _validate_digest("query_digest", self.query_digest)
        _validate_digest("artifact_digest", self.artifact_digest)

    def to_diagnostics(self) -> Mapping[str, object]:
        return {
            "schema_version": self.schema_version,
            "status": "ready",
            "ready": True,
            "source_identifier": self.source_identifier,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "through_date": self.through_date,
            "game_count": self.game_count,
            "away_runs": asdict(self.away_runs),
            "home_runs": asdict(self.home_runs),
            "total_runs": asdict(self.total_runs),
            "box_score_metric_means": _pairs_to_dict(
                self.box_score_metric_means
            ),
            "scoring_rates": _pairs_to_dict(self.scoring_rates),
            "total_threshold_rates": _pairs_to_dict(
                self.total_threshold_rates
            ),
            "snapshot_version_counts": _pairs_to_dict(
                self.snapshot_version_counts
            ),
            "query_row_count": self.query_row_count,
            "excluded_snapshot_count": (
                self.excluded_snapshot_count
            ),
            "query_digest": self.query_digest,
            "artifact_digest": self.artifact_digest,
            "score_source": "final_game_snapshots",
            "box_score_source": (
                "final_game_snapshots.payload_json"
            ),
            "database_accessed": True,
            "database_query_mode": "read_only",
            "network_accessed": False,
            "external_fetch_performed": False,
            "persistence_performed": False,
            "measurement_only": True,
            "calibration_parameters_selected": False,
            "activation_permitted": False,
            "production_authority_changed": False,
        }


def _normalize_date(name: str, value: date | str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"{name} must be an ISO date"
            ) from exc
    raise TypeError(f"{name} must be a date or ISO string")


def _safe_nonnegative_int(value: object) -> Optional[int]:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized >= 0 else None


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _mean(total: int, game_count: int) -> float:
    return round(total / game_count, 6)


def _sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _snapshot_query_record(
    snapshot: FinalGameSnapshot,
) -> Mapping[str, object]:
    return {
        "game_pk": snapshot.game_pk,
        "official_date": snapshot.official_date.isoformat(),
        "away_score": snapshot.away_score,
        "home_score": snapshot.home_score,
        "snapshot_version": snapshot.snapshot_version,
        "source": snapshot.source,
        "payload_json": snapshot.payload_json,
    }


def _snapshot_metrics(
    snapshot: FinalGameSnapshot,
) -> Optional[Mapping[str, int]]:
    away_score = _safe_nonnegative_int(snapshot.away_score)
    home_score = _safe_nonnegative_int(snapshot.home_score)
    payload = snapshot.payload_json
    if away_score is None or home_score is None:
        return None
    if not isinstance(payload, Mapping):
        return None

    boxscore = payload.get("boxscore")
    linescore = payload.get("linescore")
    if not isinstance(boxscore, Mapping):
        return None
    if not isinstance(linescore, Mapping):
        return None

    batters = []
    for side in ("away", "home"):
        team = boxscore.get(side)
        if not isinstance(team, Mapping):
            return None
        side_batters = team.get("batters")
        if not isinstance(side_batters, list):
            return None
        batters.extend(
            row for row in side_batters
            if isinstance(row, Mapping)
        )
    if not batters:
        return None

    totals = {
        "runs": away_score + home_score,
        "at_bats": 0,
        "hits": 0,
        "singles": 0,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "walks": 0,
        "hit_by_pitch": 0,
        "strikeouts": 0,
        "stolen_bases": 0,
        "caught_stealing": 0,
        "left_on_base": 0,
        "errors": 0,
    }

    for batter in batters:
        for name in (
            "at_bats",
            "hits",
            "doubles",
            "triples",
            "home_runs",
            "walks",
            "hit_by_pitch",
            "strikeouts",
            "stolen_bases",
            "caught_stealing",
        ):
            value = _safe_nonnegative_int(batter.get(name))
            totals[name] += value or 0

    extra_base_hits = (
        totals["doubles"]
        + totals["triples"]
        + totals["home_runs"]
    )
    if extra_base_hits > totals["hits"]:
        return None
    totals["singles"] = totals["hits"] - extra_base_hits

    line_totals = linescore.get("totals")
    if not isinstance(line_totals, Mapping):
        return None
    for side in ("away", "home"):
        team_totals = line_totals.get(side)
        if not isinstance(team_totals, Mapping):
            return None
        for source_name, target_name in (
            ("left_on_base", "left_on_base"),
            ("errors", "errors"),
        ):
            value = _safe_nonnegative_int(
                team_totals.get(source_name)
            )
            if value is None:
                return None
            totals[target_name] += value

    totals["observed_opportunities"] = (
        totals["at_bats"]
        + totals["walks"]
        + totals["hit_by_pitch"]
    )
    if totals["observed_opportunities"] <= 0:
        return None
    return totals


def source_canonical_observed_run_environment(
    session: Session,
    *,
    window_start: date | str,
    window_end: date | str,
    through_date: date | str,
) -> CanonicalObservedRunEnvironment:
    """Aggregate a bounded, read-only final-game baseline."""

    if not isinstance(session, Session):
        raise TypeError("session must be a Session")

    start = _normalize_date("window_start", window_start)
    end = _normalize_date("window_end", window_end)
    through = _normalize_date("through_date", through_date)
    if end < start:
        raise ValueError(
            "window_end must not precede window_start"
        )
    if end > through:
        raise ValueError(
            "window_end must not exceed through_date"
        )

    rows = (
        session.query(FinalGameSnapshot)
        .filter(
            FinalGameSnapshot.official_date >= start,
            FinalGameSnapshot.official_date <= end,
        )
        .order_by(
            FinalGameSnapshot.official_date.asc(),
            FinalGameSnapshot.game_pk.asc(),
        )
        .all()
    )
    if not rows:
        raise ValueError(
            "no final game snapshots in requested window"
        )

    query_records = [
        _snapshot_query_record(snapshot)
        for snapshot in rows
    ]
    query_digest = _sha256(query_records)

    included = []
    for snapshot in rows:
        metrics = _snapshot_metrics(snapshot)
        if metrics is not None:
            included.append((snapshot, metrics))
    if not included:
        raise ValueError(
            "no complete final game snapshots in requested window"
        )

    game_count = len(included)
    away_values = [
        int(snapshot.away_score)
        for snapshot, _ in included
    ]
    home_values = [
        int(snapshot.home_score)
        for snapshot, _ in included
    ]
    total_values = [
        away + home
        for away, home in zip(away_values, home_values)
    ]

    metric_names = tuple(sorted(included[0][1]))
    totals = {name: 0 for name in metric_names}
    for _, metrics in included:
        if tuple(sorted(metrics)) != metric_names:
            raise ValueError(
                "observed snapshot metric contract changed"
            )
        for name, value in metrics.items():
            totals[name] += value

    known_reaches = (
        totals["hits"]
        + totals["walks"]
        + totals["hit_by_pitch"]
    )
    opportunities = totals["observed_opportunities"]
    extra_base_hits = (
        totals["doubles"]
        + totals["triples"]
        + totals["home_runs"]
    )

    box_score_metric_means = tuple(
        (f"{name}_per_game", _mean(value, game_count))
        for name, value in sorted(totals.items())
    ) + (
        (
            "runs_per_known_reach",
            _ratio(totals["runs"], known_reaches),
        ),
    )

    scoring_rates = (
        (
            "hit_rate_per_observed_opportunity",
            _ratio(totals["hits"], opportunities),
        ),
        (
            "walk_rate_per_observed_opportunity",
            _ratio(totals["walks"], opportunities),
        ),
        (
            "hit_by_pitch_rate_per_observed_opportunity",
            _ratio(totals["hit_by_pitch"], opportunities),
        ),
        (
            "strikeout_rate_per_observed_opportunity",
            _ratio(totals["strikeouts"], opportunities),
        ),
        (
            "home_run_rate_per_observed_opportunity",
            _ratio(totals["home_runs"], opportunities),
        ),
        (
            "known_reach_rate_per_observed_opportunity",
            _ratio(known_reaches, opportunities),
        ),
        (
            "extra_base_hit_share",
            _ratio(extra_base_hits, totals["hits"]),
        ),
        (
            "stolen_base_success_rate",
            _ratio(
                totals["stolen_bases"],
                totals["stolen_bases"]
                + totals["caught_stealing"],
            ),
        ),
    )

    total_threshold_rates = (
        (
            "away_shutout_rate",
            _ratio(
                sum(value == 0 for value in away_values),
                game_count,
            ),
        ),
        (
            "home_shutout_rate",
            _ratio(
                sum(value == 0 for value in home_values),
                game_count,
            ),
        ),
        (
            "total_runs_5_or_fewer_rate",
            _ratio(
                sum(value <= 5 for value in total_values),
                game_count,
            ),
        ),
        (
            "total_runs_6_or_fewer_rate",
            _ratio(
                sum(value <= 6 for value in total_values),
                game_count,
            ),
        ),
        (
            "total_runs_7_or_fewer_rate",
            _ratio(
                sum(value <= 7 for value in total_values),
                game_count,
            ),
        ),
        (
            "total_runs_8_or_fewer_rate",
            _ratio(
                sum(value <= 8 for value in total_values),
                game_count,
            ),
        ),
        (
            "total_runs_9_or_more_rate",
            _ratio(
                sum(value >= 9 for value in total_values),
                game_count,
            ),
        ),
    )

    version_counts = {}
    for snapshot, _ in included:
        key = str(snapshot.snapshot_version)
        version_counts[key] = version_counts.get(key, 0) + 1
    snapshot_version_counts = tuple(
        sorted(version_counts.items())
    )

    digest_payload = {
        "schema_version": (
            CANONICAL_OBSERVED_RUN_ENVIRONMENT_SOURCE_VERSION
        ),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "through_date": through.isoformat(),
        "game_count": game_count,
        "away_runs": asdict(summarize_values(away_values)),
        "home_runs": asdict(summarize_values(home_values)),
        "total_runs": asdict(summarize_values(total_values)),
        "box_score_metric_means": dict(
            box_score_metric_means
        ),
        "scoring_rates": dict(scoring_rates),
        "total_threshold_rates": dict(
            total_threshold_rates
        ),
        "snapshot_version_counts": dict(
            snapshot_version_counts
        ),
        "query_digest": query_digest,
    }
    artifact_digest = _sha256(digest_payload)
    source_identifier = (
        "final_game_snapshots:"
        f"{start.isoformat()}:{end.isoformat()}:"
        f"{query_digest}"
    )

    return CanonicalObservedRunEnvironment(
        source_identifier=source_identifier,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        through_date=through.isoformat(),
        game_count=game_count,
        away_runs=summarize_values(away_values),
        home_runs=summarize_values(home_values),
        total_runs=summarize_values(total_values),
        box_score_metric_means=box_score_metric_means,
        scoring_rates=scoring_rates,
        total_threshold_rates=total_threshold_rates,
        snapshot_version_counts=snapshot_version_counts,
        query_row_count=len(rows),
        excluded_snapshot_count=len(rows) - game_count,
        query_digest=query_digest,
        artifact_digest=artifact_digest,
    )

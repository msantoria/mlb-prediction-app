"""Frontend-neutral player-row adaptation for canonical projections."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Tuple


CANONICAL_PLAYER_PROJECTION_ROWS_VERSION = (
    "canonical_player_projection_rows_v1"
)


def canonical_player_projection_rows(
    payload: Mapping[str, Any],
) -> Dict[str, Any]:
    """
    Flatten canonical batter and pitcher projections into display rows.

    This adapter is transport-only. It does not enrich identity, change
    simulation values, or alter canonical/legacy production authority.
    """

    if not isinstance(payload, Mapping):
        raise TypeError(
            "payload must be a mapping"
        )

    simulation_count = _positive_int(
        payload.get("simulation_count"),
        field_name="simulation_count",
    )

    rows = tuple(
        _player_row(
            projection=projection,
            player_type="batter",
            simulation_count=simulation_count,
        )
        for projection in _projection_group(
            payload,
            "batters",
        )
    ) + tuple(
        _player_row(
            projection=projection,
            player_type="pitcher",
            simulation_count=simulation_count,
        )
        for projection in _projection_group(
            payload,
            "pitchers",
        )
    )

    ordered_rows = tuple(
        sorted(
            rows,
            key=lambda row: (
                row["team_side"],
                row["player_type"],
                row["player_id"],
            ),
        )
    )

    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        diagnostics = {}

    return {
        "schema_version": (
            CANONICAL_PLAYER_PROJECTION_ROWS_VERSION
        ),
        "source_schema_version": payload.get(
            "schema_version"
        ),
        "run_id": payload.get("run_id"),
        "model_version": payload.get(
            "model_version"
        ),
        "simulation_count": simulation_count,
        "players": [
            dict(row)
            for row in ordered_rows
        ],
        "diagnostics": {
            "warnings": list(
                diagnostics.get("warnings") or []
            ),
            "pitcher_attribution_complete_rate": (
                diagnostics.get(
                    "pitcher_attribution_complete_rate"
                )
            ),
            "replay_validation_pass_rate": (
                diagnostics.get(
                    "replay_validation_pass_rate"
                )
            ),
        },
        "identity_enrichment_applied": False,
        "authoritative": False,
        "authoritative_source": "legacy",
    }


def _projection_group(
    payload: Mapping[str, Any],
    key: str,
) -> Tuple[Mapping[str, Any], ...]:
    value = payload.get(key)

    if not isinstance(value, (list, tuple)):
        raise TypeError(
            f"{key} must be a list or tuple"
        )

    rows = []

    for projection in value:
        if not isinstance(projection, Mapping):
            raise TypeError(
                f"{key} entries must be mappings"
            )
        rows.append(projection)

    return tuple(rows)


def _player_row(
    *,
    projection: Mapping[str, Any],
    player_type: str,
    simulation_count: int,
) -> Dict[str, Any]:
    player_id = str(
        projection.get("player_id") or ""
    ).strip()
    team_side = str(
        projection.get("team_side") or ""
    ).strip()

    if not player_id:
        raise ValueError(
            "player_id is required"
        )

    if team_side not in {"away", "home"}:
        raise ValueError(
            "team_side must be 'away' or 'home'"
        )

    metrics = _metric_map(
        projection.get("metrics"),
        simulation_count=simulation_count,
    )

    dfs = metrics.get("dfs_points")

    return {
        "player_id": player_id,
        "player_type": player_type,
        "team_side": team_side,
        "projected_dfs_points": (
            dfs["mean"]
            if dfs is not None
            else None
        ),
        "dfs_floor": (
            dfs["p10"]
            if dfs is not None
            else None
        ),
        "dfs_median": (
            dfs["median"]
            if dfs is not None
            else None
        ),
        "dfs_ceiling": (
            dfs["p90"]
            if dfs is not None
            else None
        ),
        "metrics": metrics,
        "simulation_count": simulation_count,
    }


def _metric_map(
    value: Any,
    *,
    simulation_count: int,
) -> Dict[str, Dict[str, float]]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(
            "metrics must be a list or tuple"
        )

    result: Dict[str, Dict[str, float]] = {}

    for metric in value:
        if not isinstance(metric, Mapping):
            raise TypeError(
                "metric entries must be mappings"
            )

        name = str(
            metric.get("name") or ""
        ).strip()

        if not name:
            raise ValueError(
                "metric name is required"
            )

        if name in result:
            raise ValueError(
                "metric names must be unique per player"
            )

        summary = metric.get("summary")

        if not isinstance(summary, Mapping):
            raise TypeError(
                "metric summary must be a mapping"
            )

        count = _positive_int(
            summary.get("count"),
            field_name=f"{name}.count",
        )

        if count != simulation_count:
            raise ValueError(
                "metric count must match simulation_count"
            )

        result[name] = {
            key: float(summary[key])
            for key in (
                "mean",
                "median",
                "p10",
                "p25",
                "p75",
                "p90",
                "minimum",
                "maximum",
            )
        }

        # Older artifacts remain valid; never infer tails from a mean.
        for key in ("sd", "p0", "p1_plus", "p2_plus", "p3_plus", "p4_plus", "p5_plus", "p6_plus"):
            if summary.get(key) is not None:
                result[name][key] = float(summary[key])

    return {
        key: result[key]
        for key in sorted(result)
    }


def _positive_int(
    value: Any,
    *,
    field_name: str,
) -> int:
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} must be an integer"
        )

    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"{field_name} must be an integer"
        ) from exc

    if normalized <= 0:
        raise ValueError(
            f"{field_name} must be positive"
        )

    return normalized

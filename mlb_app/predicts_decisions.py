"""Two-stage daily decision board built from frozen MLBGPT evidence.

The canonical Model Projections mean remains the numerical baseline.  This
module ranks the slate using the same independent evidence surfaces analysts
use after export, without pretending an unvalidated heuristic is a new count
forecast.  A learned residual may replace the baseline only after its existing
temporal holdout gate passes.
"""
from collections import defaultdict
import math
import statistics


BATTER_WEIGHTS = {
    "baseline": .45, "opportunity": .15, "process": .10,
    "trend": .15, "arsenal": .10, "location": .05,
}
PITCHER_WEIGHTS = {
    "baseline": .55, "opportunity": .20, "process": .10,
    "trend": .10, "workload": .05,
}


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _confirmed(row):
    status = str(row.get("lineup_status") or "").lower()
    if "confirm" not in status:
        return False
    if row.get("player_type") == "pitcher":
        return True
    order = row.get("batting_order")
    return isinstance(order, int) and 1 <= order <= 9


def _z(value, values):
    value = _number(value)
    sample = [v for raw in values if (v := _number(raw)) is not None]
    if value is None or len(sample) < 2:
        return None
    spread = statistics.pstdev(sample)
    return 0.0 if spread < 1e-9 else (value - statistics.mean(sample)) / spread


def _feature_value(row, name, metric):
    if name == "baseline":
        return row.get("baseline", {}).get(metric)
    return row.get("features", {}).get(name, {}).get("value")


def enrich(rows, *, force=False):
    """Attach display authority, convergence ranking and decision category."""
    populations = defaultdict(list)
    metrics = {"batter": ("hits", "total_bases", "home_runs"), "pitcher": ("strikeouts",)}
    for row in rows:
        if row.get("decision_board") and not force:
            continue
        role = row.get("player_type")
        weights = BATTER_WEIGHTS if role == "batter" else PITCHER_WEIGHTS
        for metric in metrics.get(role, ()):
            for signal in weights:
                populations[(role, metric, signal)].append(_feature_value(row, signal, metric))

    for row in rows:
        if row.get("decision_board") and not force:
            continue
        role = row.get("player_type")
        confirmed = _confirmed(row)
        row["prediction_stage"] = "confirmed_lineup" if confirmed else "model_projection_baseline"
        row["prediction_stage_label"] = "Confirmed Lineup Prediction" if confirmed else "Model Projection Baseline"
        weights = BATTER_WEIGHTS if role == "batter" else PITCHER_WEIGHTS
        row["decision_board"] = {}
        for metric in metrics.get(role, ()):
            prediction = row.get("predictions", {}).get(metric) or {}
            baseline = _number(row.get("baseline", {}).get(metric))
            adjusted = _number(prediction.get("adjusted")) if prediction.get("status") == "ready" else None
            contributions = []
            weighted_sum = weight_used = 0.0
            for signal, weight in weights.items():
                raw = _feature_value(row, signal, metric)
                score = _z(raw, populations[(role, metric, signal)])
                if score is None:
                    continue
                contribution = weight * score
                weighted_sum += contribution
                weight_used += weight
                contributions.append({"driver": signal, "raw": _number(raw), "z_score": score,
                                      "weight": weight, "contribution": contribution})
            normalized = weighted_sum / weight_used if weight_used else 0.0
            convergence = max(1.0, min(99.0, 50.0 + 15.0 * normalized))
            supporting = sum(item["z_score"] >= .25 for item in contributions if item["driver"] != "baseline")
            opposing = sum(item["z_score"] <= -.25 for item in contributions if item["driver"] != "baseline")
            category = "model_projection_baseline"
            if confirmed:
                category = "confirmed_lineup_shortlist" if convergence >= 60 and supporting >= 2 else "confirmed_lineup_pool"
            row["decision_board"][metric] = {
                "category": category,
                "convergence_score": round(convergence, 2),
                "supporting_signals": supporting,
                "opposing_signals": opposing,
                "drivers": sorted(contributions, key=lambda item: abs(item["contribution"]), reverse=True),
                "mlbgpt_line": adjusted if adjusted is not None else baseline,
                "line_authority": "validated_residual_model" if adjusted is not None else "model_projections_baseline",
                "unique_prediction": adjusted is not None and baseline is not None and abs(adjusted - baseline) >= .05,
                "book_markets": [],
            }
    return rows


def attach_markets(rows, market_rows):
    """Attach captured book context; market prices never enter model scoring."""
    by_id, by_name = defaultdict(list), defaultdict(list)
    for market in market_rows:
        if market.player_id:
            by_id[market.player_id].append(market)
        if market.player_name:
            by_name[market.player_name.strip().lower()].append(market)
    terms = {
        "hits": ("hit",), "total_bases": ("total base", "total_base"),
        "home_runs": ("home run", "home_run"), "strikeouts": ("strikeout",),
    }
    for row in rows:
        candidates = by_id.get(row.get("player_id"), []) or by_name.get(str(row.get("player_name") or "").strip().lower(), [])
        for metric, board in row.get("decision_board", {}).items():
            for market in candidates:
                text = " ".join(str(value or "") for value in (market.market_key, market.market_name)).lower()
                if not any(term in text for term in terms[metric]):
                    continue
                line = _number(market.line)
                board["book_markets"].append({
                    "book": market.book or market.provider, "market": market.market_name,
                    "selection": market.selection_label, "line": line, "price": _number(market.price),
                    "implied_probability": _number(market.implied_probability),
                    "captured_at": market.captured_at.isoformat() + "Z",
                    "line_gap": None if line is None or board["mlbgpt_line"] is None else round(board["mlbgpt_line"] - line, 3),
                })
    return rows

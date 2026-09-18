"""Versioned ridge residual correction with a strictly earlier temporal holdout.

No outcome, current result, or sportsbook field enters the feature matrix.
Models remain unavailable until both fit and holdout populations are adequate.
"""
import hashlib
import json
import numpy as np
from .predicts_probability import empirical, wilson
from .predicts_validation import MODEL_VERSION, number

FEATURES = ("baseline", "opportunity", "process", "trend", "arsenal", "location", "bullpen", "environment", "opponent_adjusted_trend")
TARGETS = {"batter": ("hits", "total_bases", "home_runs"), "pitcher": ("strikeouts",)}
MIN_TRAIN = 100
MIN_HOLDOUT = 30
MIN_DATES = 14


def vector(row, metric):
    f = row["features"]
    return [number(row["baseline"].get(metric))] + [number(f.get(key, {}).get("value")) for key in FEATURES[1:]]


def fit(records):
    """Records are already filtered by grade time, capture time, version and game date."""
    if len(records) < MIN_TRAIN + MIN_HOLDOUT:
        return None
    dates = sorted({r["date"] for r in records})
    if len(dates) < MIN_DATES:
        return None
    cutoff = dates[max(1, int(len(dates) * .75))]
    train = [r for r in records if r["date"] < cutoff]
    holdout = [r for r in records if r["date"] >= cutoff]
    if len(train) < MIN_TRAIN or len(holdout) < MIN_HOLDOUT:
        return None
    x = np.array([[np.nan if v is None else v for v in r["x"]] for r in train], dtype=float)
    counts = np.sum(np.isfinite(x), axis=0)
    means = np.divide(np.nansum(x, axis=0), counts, out=np.zeros(len(FEATURES)), where=counts > 0)
    filled = np.where(np.isfinite(x), x, means)
    scales = np.std(filled, axis=0)
    scales[scales < 1e-8] = 1
    design = np.column_stack((np.ones(len(x)), (filled - means) / scales))
    penalty = np.eye(design.shape[1]) * 20.0
    penalty[0, 0] = 0
    y = np.array([r["residual"] for r in train])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y)
    def predict(values):
        raw = np.array([means[i] if v is None else v for i, v in enumerate(values)])
        return float(coefficients[0] + ((raw-means)/scales) @ coefficients[1:])
    errors = [r["residual"] - predict(r["x"]) for r in holdout]
    learned_mae = sum(abs(e) for e in errors) / len(errors)
    baseline_mae = sum(abs(r["residual"]) for r in holdout) / len(holdout)
    model = {"version": MODEL_VERSION, "means": means.tolist(), "scales": scales.tolist(),
             "coefficients": coefficients.tolist(), "errors": errors, "holdout_start": cutoff,
             "training_count": len(train), "holdout_count": len(holdout),
             "training_data_through": max(r["date"] for r in records),
             "holdout_baseline_mae": baseline_mae, "holdout_adjusted_mae": learned_mae,
             "status": "ready" if learned_mae < baseline_mae else "no_validated_improvement",
             "training_snapshot_ids": [r["snapshot_id"] for r in records]}
    model["id"] = hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest()
    return model


def adjust(row, metric, model, records):
    baseline = row["baseline"].get(metric)
    empty = {"baseline": baseline, "adjusted": None, "expected_residual": None,
             "probability_over_baseline": None, "probability_under_baseline": None,
             "attributions": [], "status": "insufficient_history", "model_run_id": None}
    if baseline is None:
        return dict(empty, status="baseline_unavailable")
    if not model or model["status"] != "ready":
        return dict(empty, status=model["status"] if model else "insufficient_history")
    x = vector(row, metric)
    contributions = [{"feature": "historical_bias", "value": model["coefficients"][0]}]
    z = []
    for i, name in enumerate(FEATURES):
        value = 0 if x[i] is None else (x[i]-model["means"][i])/model["scales"][i]
        z.append(value)
        contributions.append({"feature": name, "value": value*model["coefficients"][i+1],
                              "missing": x[i] is None})
    residual = sum(c["value"] for c in contributions)
    # Real, held-out prediction errors supply dispersion. Floor/rounding is explicit.
    samples = [max(0, round(baseline + residual + e)) for e in model["errors"]]
    distribution = empirical(samples, baseline)
    expected_residual = distribution["mean"] - baseline
    contributions.append({"feature": "holdout_error_and_count_support", "value": expected_residual-residual})
    def distance(r):
        return sum(((r["x"][i]-model["means"][i])/model["scales"][i]-z[i])**2
                   for i in range(len(z)) if r["x"][i] is not None and x[i] is not None)
    comparable = sorted(records, key=distance)[:50]
    over = sum(r["residual"] > 0 for r in comparable)
    return {**empty, **{k: distribution[k] for k in ("probability_over_baseline", "probability_under_baseline", "probability_equal_baseline")},
            "status": "ready", "training_data_through": model["training_data_through"], "adjusted": distribution["mean"], "expected_residual": expected_residual,
            "distribution": distribution, "distribution_method": "temporal_holdout_errors_count_support",
            "attributions": contributions, "model_run_id": model["id"], "confidence": "research",
            "historical_residual_percentile": sum(r["residual"] <= expected_residual for r in records)/len(records),
            "comparables": {"sample_size": len(comparable), "over_rate": over/len(comparable),
                            "interval_95": wilson(over, len(comparable)),
                            "population_over_rate": sum(r["residual"] > 0 for r in records)/len(records)},
            "validation": {key: model[key] for key in ("training_count", "holdout_count", "holdout_baseline_mae", "holdout_adjusted_mae")}}

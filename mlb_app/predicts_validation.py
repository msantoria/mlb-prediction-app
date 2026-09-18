"""Small, strict point-in-time and baseball-domain validators."""
from datetime import datetime, timezone
import math

FEATURE_VERSION = "predicts_features_v1"
MODEL_VERSION = "predicts_ridge_holdout_v1"


def utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError("Source timestamps must contain a timezone")
    if not isinstance(value, datetime):
        raise ValueError("Missing source timestamp")
    # SQLAlchemy stores UTC-naive timestamps, matching the existing database.
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def identity(value):
    value = number(value)
    if value is None or value <= 0 or not value.is_integer():
        raise ValueError("Invalid MLBAM/game identity")
    return int(value)


def asof(source, captured, starts):
    source, captured, starts = map(utc, (source, captured, starts))
    if not source <= captured < starts:
        raise ValueError("Source must precede capture and capture must precede first pitch")


def validate_player(row):
    identity(row["player_id"])
    identity(row["game_pk"])
    if row["player_type"] not in {"batter", "pitcher"}:
        raise ValueError("Unknown player type")
    if row.get("opposing_starter_id") == row["player_id"]:
        raise ValueError("Player cannot face himself")
    order = row.get("batting_order")
    if order is not None and (int(order) != order or not 1 <= order <= 9):
        raise ValueError("Batting order outside 1–9")
    limits = {"plate_appearances": 10, "batters_faced": 50, "strikeouts": 30,
              "hits": 10, "home_runs": 8, "total_bases": 40, "pitches": 160}
    for metric, value in row["baseline"].items():
        if value is not None and (number(value) is None or (metric in limits and not 0 <= value <= limits[metric])):
            raise ValueError(f"Invalid projected {metric}")

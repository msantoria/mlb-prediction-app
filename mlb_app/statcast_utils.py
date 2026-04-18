"""
Statcast data retrieval and aggregation using pybaseball.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

try:
    import pybaseball
    pybaseball.cache.enable()
    _PYBASEBALL_AVAILABLE = True
except ImportError:
    _PYBASEBALL_AVAILABLE = False


def fetch_statcast_pitcher_data(
    player_id: int, start_date: str, end_date: str
) -> pd.DataFrame:
    """Download Statcast pitch data for a pitcher over a date range.

    Uses pybaseball.statcast_pitcher which pulls from Baseball Savant.
    Returns an empty DataFrame if pybaseball is unavailable.
    """
    if not _PYBASEBALL_AVAILABLE:
        raise ImportError("pybaseball is required. Run: pip install pybaseball")
    return pybaseball.statcast_pitcher(start_date, end_date, player_id)


def fetch_statcast_batter_data(
    player_id: int, start_date: str, end_date: str
) -> pd.DataFrame:
    """Download Statcast pitch data for a batter over a date range.

    Uses pybaseball.statcast_batter which pulls from Baseball Savant.
    Returns an empty DataFrame if pybaseball is unavailable.
    """
    if not _PYBASEBALL_AVAILABLE:
        raise ImportError("pybaseball is required. Run: pip install pybaseball")
    return pybaseball.statcast_batter(start_date, end_date, player_id)


def fetch_statcast_all_events(start_date: str, end_date: str) -> pd.DataFrame:
    """Bulk-fetch ALL Statcast events (all pitchers + batters) for a date range.

    Uses pybaseball.statcast() which is far more efficient than per-pitcher
    calls for large date ranges. Ideal for one-time historical season loads.
    Returns an empty DataFrame if pybaseball is unavailable.
    """
    if not _PYBASEBALL_AVAILABLE:
        raise ImportError("pybaseball is required. Run: pip install pybaseball")
    df = pybaseball.statcast(start_dt=start_date, end_dt=end_date, parallel=True)
    if df is None:
        return pd.DataFrame()
    return df


def fetch_pitch_arsenal_leaderboard(year: int, min_pitches: int = 50) -> pd.DataFrame:
    """Download pitch arsenal leaderboard from Baseball Savant for a season.

    Returns DataFrame with columns: pitcher_id, pitch_type, pitch_name,
    pitch_count, usage_pct, whiff_pct, strikeout_pct, rv_per_100, xwoba, hard_hit_pct.
    """
    if not _PYBASEBALL_AVAILABLE:
        raise ImportError("pybaseball is required. Run: pip install pybaseball")
    try:
        df = pybaseball.statcast_pitcher_arsenal_stats(year, minPA=min_pitches)
    except TypeError:
        df = pybaseball.statcast_pitcher_arsenal_stats(year)
    return df


def calculate_pitcher_aggregates(df: pd.DataFrame) -> Dict[str, float]:
    """Compute summary stats for a pitcher from a Statcast DataFrame."""
    if df is None or df.empty:
        return {}

    total = len(df)
    velos = pd.to_numeric(df.get("release_speed", pd.Series(dtype=float)), errors="coerce")
    spins = pd.to_numeric(df.get("release_spin_rate", pd.Series(dtype=float)), errors="coerce")
    exit_v = pd.to_numeric(df.get("launch_speed", pd.Series(dtype=float)), errors="coerce")
    pfx_x = pd.to_numeric(df.get("pfx_x", pd.Series(dtype=float)), errors="coerce")
    pfx_z = pd.to_numeric(df.get("pfx_z", pd.Series(dtype=float)), errors="coerce")
    rel_x = pd.to_numeric(df.get("release_pos_x", pd.Series(dtype=float)), errors="coerce")
    rel_z = pd.to_numeric(df.get("release_pos_z", pd.Series(dtype=float)), errors="coerce")
    ext = pd.to_numeric(df.get("release_extension", pd.Series(dtype=float)), errors="coerce")

    events = df.get("events", pd.Series(dtype=str)).fillna("")
    descriptions = df.get("description", pd.Series(dtype=str)).fillna("")

    strikeouts = (events == "strikeout").sum()
    walks = (events == "walk").sum()
    plate_appearances = events[events != ""].shape[0]
    hard_hit = (exit_v >= 95).sum()
    batted = exit_v.notna().sum()

    xwoba_vals = pd.to_numeric(df.get("estimated_woba_using_speedangle", pd.Series(dtype=float)), errors="coerce")
    xba_vals = pd.to_numeric(df.get("estimated_ba_using_speedangle", pd.Series(dtype=float)), errors="coerce")

    return {
        "avg_velocity": float(velos.mean()) if not velos.isna().all() else None,
        "avg_spin_rate": float(spins.mean()) if not spins.isna().all() else None,
        "hard_hit_pct": float(hard_hit / batted) if batted > 0 else None,
        "k_pct": float(strikeouts / plate_appearances) if plate_appearances > 0 else None,
        "bb_pct": float(walks / plate_appearances) if plate_appearances > 0 else None,
        "xwoba": float(xwoba_vals.mean()) if not xwoba_vals.isna().all() else None,
        "xba": float(xba_vals.mean()) if not xba_vals.isna().all() else None,
        "avg_horiz_break": float(pfx_x.mean()) if not pfx_x.isna().all() else None,
        "avg_vert_break": float(pfx_z.mean()) if not pfx_z.isna().all() else None,
        "avg_release_pos_x": float(rel_x.mean()) if not rel_x.isna().all() else None,
        "avg_release_pos_z": float(rel_z.mean()) if not rel_z.isna().all() else None,
        "avg_release_extension": float(ext.mean()) if not ext.isna().all() else None,
    }


def calculate_batter_aggregates(df: pd.DataFrame) -> Dict[str, float]:
    """Compute summary stats for a batter from a Statcast DataFrame."""
    if df is None or df.empty:
        return {}

    exit_v = pd.to_numeric(df.get("launch_speed", pd.Series(dtype=float)), errors="coerce")
    launch_a = pd.to_numeric(df.get("launch_angle", pd.Series(dtype=float)), errors="coerce")
    events = df.get("events", pd.Series(dtype=str)).fillna("")

    batted = exit_v.notna().sum()
    hard_hit = (exit_v >= 95).sum()
    barrel = ((exit_v >= 98) & (launch_a >= 26) & (launch_a <= 30)).sum()

    plate_appearances = events[events != ""].shape[0]
    strikeouts = (events == "strikeout").sum()
    walks = (events == "walk").sum()

    hits = events.isin(["single", "double", "triple", "home_run"]).sum()
    at_bats = events.isin(["single", "double", "triple", "home_run", "strikeout", "field_out",
                            "grounded_into_double_play", "double_play", "force_out",
                            "fielders_choice", "fielders_choice_out"]).sum()

    return {
        "avg_exit_velocity": float(exit_v.mean()) if batted > 0 else None,
        "avg_launch_angle": float(launch_a.mean()) if batted > 0 else None,
        "hard_hit_pct": float(hard_hit / batted) if batted > 0 else None,
        "barrel_pct": float(barrel / batted) if batted > 0 else None,
        "k_pct": float(strikeouts / plate_appearances) if plate_appearances > 0 else None,
        "bb_pct": float(walks / plate_appearances) if plate_appearances > 0 else None,
        "batting_avg": float(hits / at_bats) if at_bats > 0 else None,
    }


def build_pitch_arsenal_from_statcast(df: pd.DataFrame, pitcher_id: int, season: int) -> List[Dict]:
    """Derive per-pitch-type arsenal stats from raw Statcast events DataFrame.

    Fallback when the leaderboard endpoint isn't available. Returns a list of
    dicts matching the PitchArsenal schema.
    """
    if df is None or df.empty:
        return []

    df = df.copy()
    df["release_speed"] = pd.to_numeric(df.get("release_speed"), errors="coerce")
    df["launch_speed"] = pd.to_numeric(df.get("launch_speed"), errors="coerce")
    df["description"] = df.get("description", pd.Series(dtype=str)).fillna("")
    df["events"] = df.get("events", pd.Series(dtype=str)).fillna("")

    total_pitches = len(df)
    records = []

    for pitch_type, group in df.groupby("pitch_type"):
        if not pitch_type or str(pitch_type).strip() == "":
            continue
        n = len(group)
        whiffs = group["description"].str.contains("swinging_strike", case=False).sum()
        swings = group["description"].str.contains("swing|foul|hit_into_play", case=False, regex=True).sum()
        strikeouts = (group["events"] == "strikeout").sum()
        plate_appearances = group["events"][group["events"] != ""].shape[0]
        hard_hit = (group["launch_speed"] >= 95).sum()
        batted = group["launch_speed"].notna().sum()

        xwoba_col = group.get("estimated_woba_using_speedangle")
        xwoba_mean = None
        if xwoba_col is not None:
            xv = pd.to_numeric(xwoba_col, errors="coerce")
            if not xv.isna().all():
                xwoba_mean = float(xv.mean())

        records.append({
            "season": season,
            "pitcher_id": pitcher_id,
            "pitch_type": str(pitch_type),
            "pitch_name": str(pitch_type),
            "pitch_count": n,
            "usage_pct": n / total_pitches if total_pitches > 0 else None,
            "whiff_pct": float(whiffs / swings) if swings > 0 else None,
            "strikeout_pct": float(strikeouts / plate_appearances) if plate_appearances > 0 else None,
            "rv_per_100": None,
            "xwoba": xwoba_mean,
            "hard_hit_pct": float(hard_hit / batted) if batted > 0 else None,
        })

    return records

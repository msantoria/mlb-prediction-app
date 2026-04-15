"""
ETL (Extract, Transform, Load) utilities for the MLB prediction app.

This module centralises the logic required to pull raw data from public
data providers (e.g., Baseball Savant’s Statcast, MLB Stats API) and
persist it into a relational database for downstream analysis.  The focus
is on retrieving all of the per‑pitch, per‑pitcher and per‑batter
statistics needed to recreate the `advancedPitched` and `pitchingMatchups`
tables from the October 1 2025 workbook.  It also includes functions to
ingest pitch‑arsenal leaderboards and platoon splits.

Note: These functions are designed as a starting point.  Because this
repository runs in a restricted environment, the HTTP calls below are
provided as examples and have not been executed here.  When deploying
the app in production, you should test and tune the query parameters
against the latest Baseball Savant and MLB Stats endpoints.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Iterable, List, Optional

import pandas as pd  # type: ignore
import requests  # type: ignore
from sqlalchemy import create_engine, text  # type: ignore


################################################################################
#  Configuration
################################################################################

# Base URLs for external APIs.  These do not include API keys or sensitive
# credentials; those should be supplied via environment variables if needed.
STATCAST_CSV_URL = "https://baseballsavant.mlb.com/"  # Will be appended with query params
PITCH_ARSENAL_URL = (
    "https://baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats"
)
MLB_STATS_BASE_URL = "https://statsapi.mlb.com/api/v1"

# Database connection string.  Expect an environment variable like
# DATABASE_URL="postgresql://user:pass@host:port/database" to be set.  Use
# SQLite as a fallback for local development.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///mlb.db")


################################################################################
#  Helper functions
################################################################################

def get_db_engine():
    """Return a SQLAlchemy engine using the configured database URL."""
    return create_engine(DATABASE_URL)


def _parse_date(date_like: str | datetime) -> str:
    """Ensure dates are passed as ISO‑formatted strings."""
    if isinstance(date_like, datetime):
        return date_like.strftime("%Y-%m-%d")
    return str(date_like)


################################################################################
#  Statcast data
################################################################################

def fetch_statcast_events(
    start_date: str | datetime,
    end_date: str | datetime,
    player_ids: Optional[Iterable[int]] = None,
    player_type: str = "all",
) -> pd.DataFrame:
    """Retrieve raw Statcast events between two dates.

    Parameters
    ----------
    start_date : str or datetime
        The beginning of the date range (inclusive).
    end_date : str or datetime
        The end of the date range (inclusive).
    player_ids : iterable of int, optional
        If provided, restricts results to these MLBAM player IDs.
    player_type : {"all", "pitcher", "batter"}
        Filters results by pitcher or batter.  The default "all" returns
        all events regardless of player role.

    Returns
    -------
    DataFrame
        A pandas DataFrame of pitch‑level events with columns for pitch type,
        release metrics, movement, count context and batted‑ball outcomes.

    Notes
    -----
    Baseball Savant’s Statcast search provides CSV downloads.  The query
    parameters used here mirror those found in the web interface.  For
    example:

        https://baseballsavant.mlb.com/++anycsvendpoint++?all=true&start_date=2026-04-01&end_date=2026-04-02

    The exact endpoint and parameters may change year to year, so be
    prepared to update them based on the latest documentation.  No API key
    is required as of 2026.
    """
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    params = {
        "start_date": start,
        "end_date": end,
        "all": "true",  # return all events, not summarised
    }
    if player_type != "all":
        params["player_type"] = player_type
    if player_ids:
        # Baseball Savant expects a comma‑separated list of IDs.  Note that
        # thousands of IDs may trigger rate limits, so batch requests if needed.
        params["player_ids"] = ",".join(str(pid) for pid in player_ids)
    url = STATCAST_CSV_URL + "statcast_search/csv"
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    # The endpoint returns a CSV string; parse into DataFrame
    return pd.read_csv(pd.compat.StringIO(resp.text))


################################################################################
#  Pitch arsenal data
################################################################################

def fetch_pitch_arsenal(
    year: int,
    min_bbe: Optional[int] = None,
    min_pitches: Optional[int] = None,
    player_type: str = "pitcher",
) -> pd.DataFrame:
    """Download pitch‑arsenal leaderboard stats for a given year.

    Parameters
    ----------
    year : int
        Season year (e.g. 2025 or 2026).
    min_bbe : int, optional
        Minimum batted‑ball events (for hitters) to qualify.  Only used when
        `player_type="batter"`.
    min_pitches : int, optional
        Minimum pitches thrown (for pitchers) to qualify.
    player_type : {"pitcher", "batter"}
        Whether to retrieve pitcher or hitter pitch‑arsenal stats.

    Returns
    -------
    DataFrame
        A DataFrame with columns matching the original `layertwo.py`
        (Pitch Count, Usage %, Whiff %, K %, RV/100, xwOBA, Hard Hit %, etc.).
    """
    params = {
        "year": year,
        "type": player_type,
        "csv": "true",
    }
    if min_bbe is not None:
        params["minBBE"] = min_bbe
    if min_pitches is not None:
        params["minP"] = min_pitches
    resp = requests.get(PITCH_ARSENAL_URL, params=params, timeout=60)
    resp.raise_for_status()
    return pd.read_csv(pd.compat.StringIO(resp.text))


################################################################################
#  MLB Stats API helpers
################################################################################

def fetch_schedule(date: str | datetime) -> pd.DataFrame:
    """Get the MLB schedule for a specific date, including probable pitchers.

    Parameters
    ----------
    date : str or datetime
        Date of interest (YYYY-MM-DD).

    Returns
    -------
    DataFrame
        Schedule with columns for game time, home/away teams and probable
        pitchers.  This function wraps the Stats API call used in
        `layerone.py`【426202769562903†L64-L97】.
    """
    ds = _parse_date(date)
    url = f"{MLB_STATS_BASE_URL}/schedule"
    params = {
        "sportId": 1,
        "date": ds,
        "hydrate": "probablePitcher"
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    records: List[dict] = []
    for day in data.get("dates", []):
        for game in day.get("games", []):
            home = game["teams"]["home"]
            away = game["teams"]["away"]
            rec = {
                "Game Time (UTC)": game["gameDate"],
                "Away Team": away["team"]["name"],
                "Home Team": home["team"]["name"],
                "Away Pitcher": away.get("probablePitcher", {}).get("fullName"),
                "Away Pitcher ID": away.get("probablePitcher", {}).get("id"),
                "Home Pitcher": home.get("probablePitcher", {}).get("fullName"),
                "Home Pitcher ID": home.get("probablePitcher", {}).get("id"),
            }
            records.append(rec)
    return pd.DataFrame(records)


def fetch_team_splits(team_id: int, season: int, split_code: str) -> dict:
    """Retrieve team hitting stats versus left‑ or right‑handed pitchers.

    This wraps the Stats API `stats` endpoint with the `split` parameter as
    used in layerten.py.  Pass `split_code="vsLHP"` for splits against
    left‑handed pitchers or `split_code="vsRHP"` for right‑handed splits.
    """
    url = f"{MLB_STATS_BASE_URL}/teams/{team_id}/stats"
    params = {
        "stats": "season",
        "group": "hitting",
        "season": season,
        "split": split_code,
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    splits = data.get("stats", [])[0].get("splits", []) if data.get("stats") else []
    return splits[0].get("stat", {}) if splits else {}


################################################################################
#  Load functions
################################################################################

def load_dataframe_to_table(df: pd.DataFrame, table_name: str, if_exists: str = "append") -> None:
    """Load a DataFrame into the specified database table.

    Parameters
    ----------
    df : DataFrame
        DataFrame to be written.
    table_name : str
        Name of the table to write into.
    if_exists : {"append", "replace", "fail"}
        Behaviour if the table already exists.
    """
    engine = get_db_engine()
    with engine.begin() as conn:
        df.to_sql(table_name, con=conn, if_exists=if_exists, index=False)


def create_tables(schema_sql: str) -> None:
    """Execute a SQL schema definition to create tables.

    Provide a `schema_sql` string containing CREATE TABLE statements.  This is
    useful for bootstrapping a new database.  All statements will run
    within the same transaction.
    """
    engine = get_db_engine()
    with engine.begin() as conn:
        for stmt in filter(None, schema_sql.split(";")):
            conn.execute(text(stmt))


################################################################################
#  Example pipeline (to be scheduled externally)
################################################################################

def run_daily_etl(date: str | datetime) -> None:
    """Orchestrate the ETL process for a specific date.

    This function illustrates how to combine the helper functions above to
    populate your database.  It should be triggered by a scheduler (e.g.
    cron, Airflow, GitHub Actions) shortly after midnight Eastern Time.
    """
    ds = _parse_date(date)
    # Step 1: get schedule and probable pitchers
    sched_df = fetch_schedule(ds)
    # Step 2: extract unique pitcher IDs and download their Statcast events
    pitcher_ids: List[int] = [
        pid for pid in sched_df["Away Pitcher ID"].dropna().astype(int).tolist()
    ] + [
        pid for pid in sched_df["Home Pitcher ID"].dropna().astype(int).tolist()
    ]
    if pitcher_ids:
        start_date = (pd.to_datetime(ds) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
        events = fetch_statcast_events(start_date, ds, player_ids=pitcher_ids, player_type="pitcher")
        load_dataframe_to_table(events, "statcast_events")
    # Step 3: download pitch‑arsenal stats for the current season
    season_year = pd.to_datetime(ds).year
    arsenal_df = fetch_pitch_arsenal(season_year, min_pitches=50, player_type="pitcher")
    load_dataframe_to_table(arsenal_df, "pitch_arsenal")
    # Step 4: optionally load team splits (example for vsLHP and vsRHP)
    splits_records: List[dict] = []
    for team_id in sched_df["Home Pitcher ID"].dropna().astype(int).tolist() + sched_df["Away Pitcher ID"].dropna().astype(int).tolist():
        for split_code in ["vsLHP", "vsRHP"]:
            stat = fetch_team_splits(team_id, season_year, split_code)
            if stat:
                stat["TeamID"] = team_id
                stat["Season"] = season_year
                stat["Split"] = split_code
                splits_records.append(stat)
    if splits_records:
        splits_df = pd.DataFrame(splits_records)
        load_dataframe_to_table(splits_df, "team_splits")

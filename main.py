main.py#!/usr/bin/env python3
"""
MLB Daily Matchups & Predictions
================================

This script fetches the Major League Baseball (MLB) schedule for a given date,
retrieves current team records from the MLB Stats API, and generates simple
win‑probability predictions for each scheduled game.  Predictions are based
solely on each team’s current winning percentage and a modest home‑field
advantage.  It prints a tabular summary to the console, listing the
matchups, predicted home win probability, and the projected winner.

Usage
-----
To view predictions for today (according to your system clock):

    python main.py

To view predictions for a specific date:

    python main.py --date YYYY-MM-DD

If no games are scheduled on the given date, the script will let you know.

Note
----
This script uses the MLB Stats API (an unofficial but publicly available
endpoint) to obtain schedule and standings data【184818780191276†L193-L256】.  No API key is required
for basic usage.  The win‑probability model here is intentionally simple and
intended for demonstration purposes; for more accurate predictions you may
wish to incorporate starting pitcher data, offensive/defensive metrics,
and adjust the home‑field advantage accordingly.
"""

import argparse
import sys
from datetime import datetime
from typing import Dict, Iterable, List, Optional

import requests


def fetch_schedule(date_str: str) -> List[Dict]:
    """Return the list of scheduled games for the specified date.

    Parameters
    ----------
    date_str : str
        Date in ``YYYY-MM-DD`` format.

    Returns
    -------
    list of dict
        Each dict represents a game with keys including ``teams`` and
        ``status``.  If no games are scheduled, an empty list is returned.
    """
    # sportId=1 filters to Major League Baseball (MLB).  Without this
    # parameter the API may return an error message rather than schedule data.
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_str}"
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch schedule data: {exc}") from exc

    data = response.json()
    # The 'dates' key contains a list of date entries; typically there is
    # exactly one element for the requested date.  If the list is empty,
    # there are no games scheduled.
    if not data.get("dates"):
        return []
    return data["dates"][0].get("games", [])


def fetch_team_records(season: str) -> Dict[int, Dict[str, float]]:
    """Fetch win/loss records and run differentials for all teams in a season.

    Parameters
    ----------
    season : str
        The season year (e.g., ``"2026"``).  The MLB Stats API uses the
        season year to return standings information.

    Returns
    -------
    dict
        Mapping from team ID to a dict containing wins, losses, win_pct and
        run_diff.  If the request fails, a RuntimeError is raised.
    """
    url = (
        f"https://statsapi.mlb.com/api/v1/standings?leagueId=103,104&season={season}"
    )
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch standings data: {exc}") from exc

    data = response.json()
    records: Dict[int, Dict[str, float]] = {}
    for record in data.get("records", []):
        for team_record in record.get("teamRecords", []):
            tid = team_record["team"]["id"]
            wins = team_record.get("wins", 0)
            losses = team_record.get("losses", 0)
            # Compute win percentage; avoid division by zero if no games played
            win_pct = (wins / (wins + losses)) if (wins + losses) > 0 else 0.0
            run_diff = team_record.get("runsScored", 0) - team_record.get(
                "runsAllowed", 0
            )
            records[tid] = {
                "wins": float(wins),
                "losses": float(losses),
                "win_pct": float(win_pct),
                "run_diff": float(run_diff),
            }
    return records


def predict_home_win_prob(
    home_win_pct: float, away_win_pct: float, home_adv: float = 0.03
) -> float:
    """Estimate the home team’s probability of winning.

    This function implements a simple ratio model: the home team’s win
    percentage is boosted by a small constant (default 3%) to account for
    home‑field advantage, and then the home probability is computed as

        home_prob = home_pct_adj / (home_pct_adj + away_pct)

    Parameters
    ----------
    home_win_pct : float
        The home team’s current winning percentage (0–1).
    away_win_pct : float
        The away team’s current winning percentage (0–1).
    home_adv : float, optional
        Additional bonus applied to the home team’s win percentage to
        represent home‑field advantage.  A value of 0.03 equates to
        approximately a 3% boost.

    Returns
    -------
    float
        Home win probability between 0 and 1.
    """
    home_pct_adj = home_win_pct + home_adv
    denom = home_pct_adj + away_win_pct
    if denom <= 0:
        return 0.5  # default to 50/50 if both win pcts are zero
    return home_pct_adj / denom


def generate_predictions(date_str: str) -> List[Dict[str, object]]:
    """Generate predictions for all scheduled games on a given date.

    Parameters
    ----------
    date_str : str
        Date in ``YYYY-MM-DD`` format.

    Returns
    -------
    list of dict
        Each element represents one game with keys:

        * ``away_team`` – Away team name
        * ``home_team`` – Home team name
        * ``home_prob`` – Predicted probability that home team wins (0–1)
        * ``predicted_winner`` – Name of the predicted winning team
        * ``home_wins`` – Home team wins to date
        * ``home_losses`` – Home team losses to date
        * ``away_wins`` – Away team wins to date
        * ``away_losses`` – Away team losses to date
    """
    schedule = fetch_schedule(date_str)
    if not schedule:
        return []
    # Determine season from date string; parse into datetime to handle ISO format
    try:
        season_year = str(datetime.fromisoformat(date_str).year)
    except ValueError:
        raise ValueError(
            f"Invalid date format '{date_str}'. Use YYYY-MM-DD (e.g. 2026-04-15)."
        )
    records = fetch_team_records(season_year)
    predictions: List[Dict[str, object]] = []
    for game in schedule:
        # Each game dict contains 'teams' with 'home' and 'away'.  Each nested
        # dict includes a 'team' subdict with the ID and name.
        home_info = game["teams"]["home"]["team"]
        away_info = game["teams"]["away"]["team"]
        home_id, away_id = home_info["id"], away_info["id"]
        home_name, away_name = home_info["name"], away_info["name"]
        home_record = records.get(home_id, {"win_pct": 0.5, "wins": 0, "losses": 0})
        away_record = records.get(away_id, {"win_pct": 0.5, "wins": 0, "losses": 0})
        home_prob = predict_home_win_prob(
            home_record["win_pct"], away_record["win_pct"]
        )
        predicted_winner = home_name if home_prob >= 0.5 else away_name
        predictions.append(
            {
                "away_team": away_name,
                "home_team": home_name,
                "home_prob": home_prob,
                "predicted_winner": predicted_winner,
                "home_wins": home_record.get("wins", 0.0),
                "home_losses": home_record.get("losses", 0.0),
                "away_wins": away_record.get("wins", 0.0),
                "away_losses": away_record.get("losses", 0.0),
            }
        )
    return predictions


def print_predictions(predictions: Iterable[Dict[str, object]]) -> None:
    """Print a formatted table of predictions to the console."""
    if not predictions:
        print("No games scheduled or data unavailable.")
        return
    header = f"{'Away Team':25s} {'Home Team':25s} {'Home Win %':>11s}   Predicted Winner"
    print(header)
    print("-" * len(header))
    for game in predictions:
        away_team = game["away_team"]
        home_team = game["home_team"]
        home_prob = game["home_prob"] * 100
        winner = game["predicted_winner"]
        print(f"{away_team:25s} {home_team:25s} {home_prob:10.2f}%   {winner}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate MLB daily matchup predictions based on current standings."
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help=(
            "Date in YYYY-MM-DD format (default: today in system timezone). "
            "Example: --date 2026-04-15"
        ),
    )
    args = parser.parse_args(argv)

    # Determine date; if not provided, use today according to system clock
    if args.date:
        date_str = args.date
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        predictions = generate_predictions(date_str)
    except Exception as exc:
        print(f"Error generating predictions: {exc}", file=sys.stderr)
        return 1
    if not predictions:
        print(f"No MLB games scheduled on {date_str} or data unavailable.")
    else:
        print(f"MLB Matchups and Predictions for {date_str}")
        print()
        print_predictions(predictions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from typing import List, Set

from mlb_app.app import _game_from_schedule, _get_session
from mlb_app.pitcher_profile_store import upsert_pitcher_profile

MLB_SCHEDULE_HYDRATE = "probablePitcher,team"


def _target_dates(include_tomorrow: bool) -> List[str]:
    today = dt.date.today()
    dates = [today.isoformat()]
    if include_tomorrow:
        dates.append((today + dt.timedelta(days=1)).isoformat())
    return dates


def _probable_pitcher_ids_for_date(date_str: str) -> Set[int]:
    from requests import get

    schedule_url = "https://statsapi.mlb.com/api/v1/schedule"
    resp = get(
        schedule_url,
        params={"sportId": 1, "date": date_str, "hydrate": MLB_SCHEDULE_HYDRATE},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    pitcher_ids: Set[int] = set()
    for date_row in data.get("dates", []) or []:
        for game in date_row.get("games", []) or []:
            teams = game.get("teams", {}) or {}
            for side in ("home", "away"):
                probable = (teams.get(side) or {}).get("probablePitcher") or {}
                pid = probable.get("id")
                if pid:
                    pitcher_ids.add(int(pid))
    return pitcher_ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Build additive pitcher profile serving tables")
    parser.add_argument("--season", type=int, default=dt.date.today().year)
    parser.add_argument("--pitcher-id", action="append", type=int, default=[])
    parser.add_argument("--today-probables", action="store_true")
    parser.add_argument("--include-tomorrow", action="store_true")
    args = parser.parse_args()

    target_pitchers: Set[int] = {int(pid) for pid in args.pitcher_id}
    if args.today_probables:
        for date_str in _target_dates(args.include_tomorrow):
            target_pitchers.update(_probable_pitcher_ids_for_date(date_str))

    if not target_pitchers:
        raise SystemExit("No target pitchers resolved. Pass --pitcher-id or --today-probables.")

    Session = _get_session()
    results = []
    with Session() as session:
        for pitcher_id in sorted(target_pitchers):
            try:
                results.append(upsert_pitcher_profile(session, pitcher_id, args.season))
            except Exception as exc:
                results.append({
                    "pitcher_id": pitcher_id,
                    "season": args.season,
                    "error": str(exc),
                })
    print(json.dumps({"season": args.season, "results": results}, indent=2, default=str))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Audit and repair duplicate rows in ``statcast_events``.

Dry-run is the default.  ``--apply`` performs one transaction that:

1. keeps the richest/latest row for every canonical MLB pitch identity;
2. removes incomplete legacy rows shadowed by canonical rows for the same
   pitcher and date;
3. collapses exact remaining legacy copies; and
4. installs a partial unique index that prevents canonical duplicates.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import func, or_, text
from sqlalchemy.orm import aliased

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mlb_app.database import StatcastEvent, get_engine, get_session


INDEX_NAME = "ux_statcast_events_pitch_identity"


def _scope_filter(pitcher_id: Optional[int]):
    return (StatcastEvent.pitcher_id == int(pitcher_id),) if pitcher_id is not None else ()


def audit(session, pitcher_id: Optional[int] = None) -> Dict[str, int]:
    scope = _scope_filter(pitcher_id)
    complete = (
        StatcastEvent.game_pk.isnot(None),
        StatcastEvent.at_bat_number.isnot(None),
        StatcastEvent.pitch_number.isnot(None),
    )
    incomplete = or_(
        StatcastEvent.game_pk.is_(None),
        StatcastEvent.at_bat_number.is_(None),
        StatcastEvent.pitch_number.is_(None),
    )
    total_rows = int(session.query(func.count(StatcastEvent.id)).filter(*scope).scalar() or 0)
    complete_rows = int(
        session.query(func.count(StatcastEvent.id)).filter(*scope, *complete).scalar() or 0
    )
    canonical_groups = (
        session.query(
            StatcastEvent.game_pk,
            StatcastEvent.at_bat_number,
            StatcastEvent.pitch_number,
        )
        .filter(*scope, *complete)
        .group_by(
            StatcastEvent.game_pk,
            StatcastEvent.at_bat_number,
            StatcastEvent.pitch_number,
        )
        .subquery()
    )
    canonical_pitches = int(session.query(func.count()).select_from(canonical_groups).scalar() or 0)

    canonical = aliased(StatcastEvent)
    shadowed_query = session.query(func.count(StatcastEvent.id)).filter(*scope, incomplete).filter(
        session.query(canonical.id)
        .filter(
            canonical.pitcher_id == StatcastEvent.pitcher_id,
            canonical.game_date == StatcastEvent.game_date,
            canonical.game_pk.isnot(None),
            canonical.at_bat_number.isnot(None),
            canonical.pitch_number.isnot(None),
        )
        .exists()
    )
    shadowed_legacy_rows = int(shadowed_query.scalar() or 0)
    return {
        "total_rows": total_rows,
        "complete_identity_rows": complete_rows,
        "canonical_pitches": canonical_pitches,
        "duplicate_complete_rows": max(complete_rows - canonical_pitches, 0),
        "incomplete_identity_rows": max(total_rows - complete_rows, 0),
        "shadowed_legacy_rows": shadowed_legacy_rows,
    }


def _sql_scope(pitcher_id: Optional[int], alias: str = "") -> tuple[str, Dict[str, Any]]:
    if pitcher_id is None:
        return "", {}
    prefix = f"{alias}." if alias else ""
    return f" AND {prefix}pitcher_id = :pitcher_id", {"pitcher_id": int(pitcher_id)}


def repair(engine, pitcher_id: Optional[int] = None) -> Dict[str, Any]:
    Session = get_session(engine)
    with Session() as session:
        before = audit(session, pitcher_id)

    scope_sql, params = _sql_scope(pitcher_id)
    legacy_partition = ", ".join(
        (
            "game_date",
            "pitcher_id",
            "batter_id",
            "pitch_type",
            "description",
            "events",
            "inning",
            "inning_topbot",
            "outs_when_up",
            "balls",
            "strikes",
            "release_speed",
            "release_spin_rate",
            "pfx_x",
            "pfx_z",
            "plate_x",
            "plate_z",
            "launch_speed",
            "launch_angle",
            "stand",
            "p_throws",
        )
    )

    with engine.begin() as connection:
        duplicate_result = connection.execute(
            text(
                f"""
                WITH ranked AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY game_pk, at_bat_number, pitch_number
                               ORDER BY (
                                   CASE WHEN description IS NOT NULL AND LOWER(TRIM(description)) NOT IN ('', 'nan', 'none', 'null', 'na', 'n/a') THEN 1 ELSE 0 END +
                                   CASE WHEN events IS NOT NULL AND LOWER(TRIM(events)) NOT IN ('', 'nan', 'none', 'null', 'na', 'n/a') THEN 1 ELSE 0 END +
                                   CASE WHEN pitch_type IS NOT NULL AND LOWER(TRIM(pitch_type)) NOT IN ('', 'nan', 'none', 'null', 'na', 'n/a') THEN 1 ELSE 0 END +
                                   CASE WHEN release_speed IS NOT NULL THEN 1 ELSE 0 END +
                                   CASE WHEN release_spin_rate IS NOT NULL THEN 1 ELSE 0 END +
                                   CASE WHEN plate_x IS NOT NULL THEN 1 ELSE 0 END +
                                   CASE WHEN plate_z IS NOT NULL THEN 1 ELSE 0 END +
                                   CASE WHEN estimated_woba_using_speedangle IS NOT NULL THEN 1 ELSE 0 END +
                                   CASE WHEN estimated_ba_using_speedangle IS NOT NULL THEN 1 ELSE 0 END
                               ) DESC,
                               id DESC
                           ) AS pitch_rank
                    FROM statcast_events
                    WHERE game_pk IS NOT NULL
                      AND at_bat_number IS NOT NULL
                      AND pitch_number IS NOT NULL
                      {scope_sql}
                )
                DELETE FROM statcast_events
                WHERE id IN (SELECT id FROM ranked WHERE pitch_rank > 1)
                """
            ),
            params,
        )

        legacy_scope_sql, legacy_params = _sql_scope(pitcher_id, "statcast_events")
        shadowed_result = connection.execute(
            text(
                f"""
                DELETE FROM statcast_events
                WHERE (
                    game_pk IS NULL OR at_bat_number IS NULL OR pitch_number IS NULL
                )
                {legacy_scope_sql}
                AND EXISTS (
                    SELECT 1
                    FROM statcast_events AS canonical
                    WHERE canonical.pitcher_id = statcast_events.pitcher_id
                      AND canonical.game_date = statcast_events.game_date
                      AND canonical.game_pk IS NOT NULL
                      AND canonical.at_bat_number IS NOT NULL
                      AND canonical.pitch_number IS NOT NULL
                )
                """
            ),
            legacy_params,
        )

        legacy_result = connection.execute(
            text(
                f"""
                WITH ranked_legacy AS (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY {legacy_partition}
                               ORDER BY id DESC
                           ) AS legacy_rank
                    FROM statcast_events
                    WHERE (game_pk IS NULL OR at_bat_number IS NULL OR pitch_number IS NULL)
                    {scope_sql}
                )
                DELETE FROM statcast_events
                WHERE id IN (SELECT id FROM ranked_legacy WHERE legacy_rank > 1)
                """
            ),
            params,
        )

        # A player-scoped repair cannot safely create a table-wide barrier.
        if pitcher_id is None:
            connection.execute(
                text(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME}
                    ON statcast_events (game_pk, at_bat_number, pitch_number)
                    WHERE game_pk IS NOT NULL
                      AND at_bat_number IS NOT NULL
                      AND pitch_number IS NOT NULL
                    """
                )
            )

        TransactionSession = get_session(connection)
        with TransactionSession() as validation_session:
            after = audit(validation_session, pitcher_id)
        if after["canonical_pitches"] != before["canonical_pitches"]:
            raise RuntimeError("Repair changed the canonical pitch count; transaction rolled back.")
        if after["duplicate_complete_rows"] != 0:
            raise RuntimeError("Canonical duplicates remain after repair; transaction rolled back.")

    return {
        "scope": {"pitcher_id": pitcher_id},
        "before": before,
        "after": after,
        "deleted": {
            "complete_duplicates": max(before["duplicate_complete_rows"] - after["duplicate_complete_rows"], 0),
            "shadowed_legacy": max(before["shadowed_legacy_rows"] - after["shadowed_legacy_rows"], 0),
            "remaining_legacy_duplicates": max(
                before["total_rows"]
                - after["total_rows"]
                - before["duplicate_complete_rows"]
                - before["shadowed_legacy_rows"],
                0,
            ),
        },
        "rowcount_hints": {
            "complete_delete": duplicate_result.rowcount,
            "shadowed_delete": shadowed_result.rowcount,
            "legacy_delete": legacy_result.rowcount,
        },
        "unique_index_installed": pitcher_id is None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Perform the repair transaction.")
    parser.add_argument("--pitcher-id", type=int, help="Limit audit/repair to one MLB pitcher ID.")
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required; no database was changed.")
    engine = get_engine(database_url)
    Session = get_session(engine)
    if not args.apply:
        with Session() as session:
            result = {
                "mode": "dry_run",
                "scope": {"pitcher_id": args.pitcher_id},
                "audit": audit(session, args.pitcher_id),
                "next_step": "Re-run with --apply after reviewing these counts.",
            }
    else:
        result = {"mode": "applied", **repair(engine, args.pitcher_id)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

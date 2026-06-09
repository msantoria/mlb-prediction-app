#!/usr/bin/env python3
"""Run KIBL Bet105 baseline or diff syncs.

Examples:
    python scripts/sync_kibl_bet105.py --baseline --prematch
    python scripts/sync_kibl_bet105.py --diff --live
    python scripts/sync_kibl_bet105.py --baseline --prematch --markets-only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mlb_app.database import create_tables, get_engine, get_session
from mlb_app.kibl_integration import (
    KIBL_FIXTURES_PATH,
    KIBL_LIVE_BETTING_TYPE_ID,
    KIBL_MARKETS_PATH,
    KIBL_PREMATCH_BETTING_TYPE_ID,
    build_default_client,
    redact_secrets,
    sync_kibl_endpoint,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync KIBL Bet105 fixtures and markets")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--baseline", action="store_true", help="Run baseline pulls without since_last_updated")
    mode.add_argument("--diff", action="store_true", help="Run diff pulls with stored since_last_updated watermarks")

    segment = parser.add_mutually_exclusive_group(required=True)
    segment.add_argument("--prematch", action="store_true", help="Use prematch betting_type_id")
    segment.add_argument("--live", action="store_true", help="Use live betting_type_id")
    segment.add_argument("--all", action="store_true", help="Run both prematch and live")

    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--fixtures-only", action="store_true", help="Only sync fixtures")
    scope.add_argument("--markets-only", action="store_true", help="Only sync markets")
    parser.add_argument("--league-id", default=None, help="Override KIBL league_id filter, e.g. 20,643")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    engine = get_engine(os.getenv("DATABASE_URL", "sqlite:///mlb.db"))
    create_tables(engine)
    SessionLocal = get_session(engine)
    client = build_default_client()

    betting_types: List[int]
    if args.all:
        betting_types = [KIBL_PREMATCH_BETTING_TYPE_ID, KIBL_LIVE_BETTING_TYPE_ID]
    elif args.live:
        betting_types = [KIBL_LIVE_BETTING_TYPE_ID]
    else:
        betting_types = [KIBL_PREMATCH_BETTING_TYPE_ID]

    paths: List[str]
    if args.fixtures_only:
        paths = [KIBL_FIXTURES_PATH]
    elif args.markets_only:
        paths = [KIBL_MARKETS_PATH]
    else:
        paths = [KIBL_FIXTURES_PATH, KIBL_MARKETS_PATH]

    summaries: List[Dict[str, Any]] = []
    with SessionLocal() as session:
        for betting_type_id in betting_types:
            for path in paths:
                summaries.append(
                    sync_kibl_endpoint(
                        session=session,
                        client=client,
                        path=path,
                        betting_type_id=betting_type_id,
                        league_id=args.league_id,
                        baseline=args.baseline,
                    )
                )
    print(json.dumps(redact_secrets({"kibl_sync": summaries}), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

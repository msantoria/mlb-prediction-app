#!/usr/bin/env python3
"""Resumable join of genuine saved pregame snapshots to existing Finals. No reconstruction."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import select
from mlb_app.predicts_models import PredictsGame
from mlb_app.predicts_service import session_factory
from mlb_app.predicts_snapshots import grade


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--after-game-pk",type=int,default=0)
    parser.add_argument("--limit",type=int,default=100)
    args=parser.parse_args()
    if not 1<=args.limit<=1000:
        parser.error("limit must be 1–1000")
    with session_factory()() as session:
        ids=list(session.scalars(select(PredictsGame.game_pk).where(PredictsGame.game_pk>args.after_game_pk).order_by(PredictsGame.game_pk).limit(args.limit)))
        for pk in ids:
            count=grade(session,datetime.utcnow(),pk)
            session.commit()
            print(f"game_pk={pk} graded={count} resume_after={pk}",flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())

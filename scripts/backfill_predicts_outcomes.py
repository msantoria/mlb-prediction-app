#!/usr/bin/env python3
"""Resumable date-range import of genuine saved pregame projections."""
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
import json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mlb_app.predicts_service import session_factory
from mlb_app.predicts_backfill import backfill_range

def main():
    today=date.today()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-date',type=date.fromisoformat,default=today.replace(day=1))
    parser.add_argument('--end-date',type=date.fromisoformat,default=today-timedelta(days=1))
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    with session_factory()() as session:
        result=backfill_range(session,args.start_date,args.end_date,now=datetime.utcnow(),dry_run=args.dry_run)
    print(json.dumps(result,sort_keys=True))
    return 0 if all(d['status']!='source_error' for d in result['days']) else 1

if __name__=='__main__':
    raise SystemExit(main())

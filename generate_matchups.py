"""Command-line tool to generate daily MLB matchups.

This script provides a simple interface to the analysis pipeline
implemented in the ``mlb_app`` package.  Users can specify a
date to generate matchups for (in ``YYYY-MM-DD`` format); if no
date is provided, today's date is used by default.  The script
prints the resulting matchups as pretty-printed JSON.

Example usage:

.. code-block:: bash

   python generate_matchups.py --date 2026-04-15

   # or simply
   python generate_matchups.py

The underlying pipeline integrates schedule, team records, platoon
splits and pitcher statistics to produce a list of feature
dictionaries.  Note that Statcast metrics may be empty until
``statcast_utils`` functions are implemented with real data
retrieval.
"""

import argparse
import datetime
import json
from typing import List, Dict

from mlb_app.analysis_pipeline import generate_daily_matchups


def main() -> None:
    """Parse arguments and generate matchups."""
    parser = argparse.ArgumentParser(
        description="Generate daily MLB matchups with advanced statistics"
    )
    parser.add_argument(
        "--date",
        type=str,
        help="Date in YYYY-MM-DD format (default: today)",
        default=None,
    )
    args = parser.parse_args()
    if args.date:
        try:
            datetime.datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError as exc:
            raise SystemExit(
                f"Invalid date format: {args.date}. Use YYYY-MM-DD"
            ) from exc
        date_str = args.date
    else:
        date_str = datetime.date.today().isoformat()
    # Generate matchups
    matchups: List[Dict] = generate_daily_matchups(date_str)
    # Print as pretty JSON
    print(json.dumps(matchups, indent=2))


if __name__ == "__main__":
    main()

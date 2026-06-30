"""Regenerate the committed figures and seed/append the metrics history.

Run via: python scripts/generate_outputs.py [--level standard] [--date YYYY-MM-DD]
This is what the daily routine effectively does on a "kept" day; running it by
hand keeps figures/ and metrics_history.csv in sync with the current code.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pokerbot.metrics import append_history, compute_metrics, flatten
from pokerbot.visualize import generate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="standard",
                    choices=["quick", "standard", "full"])
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--no-history", action="store_true")
    args = ap.parse_args()

    print(f"computing metrics (level={args.level})...", flush=True)
    m = compute_metrics(level=args.level)
    summary = flatten(m)
    print(json.dumps(summary, indent=2), flush=True)

    # Append history first so the progress chart includes today's point.
    if not args.no_history:
        append_history(summary, args.date)
        print(f"appended metrics_history.csv for {args.date}", flush=True)

    written = generate(m)
    print("figures:", flush=True)
    for p in written:
        print("  " + p, flush=True)


if __name__ == "__main__":
    main()

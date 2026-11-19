"""Merge every annotator's judgements for one data file into a single CSV.

    python export_all.py --data data/sample.jsonl --out annotations --csv results.csv
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import core


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--data", required=True, help="the data file that was annotated")
    p.add_argument("--out", default="annotations", help="annotation folder used by the app")
    p.add_argument("--csv", default="all_annotations.csv", help="CSV file to write")
    args = p.parse_args()

    try:
        items = core.load_items(args.data)
    except (core.DataError, OSError) as e:
        print(f"Problem with data file: {e}", file=sys.stderr)
        return 1

    folder = core.store_path(args.out, args.data, "x").parent
    files = sorted(folder.glob("*.json"))
    if not files:
        print(f"No annotation files found in {folder}", file=sys.stderr)
        return 1

    rows = []
    for f in files:
        try:
            annotations = core.read_store(f)
        except core.StoreError as e:
            print(f"Skipping {f.name}: {e}", file=sys.stderr)
            continue
        rows += core.csv_rows(items, annotations, f.stem)

    Path(args.csv).write_bytes(core.to_csv_bytes(rows))
    print(f"Wrote {len(rows)} rows from {len(files)} annotator file(s) to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

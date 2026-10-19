"""Render the FX training charts for visual-audit loop 3-12.

The cutoffs below were fixed from the article text and pre-entry source charts.
This module deliberately does not read the 3-12 manifest or fixed split.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oku100.io import read_bars
from scripts.visual_audit_render_3_12 import prepare_panels, render_panel


DATA_FILES = {
    "EURUSD": {tf: ROOT / "data" / f"eurusd_{tf}.csv" for tf in ("d1", "h4", "h1", "m15")},
    "USDJPY": {tf: ROOT / "data" / f"usdjpy_{tf}.csv" for tf in ("d1", "h4", "h1", "m15")},
}

# judgment_ts is the instant immediately before the entry/trigger bar.  Only
# bars whose close is <= judgment_ts are rendered by prepare_panels().
TRAINING_CASES = (
    ("T01", "EURUSD", "2018-04-27T14:00:00+00:00"),
    ("T02", "EURUSD", "2020-01-31T11:00:00+00:00"),
    ("T03", "USDJPY", "2020-03-17T14:00:00+00:00"),
    ("T04", "USDJPY", "2020-03-25T22:00:00+00:00"),
    ("T05", "USDJPY", "2020-03-31T13:00:00+00:00"),
    ("T06", "USDJPY", "2020-04-13T00:00:00+00:00"),
    ("T07", "USDJPY", "2020-04-28T09:00:00+00:00"),
    ("T08", "EURUSD", "2020-11-27T03:00:00+00:00"),
    ("T09", "USDJPY", "2020-12-15T13:00:00+00:00"),
    ("T10", "USDJPY", "2021-01-05T03:00:00+00:00"),
    ("T11", "USDJPY", "2021-02-01T08:00:00+00:00"),
    ("T12", "USDJPY", "2021-02-15T07:00:00+00:00"),
    ("T13", "EURUSD", "2021-02-25T07:00:00+00:00"),
    ("T14", "USDJPY", "2021-07-19T06:00:00+00:00"),
    ("T15", "USDJPY", "2021-07-21T06:45:00+00:00"),
    ("T17", "USDJPY", "2022-02-08T00:00:00+00:00"),
    ("T18", "USDJPY", "2022-04-04T10:00:00+00:00"),
    ("T19", "USDJPY", "2022-05-18T13:00:00+00:00"),
    ("T20", "USDJPY", "2022-07-13T00:00:00+00:00"),
    ("T21", "USDJPY", "2022-11-08T09:00:00+00:00"),
    ("T23", "USDJPY", "2023-02-15T06:00:00+00:00"),
    ("T24", "USDJPY", "2023-03-17T11:00:00+00:00"),
    ("T25", "USDJPY", "2023-03-20T06:00:00+00:00"),
    ("T26", "USDJPY", "2023-05-16T12:00:00+00:00"),
    ("T27", "USDJPY", "2023-07-20T12:00:00+00:00"),
    ("T28", "USDJPY", "2023-08-29T10:00:00+00:00"),
    ("T29", "USDJPY", "2023-11-09T18:00:00+00:00"),
    ("T30", "USDJPY", "2023-11-22T05:15:00+00:00"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="docs/visual_audit_3_12/training_charts")
    parser.add_argument("--ids", help="comma-separated training IDs; default is all usable cases")
    args = parser.parse_args()

    selected = {item.strip() for item in args.ids.split(",")} if args.ids else None
    known = {case_id for case_id, _, _ in TRAINING_CASES}
    if selected is not None and not selected <= known:
        raise ValueError(f"unknown IDs: {','.join(sorted(selected - known))}")

    cache = {
        symbol: {tf: read_bars(path) for tf, path in paths.items()}
        for symbol, paths in DATA_FILES.items()
    }
    out_dir = ROOT / args.out_dir
    for case_id, symbol, value in TRAINING_CASES:
        if selected is not None and case_id not in selected:
            continue
        judgment_ts = datetime.fromisoformat(value)
        panels = prepare_panels(cache[symbol], judgment_ts)
        for timeframe, panel in panels.items():
            out_path = out_dir / f"{case_id}_{timeframe}.png"
            render_panel(panel, timeframe, out_path)
            print(f"saved {out_path.relative_to(ROOT)} cutoff={value}")


if __name__ == "__main__":
    main()

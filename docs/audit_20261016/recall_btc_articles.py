"""Source recall: does the default pipeline produce the source BTC trades?

Read-only. For each source BTC trade in realtrade_btc.csv the window is the
article date (JST) +-24 hours, taken as [date - 1 day, date + 2 days) UTC.
Within it, every H1 bar where a stop order in the article's direction fills
is scored with the default Params (strict gate, all changes up to
execution_spec 7-6), and the failing criteria are listed. No fill at all
means D (the trigger) never fired in that direction.
"""
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from oku100.io import read_bars  # noqa: E402
from oku100.leak import AccessAudit, CausalSeries  # noqa: E402
from oku100.pipeline import DecisionPipeline  # noqa: E402

STRICT = ("A", "C", "D", "E", "F")


def main():
    d1, h4, h1, m15 = (read_bars(ROOT / "data" / f"{n}.csv") for n in ("d1", "h4", "h1", "m15"))
    rows = list(csv.DictReader(open(ROOT / "realtrade_btc.csv", encoding="utf-8-sig")))
    pipeline = DecisionPipeline(m15=m15)
    position = {bar.timestamp: index for index, bar in enumerate(h1)}
    out = []
    for row in sorted(rows, key=lambda r: r["date"]):
        day = datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc)
        direction = 1 if row["direction"] == "買い" else -1
        fills = []
        for hour in range(24 * 3):
            ts = day - timedelta(days=1) + timedelta(hours=hour)
            if ts not in position:
                continue
            indexes = pipeline._resolve_indexes(d1, h4, h1, ts)
            causal = [CausalSeries(s, i, AccessAudit(i)) for s, i in zip((d1, h4, h1), indexes)]
            d1s, h4s, h1s = pipeline._states(causal, indexes)
            if pipeline._stop_entry_fill(h1s, direction) is None:
                continue
            result = pipeline._score_at_order_time(direction, d1s, h4s, h1s, 0)
            criteria = result["criteria"]
            failed = [name for name in STRICT if not criteria[name].passed]
            if not (criteria["B"].passed or criteria["B-2"].passed):
                failed.append("B/B-2")
            if not result["alignment"]["passed"]:
                failed.append("aligned")
            shape = "wave_from_H4_MA=True" in criteria["E"].evidence
            fills.append({
                "timestamp": ts.isoformat(),
                "entry": result["entry"],
                "stop": result["stop"],
                "strict": not failed,
                "failed": failed,
                "E_shape": shape,
                "F": criteria["F"].evidence,
            })
        out.append({
            "date": row["date"],
            "direction": row["direction"],
            "pattern": row["pattern"],
            "fills": fills,
        })
    path = Path(__file__).with_name("recall_btc_articles.json")
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    for item in out:
        print(item["date"], item["direction"], len(item["fills"]), "fills")
        for fill in item["fills"]:
            print("   ", fill["timestamp"][5:16], round(fill["entry"]), "strict" if fill["strict"] else fill["failed"],
                  "shape" if fill["E_shape"] else "no-shape", fill["F"][:24])


if __name__ == "__main__":
    main()

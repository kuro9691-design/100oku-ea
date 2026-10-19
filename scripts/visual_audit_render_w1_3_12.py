"""Render blind W1 charts for the existing 28-sample visual-audit set."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd

from oku100.io import read_bars
from oku100.models import Bar
DATA = {"BTC": "data/d1.csv", "ETH": "data/eth_d1.csv"}
MA_PERIODS = (20, 80)
MA_COLORS = ("#4488ff", "#ff4444")
WINDOW = 180


def aggregate_closed_weeks(daily_bars: list[Bar], judgment_ts: datetime) -> list[Bar]:
    """Aggregate only fully closed Monday-UTC weeks before judgment_ts."""
    buckets: dict[datetime, list[Bar]] = {}
    for bar in daily_bars:
        ts = bar.timestamp.astimezone(timezone.utc)
        week_start = (ts - timedelta(days=ts.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        if week_start + timedelta(days=7) <= judgment_ts:
            buckets.setdefault(week_start, []).append(bar)
    out = []
    for week_start in sorted(buckets):
        bars = sorted(buckets[week_start], key=lambda b: b.timestamp)
        out.append(Bar(week_start, bars[0].open, max(b.high for b in bars), min(b.low for b in bars), bars[-1].close))
    return out


def rolling_sma(values: list[float], period: int) -> list[float]:
    series = pd.Series(values, dtype="float64")
    return series.rolling(period).mean().tolist()


def render(weekly: list[Bar], out_path: Path) -> None:
    bars = weekly[-WINDOW:]
    frame = pd.DataFrame(
        {"Open": [b.open for b in bars], "High": [b.high for b in bars],
         "Low": [b.low for b in bars], "Close": [b.close for b in bars],
         "Volume": [0.0] * len(bars)},
        index=pd.DatetimeIndex([b.timestamp for b in bars], tz="UTC"),
    )
    market = mpf.make_marketcolors(up="#cccccc", down="#202020", edge="inherit", wick="inherit")
    style = mpf.make_mpf_style(base_mpf_style="nightclouds", marketcolors=market,
                               facecolor="#0a0e1a", figcolor="#0a0e1a", gridcolor="#1a2035")
    fig, axes = mpf.plot(frame, type="candle", style=style, returnfig=True, figsize=(11, 7))
    ax = axes[0]
    xs = np.arange(len(bars))
    closes = [b.close for b in bars]
    for period, color in zip(MA_PERIODS, MA_COLORS):
        ax.plot(xs, rolling_sma(closes, period), color=color, lw=1.2, label=f"MA{period}")
    ax.set_yticklabels([])
    ax.set_ylabel("")
    ticks = np.linspace(0, max(len(bars) - 1, 1), 6)
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(int(x)) for x in ticks])
    ax.set_xlabel("")
    ax.legend(loc="upper left", fontsize=8, facecolor="#111827", edgecolor="#334155",
              labelcolor="#cccccc", framealpha=0.85, ncol=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, facecolor="#0a0e1a", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="docs/visual_audit_20261017/manifest_ground_truth.json")
    parser.add_argument("--out-dir", default="docs/visual_audit_20261017/charts")
    parser.add_argument("--ids")
    args = parser.parse_args()
    manifest = json.loads((ROOT / args.manifest).read_text(encoding="utf-8"))
    wanted = set(args.ids.split(",")) if args.ids else None
    cache = {symbol: read_bars(str(ROOT / path)) for symbol, path in DATA.items()}
    for sample in manifest["samples"]:
        if wanted and sample["id"] not in wanted:
            continue
        weekly = aggregate_closed_weeks(cache[sample["symbol"]], datetime.fromisoformat(sample["judgment_ts"]))
        render(weekly, ROOT / args.out_dir / f"{sample['id']}_w1.png")
        print(f"saved {sample['id']}_w1.png")


if __name__ == "__main__":
    main()

"""Render blind five-timeframe charts for visual-audit loop 3-12.

Only id, symbol, judgment_ts, and ts_source are projected from the manifest.
No evaluation truth is returned, logged, or drawn.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
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

from chart_view import CANDLE_DN, CANDLE_UP, DARK_BG, EDGE_DN, EDGE_UP, GRID_CLR, _bars_to_df
from oku100.io import read_bars
from oku100.models import Bar
from scripts.render_candidate_charts import (
    MA_COLOR,
    MA_PERIODS_D1,
    MA_PERIODS_H1,
    MA_PERIODS_H4,
    MA_PERIODS_M15,
    MA_PERIODS_W1,
)

WINDOWS = {"w1": 156, "d1": 365, "h4": 360, "h1": 180, "m15": 180}
PERIODS = {
    "w1": MA_PERIODS_W1,
    "d1": MA_PERIODS_D1,
    "h4": MA_PERIODS_H4,
    "h1": MA_PERIODS_H1,
    "m15": MA_PERIODS_M15,
}
BAR_LENGTH = {
    "d1": timedelta(days=1),
    "h4": timedelta(hours=4),
    "h1": timedelta(hours=1),
    "m15": timedelta(minutes=15),
}
DATA_FILES = {
    "BTC": {tf: f"data/ext_20261019/btcusdt/{tf}.csv" for tf in ("d1", "h4", "h1", "m15")},
    "ETH": {tf: f"data/ext_20261019/ethusdt/{tf}.csv" for tf in ("d1", "h4", "h1", "m15")},
}


@dataclass(frozen=True)
class PanelData:
    bars: list[Bar]
    ma_values: dict[int, list[float]]


def load_manifest_projection(path: Path) -> list[dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [
        {key: sample[key] for key in ("id", "symbol", "judgment_ts", "ts_source")}
        for sample in raw["samples"]
    ]


def load_group_ids(path: Path, group: str) -> set[str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {item["id"] for item in raw[group]}


def reject_final_ids(ids: set[str], final_ids: set[str], allow_final_test: bool) -> None:
    blocked = sorted(ids & final_ids)
    if blocked and not allow_final_test:
        raise ValueError("final-test IDs are sealed; pass --allow-final-test only at the authorized final run")


def confirmed_before(bars: list[Bar], judgment_ts: datetime, timeframe: str) -> list[Bar]:
    length = BAR_LENGTH[timeframe]
    return [bar for bar in bars if bar.timestamp + length <= judgment_ts]


def resample_closed_weeks(d1_bars: list[Bar], judgment_ts: datetime) -> list[Bar]:
    buckets: dict[datetime, list[Bar]] = {}
    for bar in d1_bars:
        ts = bar.timestamp.astimezone(timezone.utc)
        week_start = (ts - timedelta(days=ts.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        if week_start + timedelta(days=7) <= judgment_ts:
            buckets.setdefault(week_start, []).append(bar)
    weeks: list[Bar] = []
    for week_start in sorted(buckets):
        days = sorted(buckets[week_start], key=lambda bar: bar.timestamp)
        weeks.append(Bar(
            week_start,
            days[0].open,
            max(bar.high for bar in days),
            min(bar.low for bar in days),
            days[-1].close,
        ))
    return weeks


def panel_data(all_confirmed: list[Bar], timeframe: str) -> PanelData:
    window = WINDOWS[timeframe]
    if len(all_confirmed) < window:
        raise ValueError(f"{timeframe}: only {len(all_confirmed)} confirmed bars; {window} required")
    closes = pd.Series([bar.close for bar in all_confirmed], dtype="float64")
    bars = all_confirmed[-window:]
    ma_values = {
        period: closes.rolling(period).mean().iloc[-window:].tolist()
        for period in PERIODS[timeframe]
    }
    return PanelData(bars, ma_values)


def prepare_panels(data: dict[str, list[Bar]], judgment_ts: datetime) -> dict[str, PanelData]:
    confirmed = {
        tf: confirmed_before(data[tf], judgment_ts, tf)
        for tf in ("d1", "h4", "h1", "m15")
    }
    confirmed["w1"] = resample_closed_weeks(data["d1"], judgment_ts)
    return {tf: panel_data(confirmed[tf], tf) for tf in ("w1", "d1", "h4", "h1", "m15")}


def _style() -> object:
    return mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mpf.make_marketcolors(
            up=CANDLE_UP,
            down=CANDLE_DN,
            edge={"up": EDGE_UP, "down": EDGE_DN},
            wick={"up": EDGE_UP, "down": EDGE_DN},
            volume="inherit",
        ),
        facecolor=DARK_BG,
        edgecolor=GRID_CLR,
        gridcolor=GRID_CLR,
        gridstyle="--",
        gridaxis="both",
        figcolor=DARK_BG,
    )


def render_panel(panel: PanelData, timeframe: str, out_path: Path) -> None:
    frame = _bars_to_df(panel.bars)
    fig, axes = mpf.plot(
        frame,
        type="candle",
        style=_style(),
        returnfig=True,
        figsize=(12, 7),
        volume=False,
    )
    ax = axes[0]
    xs = np.arange(len(panel.bars))
    for period in PERIODS[timeframe]:
        ax.plot(xs, panel.ma_values[period], color=MA_COLOR[timeframe][period], lw=1.1, label=f"MA{period}")
    ticks = np.linspace(0, len(panel.bars) - 1, 6)
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(int(value)) for value in ticks])
    ax.set_yticks([])
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.legend(loc="upper left", fontsize=8, facecolor="#111827", edgecolor="#334155", labelcolor="#cccccc")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor=DARK_BG, bbox_inches="tight")
    plt.close(fig)


def parse_ids(value: str | None, available: set[str]) -> set[str]:
    if value is None:
        return set(available)
    return {item.strip() for item in value.split(",") if item.strip()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="docs/visual_audit_20261017/manifest_ground_truth.json")
    parser.add_argument("--fixed-split", default="docs/visual_audit_3_12/fixed_split.json")
    parser.add_argument("--out-dir", default="docs/visual_audit_3_12/charts")
    parser.add_argument("--ids", help="comma-separated sample IDs")
    parser.add_argument("--allow-final-test", action="store_true")
    args = parser.parse_args()

    samples = load_manifest_projection(ROOT / args.manifest)
    by_id = {sample["id"]: sample for sample in samples}
    wanted = parse_ids(args.ids, set(by_id))
    unknown = sorted(wanted - set(by_id))
    if unknown:
        raise ValueError(f"unknown IDs: {','.join(unknown)}")
    final_ids = load_group_ids(ROOT / args.fixed_split, "final_test_group_sealed")
    reject_final_ids(wanted, final_ids, args.allow_final_test)

    cache: dict[str, dict[str, list[Bar]]] = {}
    for sample_id in sorted(wanted):
        sample = by_id[sample_id]
        symbol = sample["symbol"]
        if symbol not in DATA_FILES:
            raise ValueError(f"{sample_id}: unsupported symbol {symbol}")
        if symbol not in cache:
            cache[symbol] = {tf: read_bars(ROOT / path) for tf, path in DATA_FILES[symbol].items()}
        judgment_ts = datetime.fromisoformat(sample["judgment_ts"].replace("Z", "+00:00"))
        panels = prepare_panels(cache[symbol], judgment_ts)
        for timeframe, panel in panels.items():
            out_path = ROOT / args.out_dir / f"{sample_id}_{timeframe}.png"
            render_panel(panel, timeframe, out_path)
            print(f"saved {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

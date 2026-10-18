"""PH-52 / 周回3-2: 固定24時点の未来MAを一括測定する。

主仮定は判断時点の終値で将来48本を横ばいにする。対照18件と正例6本は
docs/pending_hypotheses.md の事前登録から変更しない。実際の未来足は使わない。
"""
from __future__ import annotations

import csv
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import mannwhitneyu

from oku100.indicators import atr, confirmed_pivots, sma
from oku100.io import read_bars
from oku100.models import Bar
from scripts.render_future_scenario import _last_confirmed, project_ma_lines

HORIZON = 48
PERIODS = (20, 80, 480)
SEED = 20261018
OUT_DIR = ROOT / "docs" / "future_ma_20261018"

POSITIVES = [
    ("2024-06-04", "2024-06-03T04:00:00+00:00", "horizontal_line"),
    ("2024-07-28", "2024-07-27T12:00:00+00:00", "horizontal_line"),
    ("2025-02-23", "2025-02-23T10:00:00+00:00", "other"),
    ("2025-03-09", "2025-03-08T17:00:00+00:00", "other"),
    ("2025-03-28", "2025-03-28T06:00:00+00:00", "other"),
    ("2026-01-13", "2026-01-13T09:00:00+00:00", "other"),
]

CONTROLS = [
    "2026-01-09T14:00:00+00:00", "2024-11-19T20:00:00+00:00",
    "2025-02-15T17:00:00+00:00", "2026-01-08T04:00:00+00:00",
    "2024-08-12T03:00:00+00:00", "2025-06-01T04:00:00+00:00",
    "2025-07-01T22:00:00+00:00", "2025-07-31T01:00:00+00:00",
    "2024-09-16T13:00:00+00:00", "2024-12-03T11:00:00+00:00",
    "2024-08-06T20:00:00+00:00", "2025-09-18T12:00:00+00:00",
    "2025-01-07T22:00:00+00:00", "2024-12-27T16:00:00+00:00",
    "2025-08-21T01:00:00+00:00", "2024-11-09T11:00:00+00:00",
    "2025-12-05T11:00:00+00:00", "2025-07-27T10:00:00+00:00",
]


@dataclass
class PairMetrics:
    min_gap: float
    h_min: int
    converges: bool
    h_expand: int | None
    turn: bool


def _projection(history: list[float], assumed_price: float) -> dict[int, list[float]]:
    future = project_ma_lines(history, [assumed_price] * HORIZON, list(PERIODS))
    return {
        period: [sum(history[-period:]) / period] + future[period]
        for period in PERIODS
    }


def _pair_metrics(lines: dict[int, list[float]], a: int, b: int, atr0: float) -> PairMetrics:
    gaps = [abs(x - y) / atr0 for x, y in zip(lines[a], lines[b])]
    h_min = int(np.argmin(gaps))
    h_expand = next((h for h in range(h_min + 1, len(gaps)) if gaps[h] > gaps[h - 1]), None)
    converges = gaps[h_min] < gaps[0]
    return PairMetrics(gaps[h_min], h_min, converges, h_expand, converges and h_expand is not None)


def _ordering(lines: dict[int, list[float]], h: int | None) -> str | None:
    if h is None:
        return None
    values = [(lines[p][h], p) for p in PERIODS]
    return " < ".join(f"MA{p}" for _, p in sorted(values))


def _slopes(lines: dict[int, list[float]], h: int | None, atr0: float) -> dict[str, float | None]:
    if h is None or h == 0:
        return {f"slope_{p}": None for p in PERIODS}
    return {f"slope_{p}": (lines[p][h] - lines[p][h - 1]) / atr0 for p in PERIODS}


def _latest_h1_level(h1: list[Bar], end_idx: int) -> float:
    pivots = confirmed_pivots(h1, end_idx, 3)
    if not pivots:
        raise ValueError("no confirmed H1 pivot")
    return max(pivots, key=lambda p: p.index).price


def measure(h1: list[Bar], timestamp: str, assumed: str) -> tuple[dict, dict[int, list[float]], int]:
    judgment = datetime.fromisoformat(timestamp)
    end_idx = _last_confirmed(h1, judgment, timedelta(hours=1))
    history = [b.close for b in h1[:end_idx + 1]]
    if len(history) < max(PERIODS):
        raise ValueError(f"MA480 not warmed at {timestamp}")
    atr0 = atr(h1, end_idx, 14)
    assumed_price = history[-1] if assumed == "flat_close" else _latest_h1_level(h1, end_idx)
    lines = _projection(history, assumed_price)
    p1 = _pair_metrics(lines, 20, 80, atr0)
    p2 = _pair_metrics(lines, 80, 480, atr0)
    result = {
        "timestamp": timestamp,
        "judgment_bar_timestamp": h1[end_idx].timestamp.isoformat(),
        "assumption": assumed,
        "assumed_price": assumed_price,
        "atr0": atr0,
        "pair1_min_gap": p1.min_gap,
        "pair1_h_min": p1.h_min,
        "pair1_converges": p1.converges,
        "pair1_h_expand": p1.h_expand,
        "pair1_turn_reference_only": p1.turn,
        "pair2_min_gap": p2.min_gap,
        "pair2_h_min": p2.h_min,
        "pair2_converges": p2.converges,
        "pair2_h_expand": p2.h_expand,
        "pair2_turn_reference_only": p2.turn,
        "ordering_at_pair1_expand": _ordering(lines, p1.h_expand),
        **_slopes(lines, p1.h_expand, atr0),
    }
    return result, lines, end_idx


def _render(h1: list[Bar], end_idx: int, lines: dict[int, list[float]], case_id: str, out: Path) -> None:
    start = max(0, end_idx - 179)
    history = h1[start:end_idx + 1]
    x_hist = np.arange(len(history))
    x_future = np.arange(len(history) - 1, len(history) + HORIZON)
    colors = {20: "#2f80ed", 80: "#eb5757", 480: "#f2c94c"}
    fig, ax = plt.subplots(figsize=(12, 6), facecolor="#0b1020")
    ax.set_facecolor("#0b1020")
    ax.plot(x_hist, [b.close for b in history], color="#9aa4b2", lw=0.8, alpha=0.65, label="H1 close")
    for period in PERIODS:
        hist_ma = [sma(h1, i, period) if i + 1 >= period else np.nan for i in range(start, end_idx + 1)]
        ax.plot(x_hist, hist_ma, color=colors[period], lw=1.0, alpha=0.75)
        ax.plot(x_future, lines[period], color=colors[period], lw=2.0, linestyle="--", label=f"MA{period} projection")
    ax.axvline(len(history) - 1, color="white", lw=0.8, alpha=0.6)
    ax.set_title(f"PH-52 future MA projection — {case_id}", color="white")
    ax.tick_params(colors="#c9d1d9")
    ax.grid(color="#243047", alpha=0.35)
    ax.legend(facecolor="#111827", labelcolor="white", fontsize=8)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    h1 = read_bars(str(ROOT / "data" / "h1.csv"))
    cases = [
        {"group": "positive", "article_date": date, "timestamp": ts, "support_group": support}
        for date, ts, support in POSITIVES
    ] + [
        {"group": "control", "article_date": None, "timestamp": ts, "support_group": "control"}
        for ts in CONTROLS
    ]
    order = list(range(len(cases)))
    random.Random(SEED).shuffle(order)
    for n, i in enumerate(order, 1):
        cases[i]["case_id"] = f"M{n:02d}"
    cases.sort(key=lambda c: c["case_id"])

    main_rows, sensitivity_rows = [], []
    for case in cases:
        main_result, lines, end_idx = measure(h1, case["timestamp"], "flat_close")
        sensitivity_result, _, _ = measure(h1, case["timestamp"], "latest_h1_pivot")
        row = {**case, **main_result}
        main_rows.append(row)
        sensitivity_rows.append({**case, **sensitivity_result})
        _render(h1, end_idx, lines, case["case_id"], OUT_DIR / "images" / f"{case['case_id']}.png")

    positives = [r["pair1_min_gap"] for r in main_rows if r["group"] == "positive"]
    controls = [r["pair1_min_gap"] for r in main_rows if r["group"] == "control"]
    control_median = float(np.median(controls))
    u = mannwhitneyu(positives, controls, alternative="two-sided")
    summary = {
        "primary": {
            "positive_below_control_median": sum(x < control_median for x in positives),
            "positive_count": len(positives),
            "control_median": control_median,
            "positive_median": float(np.median(positives)),
            "positive_range": [min(positives), max(positives)],
            "control_range": [min(controls), max(controls)],
            "mann_whitney_u": float(u.statistic),
            "mann_whitney_p_two_sided_reference": float(u.pvalue),
        },
        "seed": SEED,
        "horizon": HORIZON,
        "expansion_is_reference_only": True,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in (("main_flat.csv", main_rows), ("sensitivity_latest_h1_pivot.csv", sensitivity_rows)):
        with (OUT_DIR / name).open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (OUT_DIR / "results.json").write_text(
        json.dumps({"summary": summary, "main": main_rows, "sensitivity": sensitivity_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

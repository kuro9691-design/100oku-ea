"""判断時点で固定する「条件付き未来シナリオ」を描画する。

未来の値動きは読まない。判断時点までに確定したH1/H4ピボットと
H1 ATRから、想定経路、監視開始帯、トリガー、無効化、T1を固定する。
0.8×H1 ATRは監視開始帯の参考幅であり、単独の合否条件ではない。

Usage:
    python scripts/render_future_scenario.py --timestamp 2024-07-27T12:00:00+00:00 --direction buy
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np

from chart_view import _bars_to_df
from oku100.indicators import atr, confirmed_pivots
from oku100.indicators import sma
from oku100.io import read_bars
from oku100.models import Bar, Pivot
from oku100.pipeline import DecisionPipeline
from scripts.render_candidate_charts import (
    DARK_BG,
    GRID_CLR,
    MA_COLOR,
    MA_PERIODS_H1,
    _ma_h1,
    _style,
)

# PH-51 remains a preregistered visual reference after the pipeline experiment
# was stopped. Keep it local to this scenario renderer; it is not an EA gate.
SCENARIO_LEVEL_DISTANCE_ATR = 0.8


@dataclass(frozen=True)
class Scenario:
    timestamp: str
    direction: str
    current: float
    support_or_resistance: float
    support_type: str
    alert_band_low: float
    alert_band_high: float
    trigger: float
    invalidation: float
    target_1: float
    h1_atr: float
    rr_to_t1: float
    status: str
    geometry_warnings: list[str]
    rationale: list[str]


def _last_confirmed(bars: list[Bar], judgment_ts: datetime, interval: timedelta) -> int:
    idx = next(
        (i for i in reversed(range(len(bars))) if bars[i].timestamp + interval <= judgment_ts),
        None,
    )
    if idx is None:
        raise ValueError(f"no confirmed bar before {judgment_ts.isoformat()}")
    return idx


def _latest(pivots: list[Pivot], kind: str) -> Pivot:
    match = next((p for p in reversed(pivots) if p.kind == kind), None)
    if match is None:
        raise ValueError(f"no confirmed {kind} pivot")
    return match


def scenario_geometry_warnings(
    direction: str, invalidation: float, support_or_resistance: float,
) -> list[str]:
    """Flag a visually counter-intuitive support/invalidation ordering.

    This is deliberately diagnostic only.  The H1 invalidation pivot and the
    H4 support/resistance level come from different source-defined structures,
    so the warning must not silently move either price or change the scenario
    status.
    """
    if direction == "buy" and invalidation >= support_or_resistance:
        return ["BUY_INVALIDATION_NOT_BELOW_SUPPORT"]
    if direction == "sell" and invalidation <= support_or_resistance:
        return ["SELL_INVALIDATION_NOT_ABOVE_RESISTANCE"]
    return []


def build_scenario(
    h1: list[Bar], h4: list[Bar], judgment_ts: datetime, direction: str,
) -> tuple[Scenario, int]:
    h1_idx = _last_confirmed(h1, judgment_ts, timedelta(hours=1))
    h4_idx = _last_confirmed(h4, judgment_ts, timedelta(hours=4))
    h1_pivots = confirmed_pivots(h1, h1_idx, 3)
    pipeline = DecisionPipeline()
    d1_path = ROOT / "data" / "d1.csv"
    d1 = read_bars(str(d1_path))
    state_indexes = pipeline._resolve_indexes(d1, h4, h1, h1[h1_idx].timestamp)
    d1_state, h4_state, h1_state = pipeline._states((d1, h4, h1), state_indexes)
    current = h1[h1_idx].close

    if direction == "buy":
        invalidation_pivot = _latest(h1_pivots, "low")
        trigger = _latest(h1_pivots, "high").price
    else:
        invalidation_pivot = _latest(h1_pivots, "high")
        trigger = _latest(h1_pivots, "low").price
    invalidation = invalidation_pivot.price
    pivot_atr = atr(h1, invalidation_pivot.index, pipeline.params.atr_period)
    h4_ma = sma(h1, invalidation_pivot.index, pipeline.params.h1_slow_ma_period)
    h4_lines = pipeline._h4_lines(d1_state, h4_state)
    line = min(h4_lines, key=lambda level: abs(level - invalidation), default=None)
    support_candidates: list[tuple[float, str, float]] = []
    if abs(h4_ma - invalidation) <= pipeline.params.k1 * pivot_atr:
        support_candidates.append((h4_ma, "H4_MA", pipeline.params.k1))
    if line is not None and abs(line - invalidation) <= SCENARIO_LEVEL_DISTANCE_ATR * pivot_atr:
        support_candidates.append((line, "H4_HORIZONTAL_LINE", SCENARIO_LEVEL_DISTANCE_ATR))
    if not support_candidates:
        raise ValueError("no source-defined H4 MA/line support near the H1 invalidation pivot")
    base, support_type, support_width_atr = min(
        support_candidates, key=lambda item: abs(item[0] - invalidation)
    )

    direction_int = 1 if direction == "buy" else -1
    target = pipeline._first_target(d1_state, h4_state, trigger, direction_int)
    if target is None:
        raise ValueError("no source-defined opposing H4/D1 structure available for T1")
    risk = abs(trigger - invalidation)
    rr = abs(target - trigger) / risk if risk else 0.0
    band_low, band_high = base - support_width_atr * pivot_atr, base + support_width_atr * pivot_atr
    geometry_warnings = scenario_geometry_warnings(direction, invalidation, base)

    scenario = Scenario(
        timestamp=judgment_ts.isoformat(), direction=direction, current=current,
        support_or_resistance=base, support_type=support_type,
        alert_band_low=band_low, alert_band_high=band_high,
        trigger=trigger, invalidation=invalidation, target_1=target, h1_atr=pivot_atr,
        rr_to_t1=rr, status="watch" if rr >= 1.0 else "skip_rr_below_1",
        geometry_warnings=geometry_warnings,
        rationale=[
            f"押し・戻りの支え候補は{support_type}（H1の節の位置で照合）",
            "赤線は支えではなく、エントリー根拠が崩れるH1の節",
            "H1ダウ転換後の直近高値・安値抜けに逆指値を置く",
            "T1はトリガーより先の最寄りH4構造、無ければD1構造",
        ],
    )
    return scenario, h1_idx


def project_ma_lines(history: list[float], future: list[float], periods: list[int]) -> dict[int, list[float]]:
    """条件付き将来終値を追加した場合のSMAを再計算する。

    予測ラインは実際の未来足ではなく、「この価格シナリオならMAがどう曲がるか」の
    条件付き計算である。
    """
    values = list(history)
    warmed_at_judgment = {period: len(values) >= period for period in periods}
    result = {period: [] for period in periods}
    for close in future:
        values.append(close)
        for period in periods:
            if not warmed_at_judgment[period]:
                result[period].append(float("nan"))
            else:
                result[period].append(sum(values[-period:]) / period)
    return result


def project_flat_future_ma_at_judgment(
    h1: list[Bar], judgment_ts: datetime, horizon: int = 48,
    periods: list[int] | None = None,
) -> tuple[dict[int, list[float]], int]:
    """PH-52 projection using confirmed history and the judgment close only.

    Actual rows after ``judgment_ts`` are deliberately excluded. A period that
    is not warmed up at the judgment point stays unavailable for the complete
    projection instead of silently averaging a shorter window.
    """
    selected_periods = list(periods or MA_PERIODS_H1)
    end_idx = _last_confirmed(h1, judgment_ts, timedelta(hours=1))
    history = [bar.close for bar in h1[:end_idx + 1]]
    judgment_close = history[-1]
    return (
        project_ma_lines(history, [judgment_close] * horizon, selected_periods),
        end_idx,
    )


def render_scenario(h1: list[Bar], end_idx: int, scenario: Scenario, out_path: Path) -> None:
    window = 180
    future_slots = 45
    start = max(0, end_idx - window + 1)
    visible = h1[start:end_idx + 1]
    df = _bars_to_df(visible)
    xs = np.arange(len(visible))

    fig, axes = mpf.plot(df, type="candle", style=_style(), returnfig=True, figsize=(15, 8))
    ax = axes[0]
    for period in MA_PERIODS_H1:
        ax.plot(xs, _ma_h1(h1, start, end_idx, period), color=MA_COLOR["h1"][period], lw=1.0, alpha=0.85,
                label=f"MA{period}")

    n = len(visible)
    ax.set_xlim(-2, n + future_slots)
    ax.axvspan(n - 0.5, n + future_slots, color="#122033", alpha=0.45, label="Future scenario area")
    ax.axhspan(scenario.alert_band_low, scenario.alert_band_high, color="#f6c344", alpha=0.12,
               label=f"{scenario.support_type} watch band")
    ax.axhline(scenario.support_or_resistance, color="#f6c344", linestyle=":", lw=1.8,
               label="H4 support/resistance")
    ax.axhline(scenario.trigger, color="#20c997", linestyle="--", lw=1.5, label="Trigger candidate")
    ax.axhline(scenario.invalidation, color="#ff5c5c", linestyle="--", lw=1.5,
               label="H1 invalidation reference (SL slightly beyond)")
    ax.axhline(scenario.target_1, color="#8f7cff", linestyle="--", lw=1.5, label="T1 H4 structure")
    if scenario.geometry_warnings:
        relation = (
            f"BUY invalidation {scenario.invalidation:,.2f} is not below "
            f"support {scenario.support_or_resistance:,.2f}"
            if scenario.direction == "buy"
            else f"SELL invalidation {scenario.invalidation:,.2f} is not above "
                 f"resistance {scenario.support_or_resistance:,.2f}"
        )
        ax.text(
            0.99, 0.02, f"GEOMETRY WARNING\n{relation}\nDefinitions unchanged; inspect H1 vs H4 structure.",
            transform=ax.transAxes, ha="right", va="bottom", color="#ffb4b4", fontsize=9,
            bbox={"boxstyle": "round,pad=0.45", "facecolor": "#4a1018", "edgecolor": "#ff5c5c", "alpha": 0.92},
            zorder=20,
        )

    direction_sign = 1 if scenario.direction == "buy" else -1
    path_x = [n - 1, n + 10, n + 22, n + 38]
    # 想定経路はH4支え帯内のH1の節で折り返す。原典のSLは「節のちょっと外」だが
    # 幅の数値はないため、注文価格を発明せず、節自体を無効化基準として描く。
    bounce = scenario.invalidation
    post_trigger = scenario.trigger + direction_sign * abs(scenario.target_1 - scenario.trigger) * 0.18
    path_y = [scenario.current, bounce, post_trigger, scenario.target_1]
    future_x = np.arange(n, n + future_slots + 1)
    future_close = np.interp(future_x, path_x, path_y).tolist()
    projected = project_ma_lines([bar.close for bar in h1[:end_idx + 1]], future_close, MA_PERIODS_H1)
    ax.plot(future_x, future_close, color="#aab4c3", lw=1.0, alpha=0.35, linestyle=":",
            label="Conditional price assumption")
    for period in MA_PERIODS_H1:
        ax.plot(future_x, projected[period], color=MA_COLOR["h1"][period], lw=2.2,
                linestyle=(0, (5, 3)), label=f"Projected MA{period}")

    spreads = [
        max(projected[p][i] for p in MA_PERIODS_H1) - min(projected[p][i] for p in MA_PERIODS_H1)
        for i in range(len(future_x))
    ]
    minimum_i = int(np.argmin(spreads))
    minimum_x = future_x[minimum_i]
    minimum_y = sum(projected[p][minimum_i] for p in MA_PERIODS_H1) / len(MA_PERIODS_H1)
    ax.scatter([minimum_x], [minimum_y], s=90, color="#ffffff", edgecolor="#00d4ff", zorder=12,
               label="Minimum projected MA spread")
    ax.annotate("Minimum projected 3-MA spread\n(not automatically convergence)", (minimum_x, minimum_y), xytext=(-10, -42),
                textcoords="offset points", color="#ffffff", fontsize=9, fontweight="bold")
    ax.annotate("MA20/80 turn upward if trigger breaks", (n + 31, projected[20][31]), xytext=(8, 20),
                textcoords="offset points", color=MA_COLOR["h1"][20], fontsize=9, fontweight="bold")

    ax.set_title(
        f"Conditional 3-MA projection | {scenario.direction.upper()} | visual convergence check | RR={scenario.rr_to_t1:.2f}",
        color="#e8edf7", fontsize=13,
    )
    ax.legend(loc="upper left", fontsize=8, facecolor="#111827", edgecolor=GRID_CLR,
              labelcolor="#dddddd", framealpha=0.9, ncol=2)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, facecolor=DARK_BG, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--direction", choices=["buy", "sell"], required=True)
    parser.add_argument("--h1", default="data/h1.csv")
    parser.add_argument("--h4", default="data/h4.csv")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    judgment_ts = datetime.fromisoformat(args.timestamp)
    h1, h4 = read_bars(args.h1), read_bars(args.h4)
    scenario, h1_idx = build_scenario(h1, h4, judgment_ts, args.direction)
    stamp = judgment_ts.strftime("%Y%m%d_%H%M")
    out_path = Path(args.output) if args.output else ROOT / "charts" / "scenarios" / f"{stamp}_pre.png"
    render_scenario(h1, h1_idx, scenario, out_path)
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(asdict(scenario), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {out_path}")
    print(f"saved {json_path}")
    print(json.dumps(asdict(scenario), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
